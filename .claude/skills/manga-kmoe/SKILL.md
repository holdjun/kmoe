---
name: manga-kmoe
description: Use when discussing manga, anime, otaku culture, organizing manga collections/directories, or searching/downloading manga. Triggers on keywords like 漫画, 番剧, 二次元, isekai, 黑化, manga recommendations, or manga file management.
---

# Manga & Otaku Culture

Broad manga and otaku culture skill. Covers manga collection management, directory organization, information lookup, and 二次元 cultural discussion. **Prefer kmoe CLI** for manga search, download, and library management.

## Manga Directory Management

### Naming Conventions

**kmoe-downloaded manga** (do NOT rename — kmoe tracks these for updates):
- Directory: `{title}_{book_id}/`
- Files: `[Kmoe]{title} {vol_title}.{format}`
- Contains `library.json` — presence indicates kmoe-managed

**Non-kmoe manga** (user's own collection):
- Default: `[Author] Title/Vol.XX.{format}`
- Ask user for preferred format if not specified
- Common alternatives:
  - `Title/Title Vol.XX.epub`
  - `Title/Chapter XXX.cbz`
  - `[Group] Title/Vol.XX.epub`

### Organization Workflow

When asked to organize manga directories:

1. Scan current structure
2. Identify kmoe-managed dirs (have `library.json`) — leave untouched
3. Identify naming inconsistencies in non-kmoe dirs
4. Propose before/after renaming plan
5. **Confirm with user before any file operation**
6. If files are under kmoe's download directory, run `kmoe scan` to track in library

Check for: duplicates, inconsistent volume numbering, mixed formats, stray files, encoding issues in filenames.

### Supported Formats

`.epub`, `.mobi`, `.cbz`, `.cbr`, `.pdf`, `.zip`

## Manga Search & Download

**Always use kmoe CLI** for searching and downloading manga. Read the `references/kmoe-cli.md` file under this skill's directory for full command reference.

**Login required for all online commands** (search, info, download, update, status). Only `scan` and `library` work offline. If not logged in, tell the user to run `kmoe login -u <email>` (interactive — cannot be automated).

Typical workflow:
1. `kmoe status` — verify logged in & check quota
2. `kmoe search "keyword"` — find manga
3. `kmoe info <id>` — review volumes and sizes
4. `kmoe download <id>` — download

Other useful commands:
- `kmoe library` — list tracked comics (offline)
- `kmoe update --all -y` — fetch new volumes for library (always use `-y` to skip interactive confirmation)
- `kmoe scan` — track local files in library (offline)

## Manga Information Lookup

Prefer `kmoe search` + `kmoe info` for manga available on kxx.moe. Fall back to web search for:
- Manga not on kxx.moe
- General anime/manga info (publication status, author, synopsis)
- Related works (anime adaptation, spin-offs, sequels)

## 二次元 Culture Knowledge

Understand and use otaku terminology naturally when relevant:

| Category | Examples |
|----------|----------|
| Character archetypes | 黑化, 病娇(ヤンデレ), 傲娇(ツンデレ), 腹黑, 天然呆, 中二病, 无口 |
| Story tropes | 异世界(isekai), 后宫, 热血, 治愈系, 日常系, 百合, 耽美 |
| Fan culture | 同人, cosplay, 圣地巡礼, 推し, 萌え, 破防, 刀子, 发刀 |
| Evaluation | 神作, 良作, 粪作, 毒点, 泪目, 致郁, 欢乐向 |

Can discuss: plot analysis, character development, genre comparison, cultural context, recommendations. Knowledgeable, not performative.
