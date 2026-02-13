# kmoe

[中文](README.md)

A command-line manga downloader for kxx.moe / kzz.moe / koz.moe.

## Features

- Email login with encrypted session storage
- Search manga with language filtering
- View comic details and volume listings
- Download manga (MOBI / EPUB) with concurrent downloads
- Local library management: list, import, link, update
- Automatic mirror failover

## Installation

Requires Python 3.12+.

```bash
pip install kmoe
```

Or install from source:

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
kmoe library                           # List downloaded comics
kmoe update 18488                      # Update comic (download new volumes)
kmoe scan --dry-run                    # Preview import
kmoe scan                              # Import existing directories
kmoe link /path/to/manga 12345         # Manually link directory to comic
```

## Configuration

Config file: `~/.local/share/kmoe/config.toml`, created automatically on first login.

Configurable: download directory, default format, preferred mirror, concurrency, etc.

## License

[MIT](LICENSE)
