---
name: kmoe
description: Use when the user wants to search, download, or manage manga/comics from kxx.moe/kzz.moe/koz.moe sites. Trigger on any mention of manga downloading, comic library management, updating manga collections, checking download quota, scanning local manga files, or the kmoe CLI tool. Even if the user just says they want to read or get a specific manga title, this skill applies.
---

# kmoe — Manga Downloader CLI

CLI tool for downloading manga from kxx.moe / kzz.moe / koz.moe in EPUB or MOBI format, with local library tracking and automatic updates.

## Prerequisites

kmoe must be installed and the user must be logged in.

- Install: `pip install kmoe` or `uv tool install kmoe`
- Login: `kmoe login -u <email>` — **interactive, the user must run this themselves** (prompts for password, download directory, format preference, language, worker count)
- Check status: `kmoe status`

If the user hasn't logged in or their session expired, tell them to run `kmoe login` first. Do not attempt to automate login.

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

### library — List tracked comics

```bash
kmoe library
```

Shows all comics in the local library with download progress and completion status.

### update — Fetch new volumes

```bash
kmoe update <comic_id>            # One comic
kmoe update --all                  # Entire library
kmoe update --all --dry-run        # Preview only
kmoe update --all -y               # Skip confirmation
```

Compares local library against remote, shows what's new, and downloads missing volumes.

### scan — Import existing files

```bash
kmoe scan                          # Auto-detect all directories
kmoe scan --dry-run                # Preview without changes
```

Walks the download directory, matches local manga files to remote comic data by title, and creates `library.json` metadata. Use this to bring an existing collection under kmoe management.

### link — Manual import

```bash
kmoe link /path/to/manga <comic_id>
```

When scan can't auto-detect a comic, manually associate a directory with a comic ID.

## Common Workflows

**Find and download a manga:**

1. `kmoe search "title"` — find the comic ID
2. `kmoe info <id>` — review volumes and sizes
3. `kmoe download <id>` — download

**Keep library current:**

`kmoe update --all -y`

**Import an existing collection:**

`kmoe scan` — auto-matches titles to remote data

**Check quota before a big download:**

`kmoe status` — shows remaining monthly quota

## Key Details

- **Quota**: Monthly download limit. Shown by `kmoe status` and before each download. Downloads halt automatically when exhausted.
- **Formats**: EPUB (default) or MOBI. Set globally in config or per-download with `-f`.
- **Mirrors**: Automatically fails over between kxx.moe, kzz.moe, koz.moe.
- **Config file**: `~/.config/kmoe/config.toml` — can be edited directly.
- **All commands except `login` are non-interactive** and safe to run via shell.
- Add `-v` to any command for debug logging.
