# Repositories

## View a Repo

```bash
# View current repo
gh repo view

# View a specific repo
gh repo view owner/repo

# View in browser
gh repo view --web

# JSON output
gh repo view --json name,owner,description,defaultBranchRef,stargazerCount,forkCount
```

## Clone a Repo

```bash
# Clone by name
gh repo clone owner/repo

# Clone to specific directory
gh repo clone owner/repo ./my-dir
```

## Fork a Repo

```bash
# Fork and clone
gh repo fork owner/repo --clone

# Fork without cloning
gh repo fork owner/repo

# Fork to an organization
gh repo fork owner/repo --org my-org
```

## Create a Repo

```bash
# Create from current directory
gh repo create my-repo --source=. --push

# Create empty repo
gh repo create my-repo --public --description "My new repo"

# Create private repo
gh repo create my-repo --private

# Create from a template
gh repo create my-repo --template owner/template-repo
```

## List Repos

```bash
# List your repos
gh repo list

# List repos for an org/user
gh repo list my-org --limit=20

# Filter by language, visibility
gh repo list --language=go --visibility=public

# JSON output
gh repo list --json name,description,visibility,updatedAt --limit=10
```

## Releases

```bash
# List releases
gh release list

# View latest release
gh release view --latest

# View specific release
gh release view v1.2.3

# Create a release
gh release create v1.2.3 --title "Release v1.2.3" --notes "Changelog..."

# Create with auto-generated notes
gh release create v1.2.3 --generate-notes

# Upload assets to a release
gh release upload v1.2.3 ./build/artifact.tar.gz

# Download release assets
gh release download v1.2.3 --dir=./downloads
```

## Direct API Access

```bash
# GET request
gh api repos/{owner}/{repo}

# POST request
gh api repos/{owner}/{repo}/labels -f name=bug -f color=d73a4a

# With JQ filtering
gh api repos/{owner}/{repo}/contributors --jq '.[].login'

# Paginate results
gh api repos/{owner}/{repo}/issues --paginate --jq '.[].title'

# GraphQL query
gh api graphql -f query='{ viewer { login } }'
```

## Search

```bash
# Search repos
gh search repos "kubernetes" --language=go --sort=stars

# Search code
gh search code "func main" --repo owner/repo

# Search issues/PRs
gh search issues "bug fix" --repo owner/repo --state=open
gh search prs "feature" --author=@me
```
