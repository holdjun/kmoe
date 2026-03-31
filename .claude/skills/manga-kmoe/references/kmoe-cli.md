# kmoe CLI Reference

CLI tool for downloading manga from kxx.moe / kzz.moe / koz.moe in EPUB or MOBI format, with local library tracking and automatic updates.

## Prerequisites

kmoe must be installed and the user must be logged in.

**Check installation and login:**

```bash
kmoe --version
kmoe status
```

If not installed: `uv pip install kmoe` (or `pip install kmoe`)

If not logged in or session expired, tell the user to run `kmoe login -u <email>` themselves — **login is interactive** (prompts for password, download directory, format preference, language, worker count). Do not attempt to automate login. The website is **https://kxx.moe** (mirrors: kzz.moe, koz.moe) — tell the user this is where they register an account if they don't have one.

## Commands

### search — Find manga

```bash
kmoe search "keyword"
kmoe search "keyword" --lang ch      # Filter: all/ch/jp/en/oth
kmoe search "keyword" --page 2       # Pagination
```

Returns a table: ID, Title, Authors, Update date, Score, Status, Language.

### info — View details

```bash
kmoe info <comic_id>
```

Shows metadata (title, authors, categories, score, description) and a volume list with MOBI/EPUB sizes.

### download — Get volumes

```bash
kmoe download <comic_id>                        # All volumes
kmoe download <comic_id> -V "vol1,vol2,vol3"    # Specific volume IDs
kmoe download <comic_id> -f epub                 # Override format (epub/mobi)
```

Files go to `{download_dir}/{title}_{book_id}/`. Already-downloaded volumes are skipped.

**Always run `kmoe status` first to check remaining quota.** Warn user if quota looks tight.

### library — List tracked comics

```bash
kmoe library
```

Shows all comics with download progress, completion status, and source (download or scan).

### update — Fetch new volumes

```bash
kmoe update <comic_id>            # One comic
kmoe update --all                  # Entire library
kmoe update --all --dry-run        # Preview only
kmoe update --all -y               # Skip confirmation
```

Only affects download-source entries — scan-only entries are skipped.

### scan — Maintain local library

```bash
kmoe scan
```

Purely local (no network). Walks the download directory and maintains `library.json`:
- **Untracked directories**: creates library.json with `source="scan"`
- **Scan-source entries**: rescans files, updates records
- **Download-source entries**: validates integrity, removes records for missing/undersized files

### status — Check account

```bash
kmoe status
```

Shows login status, remaining monthly quota, configured download directory and format.

## Common Workflows

| Task | Commands |
|------|----------|
| Find & download | `search` -> `info` -> `download` |
| Keep library current | `update --all -y` |
| Import existing collection | `scan` |
| Check quota | `status` |

## Key Details

- **Quota**: Monthly download limit. Downloads halt when exhausted.
- **Formats**: EPUB (default) or MOBI. Set globally in config or per-download with `-f`.
- **Mirrors**: Automatic failover between kxx.moe, kzz.moe, koz.moe.
- **Config**: `~/.config/kmoe/config.toml`
- **Sources**: `download` (online ID, supports update) vs `scan` (local-only).
- **All commands except `login` are non-interactive** and safe to run via shell (use `-y` with `update` to skip confirmation).
- **Login required** for all online commands (search, info, download, update, status). Only `scan` and `library` work offline.
- Add `-v` for debug logging.
