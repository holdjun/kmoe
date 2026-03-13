---
name: kmoe
description: Use when searching, downloading, or managing manga from kxx.moe/kzz.moe/koz.moe, or using the kmoe CLI.
---

# kmoe — Manga Downloader CLI

CLI tool for downloading manga from kxx.moe / kzz.moe / koz.moe in EPUB or MOBI format, with local library tracking and automatic updates.

## Prerequisites

kmoe must be installed and the user must be logged in.

**First, check if kmoe is installed:**

```bash
kmoe --version
```

If not installed, install it for the user:

```bash
pip install kmoe
```

**Then check login status:**

```bash
kmoe status
```

If not logged in or session expired, tell the user to run `kmoe login -u <email>` themselves — **login is interactive** (prompts for password, download directory, format preference, language, worker count). Do not attempt to automate login. The website is **https://kxx.moe** (mirrors: kzz.moe, koz.moe) — tell the user this is where they register an account if they don't have one.

## Commands Reference

### search — Find manga

```bash
kmoe search "keyword"
kmoe search "keyword" --lang ch      # Filter: all/ch/jp/en/oth
kmoe search "keyword" --page 2       # Pagination
```

Returns a table: ID, Title, Authors, Update date, Score, Status, Language. Note the comic ID for subsequent commands.

### info — View details

```bash
kmoe info <comic_id>
```

Shows metadata (title, authors, categories, score, description) and a volume list with MOBI/EPUB sizes. Use this to check what's available before downloading.

### download — Get volumes

```bash
kmoe download <comic_id>                        # All volumes
kmoe download <comic_id> -V "vol1,vol2,vol3"    # Specific volume IDs
kmoe download <comic_id> -f epub                 # Override format (epub/mobi)
```

Files go to `{download_dir}/{title}_{book_id}/`. Shows progress bars, transfer speed, and quota before starting. Already-downloaded volumes are skipped automatically.

**Before downloading, run `kmoe status` to check the user's remaining quota.** If quota looks tight for the requested download, warn the user before proceeding.

### library — List tracked comics

```bash
kmoe library
```

Shows all comics in the local library with download progress, completion status, and source (download or scan).

### update — Fetch new volumes

```bash
kmoe update <comic_id>            # One comic
kmoe update --all                  # Entire library
kmoe update --all --dry-run        # Preview only
kmoe update --all -y               # Skip confirmation
```

Compares local library against remote, shows what's new, and downloads missing volumes. **Only affects download-source entries** — scan-only (local) entries are skipped.

### scan — Maintain local library

```bash
kmoe scan                          # Scan all directories
```

Purely local (no network). Walks the download directory and maintains `library.json` metadata:
- **Untracked directories** (no library.json): scans files, creates library.json with `source="scan"`. No online matching or directory renaming.
- **Scan-source entries**: rescans files on disk, updates records (picks up added/removed files).
- **Download-source entries**: validates file integrity (removes records for missing or undersized files). Run `update` afterward to re-download removed volumes.

## Common Workflows

**Find and download a manga:**

1. `kmoe search "title"` — find the comic ID
2. `kmoe info <id>` — review volumes and sizes
3. `kmoe download <id>` — download

**Keep library current:**

`kmoe update --all -y`

**Import an existing collection:**

`kmoe scan` — scans local files and creates library.json (offline, no online matching)

**Check quota before a big download:**

`kmoe status` — shows remaining monthly quota

## Key Details

- **Quota**: Monthly download limit. Shown by `kmoe status` and before each download. Downloads halt automatically when exhausted.
- **Formats**: EPUB (default) or MOBI. Set globally in config or per-download with `-f`.
- **Mirrors**: Automatically fails over between kxx.moe, kzz.moe, koz.moe.
- **Config file**: `~/.config/kmoe/config.toml` — can be edited directly.
- **Two source types**: `download` (from kmoe, has online ID, supports `update`) and `scan` (local-only, no online link).
- **All commands except `login` are non-interactive** and safe to run via shell.
- Add `-v` to any command for debug logging.
