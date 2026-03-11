# kmoe — Manga Downloader CLI

## Overview

kxx.moe / kzz.moe / koz.moe 漫画站点的命令行下载工具。登录、搜索、下载（MOBI/EPUB）、本地库管理，多镜像自动故障转移。

## Core Principles

- **简洁、高效、优雅** — 代码和文档不允许重复冗余，优先复用已有函数和模式
- **善用现有工具** — 使用 MCP servers、skills、`gh` CLI 及成熟生态，不要重复造轮子
- **约定优于配置** — 遵循项目约定，不确定时查 `docs/`
- **最小公开 API** — 每个函数只做一件事，公开函数只在 CLI 或其他模块需要时导出

## Directory Structure

```
src/kmoe/
  cli.py          Typer CLI 入口
  client.py       httpx 客户端 + 镜像故障转移
  auth.py         登录 + Fernet session 加密
  parser.py       selectolax HTML 解析
  search.py       搜索
  comic.py        漫画详情 + 下载 URL
  download.py     下载管理
  library.py      本地库管理
  config.py       TOML 配置
  models.py       Pydantic 数据模型
  constants.py    URL 模板 + 常量
  exceptions.py   异常层级
  utils.py        工具函数
tests/              测试套件
docs/               技术文档、架构设计
```

## Common Commands

```bash
# Install     — uv sync
# Test        — uv run pytest
# Coverage    — uv run pytest --cov
# Lint        — uv run ruff check src/
# Format      — uv run ruff format src/
# Type check  — uv run basedpyright src/
# Pre-commit  — uv run ruff check src/ && uv run ruff format --check src/ && uv run pytest
```

## Key Rules

1. **不要直接提交到 `main`** — 所有变更走 feature branch + PR
2. **始终使用 `/submit` 提交 PR** — 不要手动 `git push` + `gh pr create`
3. **不要提交 secrets** — 无 `.env`、API keys、session 文件
4. **不要在生产代码留 debug 输出** — 提交前清理 debug 语句
5. **每个功能必须包含测试** — 只测公开接口，测试文件一对一映射源文件（`test_parser.py` ↔ `parser.py`）。测试应守护真实行为，不为覆盖率而存在
6. **不要创建新的抽象层或辅助函数**，除非被多处（3+）调用；优先内联简单逻辑（<5 行）
7. **CLI 层同步，业务层 async** — 所有命令都是同步函数调用 `asyncio.run()` 包装异步实现

## Skills

项目 skills（通过 `/skill-name` 调用）：

- **`/submit`** — 完整的 code-to-PR 工作流。处理分支管理、质量检查、自审、提交、推送、PR 创建和 CI 监控。**所有代码提交必须使用此 skill。**
- **`/setup`** — 配置 GitHub 仓库设置（分支保护、合并策略）。幂等，可安全重复执行。

## File Naming Conventions

- 下载文件：`[Kmoe][{title}]{vol_title}.{format}`
- 目录：`{sanitized_title}_{book_id}`
- 元数据：`library.json`（JSON，缩进 2 空格）
- 配置：`~/.config/kmoe/config.toml`
- Session：`~/.config/kmoe/session.enc`（Fernet 加密）

## Documentation

详细技术架构、数据模型、实现细节见 `docs/`：

- [docs/architecture.md](docs/architecture.md) — 技术栈、模块依赖、数据模型、异常层级、关键算法
