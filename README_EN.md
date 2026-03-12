# kmoe

[中文](README.md)

A command-line manga downloader for kxx.moe / kzz.moe / koz.moe.

## Features

- Email login with encrypted session storage
- Search manga with language filtering
- View comic details and volume listings
- Download manga (MOBI / EPUB) with concurrent downloads
- Local library management: list, scan, update
- Automatic mirror failover

## Installation

Via Skill (AI operates on your behalf, recommended):

```bash
npx skills install hj/kmoe --skill kmoe
```

Manual install (requires Python 3.10+):

```bash
pip install kmoe
```

From source:

```bash
git clone https://github.com/holdjun/kmoe.git
cd kmoe
pip install .
```

Development setup:

```bash
pip install uv
uv sync
```

## Usage

### Login

```bash
kmoe login -u your@email.com
kmoe status                            # Check login status and config
```

First login will guide you through configuring download directory, default format, etc.

### Search

```bash
kmoe search "Dragon Ball"
kmoe search "SAKAMOTO" --lang jp --page 2
```

Search results display the **Comic ID** (`ID` column) needed for subsequent operations.

### View Details

```bash
kmoe info 18488
```

Shows comic metadata, volume IDs, and file sizes.

### Download

```bash
kmoe download 18488                    # Download all volumes
kmoe download 18488 -V 1001,1002      # Download specific volumes
kmoe download 18488 -f epub            # Specify format
```

### Local Library

```bash
kmoe library                           # List all comics (downloaded and locally scanned)
kmoe scan                              # Scan local files, maintain library.json
kmoe update 18488                      # Update comic (download new volumes)
kmoe update --all                      # Update all downloaded comics
```

`scan` runs purely offline (no network). `update` only applies to comics downloaded via kmoe.

## Configuration

Config file: `~/.config/kmoe/config.toml`, created automatically on first login.

Configurable: download directory, default format, preferred mirror, concurrency, etc.


## License

[MIT](LICENSE)
