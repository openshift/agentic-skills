---
name: github
description: Interact with GitHub repositories, pull requests, issues, actions, and more using the gh CLI. Use when the user asks about GitHub repos, shares a GitHub URL, or wants to manage PRs, issues, or CI/CD workflows.
allowed-tools: Bash(gh:*) Bash(curl:*)
---

# GitHub via gh CLI

Interact with GitHub using the `gh` CLI (authenticated via `gh auth login`).

## Quick Start

```bash
# View a PR
gh pr view 123

# List open PRs in current repo
gh pr list

# View an issue
gh issue view 456

# List recent workflow runs
gh run list --limit=5

# View repo info
gh repo view

# Direct API call
gh api repos/{owner}/{repo}/pulls
```

## URL Parsing

When the user shares a GitHub URL like `https://github.com/owner/repo/pull/123`, extract the owner, repo, and number to use with `gh` commands:

```bash
# From https://github.com/openshift/kubernetes/pull/2100
gh pr view 2100 --repo openshift/kubernetes

# From https://github.com/openshift/kubernetes/issues/50
gh issue view 50 --repo openshift/kubernetes
```

Use `--repo owner/repo` when the URL refers to a different repo than the current working directory.

## References

Detailed command references — read on demand:

|references/pull-requests.md — Create, review, merge, checkout, diff, checks
|references/issues.md — Create, list, view, edit, close, comment, labels
|references/actions.md — Workflows, runs, artifacts, logs
|references/repos.md — Clone, fork, view, create, releases, collaborators

## Common Pitfalls

### Always use `--repo` for external repos

When the user shares a URL or references a repo other than the current working directory, **always** include `-R owner/repo` (or `--repo owner/repo`). Without it, `gh` defaults to the current directory's repo and will fail.

```bash
# WRONG — will fail if you're not in the cluster-version-operator checkout
gh pr view 1314

# CORRECT
gh pr view 1314 -R openshift/cluster-version-operator
```

### Avoid `!=` in jq expressions

Zsh treats `!` as history expansion, which corrupts `!=` into `\!=` inside jq filters. Use negation alternatives instead:

```bash
# WRONG — zsh will mangle != to \!=
gh api repos/o/r/pulls --jq '[.[] | select(.merged_at != null)]'

# CORRECT — use truthy check
gh api repos/o/r/pulls --jq '[.[] | select(.merged_at)]'

# CORRECT — use "not" for negation
gh api repos/o/r/pulls --jq '[.[] | select(.merged_at | not)]'
```

### OAuth-restricted organizations (curl fallback)

Some GitHub organizations (e.g., `containers`) restrict OAuth app access. When this happens, `gh` CLI commands fail with errors like:

```
Resource protected by organization SAML enforcement. You must grant your OAuth token access to this organization.
```

or:

```
Could not resolve to a PullRequest
```

**When `gh` fails on an org-restricted repo, fall back to `curl` using `gh auth token` to get the token:**

```bash
# View a PR
curl -s -H "Authorization: token $(gh auth token)" \
  https://api.github.com/repos/containers/podman/pulls/25972 | jq '{title: .title, state: .state, user: .user.login, body: .body}'

# List open PRs
curl -s -H "Authorization: token $(gh auth token)" \
  "https://api.github.com/repos/containers/podman/pulls?state=open&per_page=10" | jq '.[].title'

# View an issue
curl -s -H "Authorization: token $(gh auth token)" \
  https://api.github.com/repos/containers/podman/issues/500 | jq '{title: .title, state: .state, body: .body}'

# List PR files
curl -s -H "Authorization: token $(gh auth token)" \
  https://api.github.com/repos/containers/podman/pulls/25972/files | jq '.[].filename'

# Get PR diff
curl -s -H "Authorization: token $(gh auth token)" \
  -H "Accept: application/vnd.github.v3.diff" \
  https://api.github.com/repos/containers/podman/pulls/25972
```

Always try `gh` first and fall back to `curl` only when it fails due to org restrictions.

## Important

- **Always confirm with the user before creating PRs/issues, commenting, merging, pushing, deleting branches, or triggering workflow runs.**
- Use `--json` flag for reliable parsing of command output (e.g., `gh pr list --json number,title,state`).
- Use `--repo owner/repo` to target a repo other than the current directory.
- Use `--web` flag to open items in the browser when useful.
- All actions happen as the authenticated `gh` user.
