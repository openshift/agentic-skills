#!/usr/bin/env bash
# Find hardcoded credentials in a GitOps repo WITHOUT printing their values.
#
# Why this is a script and not a documented grep: the obvious
#   grep -rn -iE "(password|token|secret):" .
# prints the whole matching line, so running it puts the credential straight
# into the agent transcript. An audit that leaks the thing it is auditing for
# is worse than no audit — the finding is the LOCATION, never the value.
#
# This reports file, line, key name and value length. That is enough to triage
# severity and to find the string yourself; it is not enough to use the
# credential. Nothing here writes, and nothing here echoes a secret value.
#
# usage: scan-credentials.sh [repo-root]
# exit:  0 always when it ran (this is a reporting tool, not a gate)
#        2 bad usage
set -uo pipefail

ROOT="${1:-.}"
[[ -d "$ROOT" ]] || { echo "usage: $(basename "$0") [repo-root]" >&2; exit 2; }

# Keys worth flagging, matched as a SUBSTRING of the key name.
#
# An earlier version anchored the whole key — ^(password|token|secret):  — and so
# matched `password:` but silently missed `api-key:`, `webhook-secret:`,
# `connection-string:` and `bearerToken:`. A measured audit run caught it: the
# scanner reported 2 of at least 5 credential locations in one fixture. For a
# security scanner that is the worst failure mode available, because a clean
# result is exactly what the reader acts on. Substring matching now, with an
# explicit denylist below for the structural keys that merely REFERENCE a secret.
KEYS='password|passwd|pwd|token|secret|apikey|api.key|access.?key|private.?key|ssh.?key|credential|connection.?string|dsn|bearer'

# Keys that contain a flagged word but hold no secret: they name or point at one.
# Flagging these is the noise that makes people stop reading credential scans.
NOT_SECRETS='secretName|secretKeyRef|configMapKeyRef|valueFrom|secretRef|tokenSecretRef|topologyKey|secretGenerator|sealedSecret|creationTimestamp'

plain=0; enc=0; synth=0; keys=0

emit() { printf '    %-58s %-16s %s\n' "$1" "$2" "$3"; }

echo "CREDENTIAL SCAN: $ROOT"
echo "  Values are never printed — location, key and length only."
echo

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT

# -I skips binaries. The grep prints whole lines, but nothing downstream emits
# the value portion — only its length. The last filter drops PARENT keys such as
# `stringData:` or `data:` that have nothing after the colon: the secret lives in
# their children, which are matched on their own lines, and reporting the parent
# too would double-count every finding.
grep -rnIE "^[[:space:]]*[\"']?[A-Za-z0-9_.-]*($KEYS)[A-Za-z0-9_.-]*[\"']?[[:space:]]*:" "$ROOT" \
  --include='*.yaml' --include='*.yml' --include='*.json' 2>/dev/null \
  | grep -viE "($NOT_SECRETS)" \
  | grep -vE '^[^:]*:[0-9]+:[[:space:]]*#' \
  | grep -vE ':[[:space:]]*(\{\}|\[\]|\||>)?[[:space:]]*$' \
  > "$tmp" || true

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  file="${line%%:*}"; rest="${line#*:}"
  lineno="${rest%%:*}"; content="${rest#*:}"

  key="$(printf '%s' "$content" | sed -E "s/^[[:space:]]*[\"']?([A-Za-z0-9_.-]+)[\"']?[[:space:]]*:.*/\1/")"
  val="$(printf '%s' "$content" | sed -E 's/^[^:]*:[[:space:]]*//')"
  # Strip a trailing comment before measuring, so "# notsecret" does not
  # inflate the reported length.
  bare="$(printf '%s' "$val" | sed -E 's/[[:space:]]+#.*$//; s/^["'"'"']//; s/["'"'"']$//')"
  n=${#bare}

  loc="${file#./}:$lineno"

  if printf '%s' "$content" | grep -qiE '# *notsecret|EXAMPLE-|CHANGEME|<[a-z-]+>|\$\{|\{\{'; then
    synth=$((synth+1)); emit "$loc" "key=$key" "marked synthetic / templated"
    continue
  fi
  # SOPS and SealedSecrets store ciphertext in these same keys. Flagging them
  # as plaintext is a false positive that trains people to ignore the scanner.
  if grep -qiE 'kind:[[:space:]]*SealedSecret|sops:|ENC\[' "$file" 2>/dev/null; then
    enc=$((enc+1)); emit "$loc" "key=$key" "encrypted at rest — not a finding"
    continue
  fi
  if printf '%s' "$key" | grep -qiE 'ssh.?key|private.?key'; then
    keys=$((keys+1)); emit "$loc" "key=$key" "SSH private key, ${n} chars"
    continue
  fi
  plain=$((plain+1)); emit "$loc" "key=$key" "PLAINTEXT, ${n} chars"
done < "$tmp"

# PEM blocks: report the file only. Never the body, and never the first line,
# which for some formats already carries key material.
pem=0
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  pem=$((pem+1)); emit "${f#./}" "PEM block" "private key material in file"
done < <(grep -rlIE 'BEGIN ([A-Z ]+ )?PRIVATE KEY' "$ROOT" 2>/dev/null || true)

echo
echo "  plaintext: $plain   ssh keys: $keys   PEM files: $pem   synthetic: $synth   encrypted: $enc"
if [[ $((plain + keys + pem)) -gt 0 ]]; then
  echo
  echo "  Treat every plaintext hit as COMPROMISED: it is in git history, so removing it"
  echo "  from HEAD is not sufficient. Rotate first, then purge."
fi
exit 0
