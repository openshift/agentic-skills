---
name: jira
description: Interact with Red Hat Jira (issues.redhat.com) via REST API. Use when the user asks about Jira issues, shares a Jira URL, mentions issue keys like OCPBUGS-*, OCPNODE-*, or any issues.redhat.com link.
allowed-tools: Bash(curl:*)
---

# Red Hat Jira

Interact with Red Hat Jira via REST API with `curl`. Uses a Bearer token from the `JIRA_API_TOKEN` environment variable.

## Authentication

```bash
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" "<url>" | python3 -m json.tool
```

**PAT limitation**: `currentUser()` in JQL and `/rest/api/2/myself` do NOT work with PATs on Red Hat Jira. To find the token owner's username:

```bash
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/auth/1/session" | python3 -m json.tool
```

Then use the `name` field (e.g., `harpatil@redhat.com`) in JQL queries like `assignee="harpatil@redhat.com"`.

## Quick Start

```bash
# View an issue
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/issue/OCPNODE-4151?fields=summary,status,assignee,priority,issuetype,description,created,updated,components,labels,fixVersions" \
  | python3 -m json.tool

# Search with JQL
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/search?jql=assignee%3D%22harpatil%40redhat.com%22+AND+type%3DEpic+AND+status+not+in+(Closed,Done)&maxResults=10&fields=summary,status,assignee,priority" \
  | python3 -m json.tool

# Get children of an epic
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/search?jql=%22Epic+Link%22%3DOCPNODE-4151&fields=summary,status,assignee,issuetype,priority" \
  | python3 -m json.tool
```

## URL Parsing

**Jira URLs** like `https://issues.redhat.com/browse/OCPNODE-4151` — extract the issue key (`OCPNODE-4151`) from the path after `/browse/`.

## References

Detailed command references — read on demand:

|references/jira.md — Issues, JQL search, epics, comments, transitions, custom fields

## Important

- **Always include clickable Jira URLs** when displaying issues, epics, or any Jira items. Format: `https://issues.redhat.com/browse/{KEY}`.
- **Always confirm with the user before creating/updating Jira issues, adding comments, transitioning status, or any write operation.**
- Use `fields=` parameter to limit Jira response size — full issue responses are very large.
- Epic children are found via JQL `"Epic Link"=EPIC-KEY`, NOT `parentEpic`.
- All actions happen as the token owner.
