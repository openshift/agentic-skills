# Pull Requests

## List PRs

```bash
# List open PRs
gh pr list

# Filter by state, author, labels, base branch
gh pr list --state=closed --author=@me --label=bug --base=main

# JSON output with specific fields
gh pr list --json number,title,state,author,createdAt --limit=20

# Search PRs
gh pr list --search "fix login in:title"
```

## View a PR

```bash
# View PR details
gh pr view 123

# View in browser
gh pr view 123 --web

# JSON output
gh pr view 123 --json title,body,state,mergeable,reviews,checks

# View PR diff
gh pr diff 123

# View PR comments
gh pr view 123 --comments
```

## Create a PR

```bash
# Interactive create
gh pr create

# With title and body
gh pr create --title "Fix login bug" --body "Resolves #456"

# Set base branch, reviewers, labels
gh pr create --base main --reviewer user1,user2 --label bug,urgent

# Draft PR
gh pr create --draft --title "WIP: new feature"

# Create from specific branch
gh pr create --head feature-branch --base main
```

## Review a PR

```bash
# Approve
gh pr review 123 --approve

# Request changes
gh pr review 123 --request-changes --body "Please fix the tests"

# Comment (without approve/reject)
gh pr review 123 --comment --body "Looks good overall, minor nit on line 42"
```

## Merge a PR

```bash
# Merge (default strategy)
gh pr merge 123

# Squash merge
gh pr merge 123 --squash

# Rebase merge
gh pr merge 123 --rebase

# Merge and delete branch
gh pr merge 123 --squash --delete-branch

# Auto-merge when checks pass
gh pr merge 123 --auto --squash
```

## Checkout a PR

```bash
# Checkout PR locally
gh pr checkout 123

# Checkout with a custom branch name
gh pr checkout 123 --branch my-review-branch
```

## PR Checks

```bash
# View check status
gh pr checks 123

# Wait for checks to complete
gh pr checks 123 --watch
```

## Comment on a PR

```bash
# Add a comment
gh pr comment 123 --body "Thanks for the fix!"

# Add a comment from editor
gh pr comment 123 --editor
```

## Close / Reopen

```bash
# Close a PR
gh pr close 123

# Close with a comment
gh pr close 123 --comment "Superseded by #456"

# Reopen a PR
gh pr reopen 123
```

## Edit a PR

```bash
# Edit title
gh pr edit 123 --title "Updated title"

# Add labels, reviewers, assignees
gh pr edit 123 --add-label bug --add-reviewer user1 --add-assignee user2

# Remove labels
gh pr edit 123 --remove-label wip
```
