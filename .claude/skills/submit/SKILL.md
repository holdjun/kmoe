# Submit

Complete code-to-PR workflow. Self-review, commit, push, and open a pull request.

**All code submissions MUST go through this skill. No exceptions.**

## Steps

### 1. Ensure Feature Branch

```bash
git fetch origin
```

Check if the current branch has an open PR:

```bash
gh pr view --json state --jq '.state' 2>/dev/null
```

- **Open PR exists** → stay on this branch, proceed to Step 2.
- **No open PR** (on `main`, or on a stale branch whose PR was merged/closed) → stash uncommitted changes, create a new feature branch from `origin/main`, pop the stash, and delete the old branch if applicable.

```bash
OLD_BRANCH=$(git branch --show-current)
git stash --include-untracked  # if there are uncommitted changes
git checkout -b <type>/<description> origin/main
git stash pop                  # if stashed
# delete old branch only if it wasn't main
[[ "$OLD_BRANCH" != "main" ]] && git branch -D "$OLD_BRANCH"
```

Infer `<type>/<description>` from the current changes.

### 2. Quality Checks

Run project-specific quality checks as defined in `CLAUDE.md` (lint, format, type-check, test, build).

If no project-specific checks are defined yet, skip this step.

Iterate until all checks pass. Fix issues before proceeding.

### 3. Self-Review

Review all changes thoroughly:

```bash
git diff
git diff --cached
```

**Hygiene checks** — remove:
- Leaked secrets or credentials (API keys, tokens, passwords, `.env` content)
- Debug statements (`print`, `console.log`, `debugger`, `println!`, `fmt.Println`, etc.)
- Unrelated changes that belong in a separate PR
- Files that should not be committed (`.env`, credentials, large binaries)

**Code and logic review** — verify:
- Correctness: does the code do what it's supposed to? Are edge cases handled?
- Readability: is naming clear? Is the logic easy to follow?
- No redundant or dead code introduced
- Error handling is appropriate (not swallowed, not excessive)
- No obvious performance issues (unnecessary loops, repeated computations, missing early returns)
- Changes are consistent with the existing codebase style and patterns

If issues found, fix them and re-run Step 2.

### 4. Update Documentation

Determine if docs need updating based on the changes:
- `README.md` — project overview changes
- Files under `docs/` — architecture, conventions, specs

Update docs when changes affect: dependencies, directory structure, commands, workflows, architecture, or CI configuration.

Skip for purely internal changes. If docs were updated, re-run Step 2.

### 5. Stage and Commit

Stage relevant changes and commit:

```bash
git add <specific-files>
git commit -m "<type>: <description>"
```

Rules:
- Use specific file paths, never `git add -A` or `git add .`
- Conventional commit format: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Max 72 characters, imperative mood
- If all changes are already committed, skip to Step 6

### 6. Push and Create/Update PR

Push the branch:

```bash
git push -u origin HEAD
```

If rejected (e.g., after amend or rebase):

```bash
git push --force-with-lease -u origin HEAD
```

Then check if a PR already exists (reuse result from Step 1):

- **PR exists** → push already updated it, skip to Step 7.
- **No PR** → create one:

```bash
gh pr create --title "<type>: <description>" --body "$(cat <<'EOF'
## Summary

<brief description of what and why>

## Changes

- <change 1>
- <change 2>

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor
- [ ] Documentation
- [ ] CI/Build
- [ ] Other
EOF
)"
```

### 7. Monitor CI

```bash
gh pr checks --watch
```

If CI fails:
1. Read the failure logs
2. Fix the issue locally
3. Re-run quality checks (Step 2)
4. Commit the fix (Step 5)
5. Push (Step 6)
6. Re-monitor CI
