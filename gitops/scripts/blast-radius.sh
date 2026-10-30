#!/usr/bin/env bash
# Resolve what else a change to an Argo CD object would affect, so a recommendation
# can state its impact instead of only its urgency.
#
#   scripts/blast-radius.sh <kind> <name> [namespace]
#
#   scripts/blast-radius.sh ArgoCD openshift-gitops openshift-gitops
#   scripts/blast-radius.sh AppProject team-a openshift-gitops
#   scripts/blast-radius.sh Application payments openshift-gitops
#
# STRICTLY READ-ONLY: only get/api-resources. It never mutates anything.
#
# Why this exists: a diff answers "what changes on this object". Most Argo CD objects
# are fan-out points, so that is rarely the question that matters. A one-field edit to
# an ArgoCD CR looks trivial and restarts components every Application depends on.
#
# Exit codes: 0 = resolved (or nothing affected), 2 = usage, 3 = no cluster reachable,
#             4 = a lookup failed, so the radius is UNKNOWN rather than zero.
# Never non-zero merely because the blast radius is large — callers display, they do
# not gate on it.
set -uo pipefail

KCTL="$(command -v oc >/dev/null 2>&1 && echo oc || echo kubectl)"
KIND="${1:-}"; NAME="${2:-}"; NS="${3:-}"

# Canonicalise the kind before dispatching. `oc` takes lowercase resource names,
# so someone who has just run `oc get applicationset` naturally types
# `applicationset` here too — and a case-sensitive match sent that to the "no
# fan-out rule for kind" branch, which reads like a finding rather than a typo.
# A blast-radius tool that quietly declines to compute is worse than one that
# errors, because the caller reports "impact not computed" and moves on.
case "$(printf '%s' "$KIND" | tr '[:upper:]' '[:lower:]')" in
  argocd|argocds)                    KIND=ArgoCD ;;
  appproject|appprojects)            KIND=AppProject ;;
  applicationset|applicationsets)    KIND=ApplicationSet ;;
  application|applications|app)      KIND=Application ;;
  rolloutmanager|rolloutmanagers)    KIND=RolloutManager ;;
  configmap|configmaps|cm)           KIND=ConfigMap ;;
esac

if [[ -z "$KIND" || -z "$NAME" ]]; then
  cat >&2 <<EOT
usage: $(basename "$0") <kind> <name> [namespace]
  kinds: ArgoCD | AppProject | ApplicationSet | Application | RolloutManager | ConfigMap
EOT
  exit 2
fi

if ! $KCTL api-resources >/dev/null 2>&1; then
  echo "NO CLUSTER REACHABLE — state the impact from the manifests instead, and say it was not verified against a live cluster." >&2
  exit 3
fi

# Full resource names throughout. Short names are ambiguous when ACM/MCE is installed:
# a bare `application` resolves to applications.app.k8s.io and reports NotFound for the
# wrong kind, which reads as "absent" rather than "you asked the wrong API".
APPS=applications.argoproj.io
APPSETS=applicationsets.argoproj.io

# "I could not determine this" must never render as "nothing is affected".
#
# Every count below comes from a `get` that used to be suffixed with 2>/dev/null.
# If the list call fails — RBAC denies it, the CRD is absent, the API times out —
# that produced an empty result, which produced a count of 0, which the caller
# reads as "no fan-out, safe to proceed". That is the same silent-undercount
# failure that made this script report 0 Applications for an ApplicationSet that
# owned two. A tool answering "what else does this touch" has to distinguish
# zero from unknown, and say so loudly when it cannot tell.
# A FILE, not a variable. Most of these lookups run inside $( ), and a variable
# set in a subshell never reaches the parent — so an earlier version printed
# "COULD NOT DETERMINE" to stderr and then cheerfully reported a count of 0 and
# exited 0. That is the exact silent-zero this guard exists to stop, reintroduced
# by the guard itself. The test suite caught it; nothing else would have.
UNKNOWN_FLAG="$(mktemp)"; rm -f "$UNKNOWN_FLAG"
trap 'rm -f "$UNKNOWN_FLAG"' EXIT
unknown_seen() { [[ -e "$UNKNOWN_FLAG" ]]; }
die_unknown() {
  : > "$UNKNOWN_FLAG"
  echo "  !! COULD NOT DETERMINE: $1" >&2
  echo "  !! Treat the blast radius as UNKNOWN, not as zero. Do not proceed on this output." >&2
}

# Run a read and distinguish failure from an empty result.
# Prints output on success; on failure prints nothing and flags UNKNOWN.
try_get() {
  local what="$1"; shift
  local out rc
  out="$($KCTL "$@" 2>&1)"; rc=$?
  if [[ $rc -ne 0 ]]; then
    die_unknown "$what — ${KCTL} exited $rc: $(printf '%s' "$out" | head -1)"
    return 1
  fi
  printf '%s' "$out"
}

# Does a named object exist? Distinguishes absent from unreadable.
exists() {  # exists <resource> <name> [-n ns]
  local out rc
  out="$($KCTL get "$@" -o name 2>&1)"; rc=$?
  [[ $rc -eq 0 ]] && return 0
  if printf '%s' "$out" | grep -qiE 'not found|notfound'; then
    return 1
  fi
  die_unknown "could not read $1/$2 — $(printf '%s' "$out" | head -1)"
  return 2
}

# Report "no such object" distinctly from "exists, affects nothing".
absent_note() {
  echo "  No $1 named '$2'${3:+ in namespace $3} — nothing resolved."
  echo "  This is NOT a statement that the change is safe; the object was not found."
}

# project \t namespace/name \t owner-from-ownerReferences \t owner-from-label
#
# Two owner columns on purpose. The ApplicationSet link is taken primarily from
# ownerReferences, NOT from the argocd.argoproj.io/application-set-name label:
# an ApplicationSet template that declares its own metadata.labels REPLACES the
# controller's default labels, so that label is absent on many real generated
# Applications. Keying off it alone made this script report "Applications
# generated by it: 0" for an ApplicationSet that demonstrably owned two.
# Under-reporting fan-out is the dangerous direction here — it tells the caller
# nothing else is affected when things are. The label is kept as a fallback for
# Applications whose ownerReference has been stripped.
apps_tsv() {
  try_get "list of Applications cluster-wide" get "$APPS" -A -o jsonpath='{range .items[*]}{.spec.project}{"\t"}{.metadata.namespace}/{.metadata.name}{"\t"}{.metadata.ownerReferences[?(@.kind=="ApplicationSet")].name}{"\t"}{.metadata.labels.argocd\.argoproj\.io/application-set-name}{"\n"}{end}'
}

echo "BLAST RADIUS: $KIND/${NS:+$NS/}$NAME"
echo

case "$KIND" in

  ArgoCD)
    [[ -z "$NS" ]] && { echo "  (namespace required for ArgoCD)" >&2; exit 2; }
    exists argocd "$NAME" -n "$NS"; rc=$?
    [[ $rc -eq 1 ]] && { absent_note "ArgoCD CR" "$NAME" "$NS"; exit 0; }
    [[ $rc -eq 2 ]] && exit 4
    # An ArgoCD CR governs Applications in its own namespace plus any sourceNamespaces.
    watched="$NS $($KCTL get argocd "$NAME" -n "$NS" -o jsonpath='{range .spec.sourceNamespaces[*]}{@}{" "}{end}' 2>/dev/null)"
    n_app=0
    for w in $watched; do
      c=$(apps_tsv | awk -F'\t' -v ns="$w/" '$2 ~ "^"ns' | wc -l | tr -d ' ')
      [[ "$c" -gt 0 ]] && echo "  Applications in $w: $c"
      n_app=$((n_app + c))
    done
    n_set=$($KCTL get "$APPSETS" -n "$NS" --no-headers 2>/dev/null | wc -l | tr -d ' ')
    echo "  Applications governed : $n_app"
    echo "  ApplicationSets       : $n_set"
    echo
    echo "  Editing this CR makes the operator RESTART the component(s) you changed."
    echo "  Those $n_app Application(s) stop reconciling until the component is back."
    owner=$($KCTL get argocd "$NAME" -n "$NS" -o jsonpath='{.metadata.ownerReferences[0].kind}/{.metadata.ownerReferences[0].name}' 2>/dev/null)
    [[ -n "$owner" && "$owner" != "/" ]] && \
      echo "  Owned by $owner — manual edits here may be reconciled away; change the owner instead."
    ;;

  AppProject)
    [[ -z "$NS" ]] && { echo "  (namespace required for AppProject)" >&2; exit 2; }
    exists appprojects.argoproj.io "$NAME" -n "$NS"; rc=$?
    [[ $rc -eq 1 ]] && { absent_note "AppProject" "$NAME" "$NS"; exit 0; }
    [[ $rc -eq 2 ]] && exit 4
    tsv="$(apps_tsv)"
    # Scope to this AppProject's own instance. A project name is only unique within
    # an Argo CD instance: two instances can both define `default`, and matching on
    # name alone silently merges their Applications into one impact figure.
    members=$(printf '%s' "$tsv" | awk -F'\t' -v p="$NAME" -v ns="$NS/" '$1==p && $2 ~ "^"ns {print "    "$2}')
    cnt=$(printf '%s\n' "$members" | grep -c . || true)
    elsewhere=$(printf '%s' "$tsv" | awk -F'\t' -v p="$NAME" -v ns="$NS/" '$1==p && $2 !~ "^"ns {print "    "$2}')
    ecnt=$(printf '%s\n' "$elsewhere" | grep -c . || true)
    if unknown_seen; then
      echo "  Applications in this project: UNKNOWN (the lookup failed above)"
    else
      echo "  Applications in this project: $cnt"
      [[ "$cnt" -gt 0 ]] && printf '%s\n' "$members"
    fi
    if [[ "$ecnt" -gt 0 ]]; then
      echo
      echo "  NOTE: $ecnt other Application(s) name a project '$NAME' in a different"
      echo "  namespace. Project names are unique per instance, so these are probably a"
      echo "  DIFFERENT AppProject and are not counted above — confirm before assuming"
      echo "  they are unaffected:"
      printf '%s\n' "$elsewhere"
    fi
    echo
    echo "  Tightening sourceRepos, destinations or the resource whitelists can push these"
    echo "  Applications to InvalidSpecError. They stop syncing with nobody editing them."
    ;;

  ApplicationSet)
    [[ -z "$NS" ]] && { echo "  (namespace required for ApplicationSet)" >&2; exit 2; }
    exists "$APPSETS" "$NAME" -n "$NS"; rc=$?
    [[ $rc -eq 1 ]] && { absent_note "ApplicationSet" "$NAME" "$NS"; exit 0; }
    [[ $rc -eq 2 ]] && exit 4
    gen=$(apps_tsv | awk -F'\t' -v s="$NAME" '$3==s || $4==s {print "    "$2}')
    cnt=$(printf '%s\n' "$gen" | grep -c . || true)
    unknown_seen && { echo "  Applications generated by it: UNKNOWN (the lookup failed above)"; cnt="?"; } \
                 || echo "  Applications generated by it: $cnt"
    [[ "$cnt" -gt 0 ]] && printf '%s\n' "$gen"
    echo
    echo "  A template edit rewrites all $cnt at once. A generator edit can prune some away,"
    echo "  which deletes their workloads unless preserveResourcesOnDeletion is set."
    ;;

  Application)
    [[ -z "$NS" ]] && { echo "  (namespace required for Application)" >&2; exit 2; }
    exists "$APPS" "$NAME" -n "$NS"; rc=$?
    [[ $rc -eq 1 ]] && { absent_note "Application" "$NAME" "$NS"; exit 0; }
    [[ $rc -eq 2 ]] && exit 4
    res=$(try_get "managed resources of $NAME" get "$APPS" "$NAME" -n "$NS" -o jsonpath='{range .status.resources[*]}    {.kind}/{.namespace}/{.name}{"\n"}{end}')
    cnt=$(printf '%s\n' "$res" | grep -c . || true)
    prune=$($KCTL get "$APPS" "$NAME" -n "$NS" -o jsonpath='{.spec.syncPolicy.automated.prune}' 2>/dev/null)
    sync=$($KCTL get "$APPS" "$NAME" -n "$NS" -o jsonpath='{.status.sync.status}' 2>/dev/null)
    if [[ "$cnt" -eq 0 ]] && ! unknown_seen; then
      # status.resources is empty both when an Application manages nothing and when
      # it has NEVER SYNCED — most often because comparison failed. Those are very
      # different impacts and the raw count cannot tell them apart.
      echo "  Managed resources: 0"
      echo "  sync status: ${sync:-<none>}"
      if [[ "$sync" != "Synced" ]]; then
        echo "  This Application has no resources recorded AND is not Synced, so the zero"
        echo "  above probably means it never deployed — not that deleting it is harmless."
      fi
    else
    echo "  Managed resources: $cnt"
    fi
    [[ "$cnt" -gt 0 ]] && printf '%s\n' "$res"
    echo
    if [[ "$prune" == "true" ]]; then
      echo "  prune: true — DELETING this Application deletes all $cnt resource(s) above."
    else
      echo "  prune is not enabled; deleting the Application orphans the $cnt resource(s)"
      echo "  rather than removing them."
    fi
    ;;

  RolloutManager)
    if [[ -n "$NS" ]]; then
      exists rolloutmanagers.argoproj.io "$NAME" -n "$NS"; rc=$?
      [[ $rc -eq 1 ]] && { absent_note "RolloutManager" "$NAME" "$NS"; exit 0; }
      [[ $rc -eq 2 ]] && exit 4
    fi
    cnt=$(try_get "cluster-wide Rollout list" get rollouts.argoproj.io -A --no-headers | grep -c . || true)
    scoped=$($KCTL get rolloutmanager "$NAME" ${NS:+-n "$NS"} -o jsonpath='{.spec.namespaceScoped}' 2>/dev/null)
    echo "  Rollouts on the cluster: $cnt"
    echo "  namespaceScoped: ${scoped:-false (default) — controller watches ALL namespaces}"
    echo
    echo "  Changing this restarts the rollouts controller; in-flight Rollouts pause until"
    echo "  it is back. Flipping namespaceScoped silently STOPS watching Rollouts outside"
    echo "  its namespace — they sit untouched with no error anywhere."
    ;;

  ConfigMap)
    echo "  Instance-wide: argocd-cm, argocd-rbac-cm and argocd-cmd-params-cm apply to every"
    echo "  Application on the instance."
    [[ -n "$NS" ]] && echo "  Applications in $NS: $(apps_tsv | awk -F'\t' -v ns="$NS/" '$2 ~ "^"ns' | wc -l | tr -d ' ')"
    echo
    echo "  These are operator-managed on OpenShift GitOps — direct edits are reverted."
    echo "  An argocd-rbac-cm change can lock users out, including whoever makes it."
    ;;

  *)
    echo "  No fan-out rule for kind '$KIND'. State the impact from first principles and say"
    echo "  it was not computed. Known kinds: ArgoCD, AppProject, ApplicationSet, Application,"
    echo "  RolloutManager, ConfigMap."
    ;;
esac

echo
if unknown_seen; then
  echo "  (read-only; nothing was modified — but one or more lookups FAILED above."
  echo "   The numbers here are incomplete. Do not report this as a computed impact.)"
  exit 4
fi
echo "  (read-only; nothing was modified)"
