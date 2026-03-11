# Setup

Configure GitHub repository settings. Idempotent — safe to re-run.

## Steps

### 1. Detect Repository

```bash
gh repo view --json owner,name --jq '"\(.owner.login)/\(.name)"'
```

Save as `{owner}/{repo}` for subsequent API calls.

### 2. Configure Branch Protection

Protect the `main` branch. Require the `ci` status check if `.github/workflows/ci.yml` exists:

```bash
if [ -f .github/workflows/ci.yml ]; then
  gh api repos/{owner}/{repo}/branches/main/protection \
    --method PUT \
    --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["ci"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
else
  gh api repos/{owner}/{repo}/branches/main/protection \
    --method PUT \
    --input - <<'EOF'
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
fi
```

If 403: the user lacks admin permissions or needs a paid plan for private repos. Inform and skip.

### 3. Configure Merge Strategy

Set squash-merge only with auto-delete branches:

```bash
gh api repos/{owner}/{repo} \
  --method PATCH \
  --field allow_squash_merge=true \
  --field allow_merge_commit=false \
  --field allow_rebase_merge=false \
  --field delete_branch_on_merge=true \
  --field squash_merge_commit_title=PR_TITLE \
  --field squash_merge_commit_message=PR_BODY
```

If 403: inform the user and skip.

### 4. Summary

Print what was configured:

```
Setup complete:
  ✓ Repository: {owner}/{repo}
  ✓ Branch protection: main (CI required, enforce admins)
  ✓ Merge strategy: squash only, auto-delete branches

Ready to develop:
  git fetch origin main
  git checkout -b feat/my-feature origin/main
```

Adjust checkmarks to reflect which steps succeeded vs. skipped.
