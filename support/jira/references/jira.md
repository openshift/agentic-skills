# Jira (issues.redhat.com)

View, search, create, update, and manage Jira issues via the REST API v2.

> **Auth:** Always set the token from the OS secret store before any curl call:

## Base URL

```
https://issues.redhat.com/rest/api/2
```

## View Issue

```bash
# Basic issue details
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/issue/{issueKey}?fields=summary,status,assignee,priority,issuetype,description,created,updated,components,labels,fixVersions,versions,reporter,resolution,resolutiondate,duedate" \
  | python3 -m json.tool

# With field name mappings (discover custom field names)
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/issue/{issueKey}?expand=names" \
  | python3 -m json.tool

# With changelog (issue history)
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/issue/{issueKey}?expand=changelog" \
  | python3 -m json.tool

# Rendered fields (description/comments as HTML)
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/issue/{issueKey}?expand=renderedFields&fields=description,comment" \
  | python3 -m json.tool
```

## Epic Children

**Use `"Epic Link"` in JQL** — the `parentEpic` function does NOT work on this instance.

```bash
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/search?jql=%22Epic+Link%22%3D{epicKey}&fields=summary,status,assignee,issuetype,priority&maxResults=50" \
  | python3 -m json.tool
```

## Comments

```bash
# List comments
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/issue/{issueKey}/comment" \
  | python3 -m json.tool

# List comments with pagination
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/issue/{issueKey}/comment?startAt=0&maxResults=10" \
  | python3 -m json.tool

# Add a comment (ALWAYS confirm with user first)
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "https://issues.redhat.com/rest/api/2/issue/{issueKey}/comment" \
  -d '{"body": "Comment text here"}' \
  | python3 -m json.tool
```

## Transitions (Workflow)

```bash
# List available transitions
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/issue/{issueKey}/transitions" \
  | python3 -m json.tool

# Perform a transition (ALWAYS confirm with user first)
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "https://issues.redhat.com/rest/api/2/issue/{issueKey}/transitions" \
  -d '{"transition": {"id": "TRANSITION_ID"}}' \
  | python3 -m json.tool
```

Note: Some issues (especially Bugzilla-synced bugs) may return empty transitions if the workflow is managed externally.

## Update Issue

```bash
# Update fields (ALWAYS confirm with user first)
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X PUT "https://issues.redhat.com/rest/api/2/issue/{issueKey}" \
  -d '{
    "fields": {
      "summary": "Updated summary",
      "description": "Updated description",
      "assignee": {"name": "username@redhat.com"},
      "priority": {"name": "Major"},
      "labels": ["label1", "label2"]
    }
  }'

# Update a single field
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X PUT "https://issues.redhat.com/rest/api/2/issue/{issueKey}" \
  -d '{"fields": {"assignee": {"name": "username@redhat.com"}}}'
```

## Create Issue

```bash
# Create a new issue (ALWAYS confirm with user first)
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "https://issues.redhat.com/rest/api/2/issue" \
  -d '{
    "fields": {
      "project": {"key": "OCPNODE"},
      "issuetype": {"name": "Story"},
      "summary": "Issue summary",
      "description": "Detailed description",
      "assignee": {"name": "username@redhat.com"},
      "priority": {"name": "Major"},
      "customfield_12311140": "EPIC-KEY"
    }
  }' | python3 -m json.tool
```

Common issue types: `Epic`, `Story`, `Task`, `Bug`, `Sub-task`, `Feature`, `Spike`

## Link Issues

```bash
# Create a link between issues (ALWAYS confirm with user first)
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "https://issues.redhat.com/rest/api/2/issueLink" \
  -d '{
    "type": {"name": "Blocks"},
    "inwardIssue": {"key": "OCPNODE-100"},
    "outwardIssue": {"key": "OCPNODE-200"}
  }'
```

Common link types: `Blocks`, `Cloners`, `Duplicate`, `Relates`

## Watchers

```bash
# Get watchers
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/issue/{issueKey}/watchers" \
  | python3 -m json.tool

# Add yourself as a watcher
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "https://issues.redhat.com/rest/api/2/issue/{issueKey}/watchers" \
  -d '"username@redhat.com"'
```

## User Search

Resolve a display name to a Jira username (for use in `assignee =` JQL clauses):

```bash
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/user/search?username=First+Last" \
  | python3 -c "
import sys, json
for u in json.load(sys.stdin):
    print(f'{u[\"displayName\"]:<30} {u[\"name\"]}')"
```

The `name` field is the Jira username. Use it in JQL: `assignee = "username"`.

## JQL Search

```bash
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/search?jql=<URL-ENCODED-JQL>&fields=summary,status,assignee,priority,issuetype&maxResults=20" \
  | python3 -m json.tool
```

**Tip:** URL-encode JQL queries. Use `+` for spaces, `%3D` for `=`, `%27` for `'`, `%22` for `"`.

### JQL Operators

| Operator | Example |
|---|---|
| `=` | `status = "In Progress"` |
| `!=` | `status != Done` |
| `IN` | `status IN ("To Do", "In Progress")` |
| `NOT IN` | `priority NOT IN (Blocker, Critical)` |
| `IS EMPTY` | `assignee IS EMPTY` |
| `IS NOT EMPTY` | `fixVersion IS NOT EMPTY` |
| `~` (contains) | `summary ~ "kubernetes"` |
| `>`, `<`, `>=`, `<=` | `created >= "2026-01-01"` |
| `WAS` | `status WAS "In Progress"` |
| `CHANGED` | `status CHANGED FROM "To Do" TO "In Progress"` |

### Common Queries

```bash
# My open epics
jql: assignee = "harpatil@redhat.com" AND type = Epic AND resolution = Unresolved ORDER BY priority DESC

# Children of an epic
jql: "Epic Link" = OCPNODE-4151

# Critical bugs updated recently
jql: project = OCPBUGS AND type = Bug AND priority IN (Blocker, Critical) AND updated >= -7d ORDER BY priority DESC

# Text search
jql: project = OCPNODE AND text ~ "TLS profile"

# By component
jql: project = OCPBUGS AND component = "Management Console"

# By fix version
jql: project = OCPNODE AND fixVersion = "4.22"

# Created this week
jql: project = OCPNODE AND created >= startOfWeek()

# Unresolved in current sprint
jql: sprint in openSprints() AND project = OCPNODE AND resolution = Unresolved
```

### Pagination

```bash
# First page
"https://issues.redhat.com/rest/api/2/search?jql=...&startAt=0&maxResults=20&fields=summary,status"

# Next page
"https://issues.redhat.com/rest/api/2/search?jql=...&startAt=20&maxResults=20&fields=summary,status"
```

### Tabular Output

```bash
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/search?jql=project%3DOCPNODE+AND+type%3DEpic&maxResults=10&fields=summary,status,assignee,priority" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'Total: {data[\"total\"]} issues')
print(f'{\"Key\":<20} {\"Status\":<15} {\"Assignee\":<25} {\"Summary\"}')
print('-' * 90)
for issue in data['issues']:
    f = issue['fields']
    assignee = f.get('assignee', {})
    print(f'{issue[\"key\"]:<20} {f[\"status\"][\"name\"]:<15} {(assignee or {}).get(\"displayName\", \"Unassigned\"):<25} {f[\"summary\"][:50]}')
"
```

## Field Selection

Use `fields=` to limit response size:

```bash
# Minimal
fields=summary

# Standard view
fields=summary,status,assignee,priority,issuetype,created,updated

# With custom fields
fields=summary,status,assignee,customfield_12311140,customfield_12310243
```

## Useful Custom Fields

Red Hat-specific custom fields on issues.redhat.com:

| Custom Field ID | Name | Notes |
|---|---|---|
| `customfield_12311140` | Epic Link | Set on children to link to parent epic |
| `customfield_12311141` | Epic Name | Short name for the epic |
| `customfield_12311142` | Epic Status | Epic-specific status |
| `customfield_12310940` | Sprint | Sprint association |
| `customfield_12310243` | Story Points | Estimation points |
| `customfield_12313140` | Parent Link | Parent issue link |
| `customfield_12313240` | Team | Team assignment |
| `customfield_12313941` | Target start | Planned start date |
| `customfield_12313942` | Target end | Planned end date |
| `customfield_12315948` | QA Contact | QA assignee |
| `customfield_12316142` | Severity | Bug severity |
| `customfield_12318341` | Feature Link | Link to parent feature |
| `customfield_12319940` | Target Version | Target release version |
| `customfield_12320845` | Color Status | RAG status |
| `customfield_12316840` | Bugzilla Bug | Linked Bugzilla ID |
| `customfield_12317313` | Release Note Text | Release note content |
| `customfield_12316749` | Architect | Architect contact |
| `customfield_12316752` | Product Manager | PM contact |
| `customfield_12310220` | Git Pull Request | Linked PRs |
| `customfield_12316542` | Ready | Ready for development |
| `customfield_12316543` | Blocked | Blocked flag |
| `customfield_12316544` | Blocked Reason | Reason for block |

```bash
# Discover all field names for an issue
curl -s -H "Authorization: Bearer $JIRA_API_TOKEN" \
  "https://issues.redhat.com/rest/api/2/issue/{issueKey}?expand=names" \
  | python3 -c "import sys,json; data=json.load(sys.stdin); [print(f'{k}: {v}') for k,v in sorted(data.get('names',{}).items())]"
```
