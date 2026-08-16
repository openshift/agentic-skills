# Actions & Workflows

## List Workflow Runs

```bash
# List recent runs
gh run list --limit=10

# Filter by workflow, branch, status
gh run list --workflow=ci.yml --branch=main --status=failure

# JSON output
gh run list --json databaseId,name,status,conclusion,headBranch,createdAt --limit=10
```

## View a Run

```bash
# View run details
gh run view 12345

# View in browser
gh run view 12345 --web

# View run log
gh run view 12345 --log

# View failed step logs only
gh run view 12345 --log-failed

# View specific job
gh run view 12345 --job=67890
```

## Trigger a Workflow

```bash
# Run a workflow (workflow_dispatch)
gh workflow run ci.yml

# Run with inputs
gh workflow run deploy.yml --field environment=staging --field version=v1.2.3

# Run on a specific branch
gh workflow run ci.yml --ref feature-branch
```

## List Workflows

```bash
# List all workflows
gh workflow list

# Include disabled workflows
gh workflow list --all
```

## Enable / Disable Workflows

```bash
gh workflow enable ci.yml
gh workflow disable ci.yml
```

## Rerun

```bash
# Rerun all jobs in a run
gh run rerun 12345

# Rerun only failed jobs
gh run rerun 12345 --failed
```

## Watch a Run

```bash
# Watch a run until it completes
gh run watch 12345

# Watch with exit status (useful in scripts)
gh run watch 12345 --exit-status
```

## Download Artifacts

```bash
# Download all artifacts from a run
gh run download 12345

# Download specific artifact
gh run download 12345 --name=test-results

# Download to specific directory
gh run download 12345 --dir=./artifacts
```

## Cancel a Run

```bash
gh run cancel 12345
```

## View Run in Context

```bash
# View the run associated with current commit
gh run list --commit=$(git rev-parse HEAD)

# View runs for a specific PR
gh run list --branch=feature-branch
```
