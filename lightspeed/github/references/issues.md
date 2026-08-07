# Issues

## List Issues

```bash
# List open issues
gh issue list

# Filter by state, author, labels, assignee
gh issue list --state=closed --author=@me --label=bug --assignee=@me

# JSON output with specific fields
gh issue list --json number,title,state,author,labels,createdAt --limit=20

# Search issues
gh issue list --search "memory leak in:title"
```

## View an Issue

```bash
# View issue details
gh issue view 456

# View in browser
gh issue view 456 --web

# JSON output
gh issue view 456 --json title,body,state,labels,assignees,comments

# View issue comments
gh issue view 456 --comments
```

## Create an Issue

```bash
# Interactive create
gh issue create

# With title and body
gh issue create --title "Bug: login fails" --body "Steps to reproduce..."

# With labels and assignees
gh issue create --title "Feature request" --label enhancement --assignee @me

# From a template
gh issue create --template bug_report.md
```

## Edit an Issue

```bash
# Edit title and body
gh issue edit 456 --title "Updated title" --body "Updated description"

# Add/remove labels
gh issue edit 456 --add-label priority/high --remove-label triage

# Add/remove assignees
gh issue edit 456 --add-assignee user1 --remove-assignee user2
```

## Close / Reopen

```bash
# Close an issue
gh issue close 456

# Close with a reason
gh issue close 456 --reason "not planned"

# Close with a comment
gh issue close 456 --comment "Fixed in #789"

# Reopen an issue
gh issue reopen 456
```

## Comment on an Issue

```bash
# Add a comment
gh issue comment 456 --body "Investigating this now"

# Add a comment from editor
gh issue comment 456 --editor
```

## Pin / Unpin

```bash
gh issue pin 456
gh issue unpin 456
```

## Transfer

```bash
# Transfer issue to another repo
gh issue transfer 456 owner/other-repo
```
