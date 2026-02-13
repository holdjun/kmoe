# kmoe 开发文档

> 技术架构、实现细节、开发指南。产品使用说明见 [README.md](README.md)。

## 原则

**代码必须简洁、高效、优雅，不允许重复冗余。**

- 优先复用已有函数和模式
- 避免过度抽象和提前优化
- 每个函数只做一件事
- 公开 API 越少越好
- 测试只测公开接口

## 技术栈

| 组件 | 选择 | 用途 |
|------|------|------|
| 包管理 | uv | 依赖解析，替代 pip/venv |
| Lint/Format | ruff | Rust 实现，替代 flake8+black+isort |
| 类型检查 | basedpyright | 比 mypy 快，与 pydantic 配合好 |
| HTTP | httpx | 原生 async，连接池 |
| HTML 解析 | selectolax | C 绑定，比 bs4 快 20x |
| CLI | typer + rich | 类型提示 + 终端 UI |
| 数据验证 | pydantic v2 | Rust 核心，快速验证 |
| 加密 | cryptography | Fernet 对称加密 |
| 日志 | structlog | 结构化日志 |
| 测试 | pytest + respx | Mock httpx |

## 架构

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
```

模块依赖（精简）：

```
cli → auth, search, comic, library, download, config, client
download → comic, library, client
comic → client, parser
auth → client, parser
search → client, parser
library → models, utils
config → models, utils
client → constants, models
parser → models
```

## 数据模型

定义在 `models.py`。带 `frozen=True` 的模型不可变（`ComicMeta`, `Volume`, `SearchResult`, `UserStatus`），其余模型可变（`ComicDetail`, `LibraryEntry`, `DownloadedVolume`, `SearchResponse`）。

### ComicMeta
漫画元数据：`book_id`, `title`, `authors`, `status`, `region`, `categories`, `score`, `cover_url`, `description`

### Volume
卷信息：`vol_id`, `title`, `file_count`, `size_mobi_mb`, `size_epub_mb`

### ComicDetail
完整信息：`meta: ComicMeta`, `volumes: list[Volume]`

### SearchResult / SearchResponse
搜索结果：`comic_id`, `title`, `authors`, `score`, `status`, `language`

### LibraryEntry
本地库条目：`book_id`, `title`, `meta`, `downloaded_volumes`, `last_checked`, `is_complete`

### DownloadedVolume
下载记录：`vol_id`, `title`, `format`, `filename`, `downloaded_at`, `size_bytes`

### AppConfig (dataclass, 可变)
配置：`download_dir`, `default_format`, `preferred_mirror`, `mirror_failover`, `rate_limit_delay`, `max_retries`, `preferred_language`, `max_download_workers`

## 异常层级

所有自定义异常继承自 `KmoeError`：

```
KmoeError
  AuthError
    LoginRequiredError
    SessionExpiredError
  NetworkError
    MirrorExhaustedError (stores mirrors_tried)
    RateLimitError
  ParseError (stores url)
  DownloadError
    QuotaExhaustedError
  ComicNotFoundError (stores comic_id)
  VolumeNotFoundError (stores vol_id)
  ConfigError
```

## 关键实现

### 镜像故障转移

`KmoeClient._request_with_failover()` 逻辑：

1. 优先使用 `preferred_mirror`，失败后按顺序尝试其他镜像
2. 每个镜像重试 `max_retries` 次，指数退避（0.5s, 1s, 2s...）
3. HTTP 404/502/503/504 立即切换下一镜像（不重试）
4. 成功的非首选镜像会被提升为 `active_mirror`
5. 所有镜像耗尽后抛出 `MirrorExhaustedError`
6. 每次请求前强制等待 `rate_limit_delay` 秒

### Session 加密

`auth.py` 使用 Fernet：

1. 密钥 = `base64(SHA256(hostname + username))`
2. 登录后将 cookies 加密存储到 `~/.local/share/kmoe/session.enc`
3. 加载时解密并恢复到 httpx client
4. 机器标识变化时解密失败，返回 `None`

### HTML 解析

`parser.py` 使用 selectolax CSS 选择器：

- **Comic detail**: 直接解析 DOM 元素（`.comic-title`, `.meta-value`, `.score-num` 等）
- **Volume data**: 从 JavaScript `var volData = [...]` 中正则提取 JSON
- **Search results**: 解析 `.book-item` + `data-bookid` 属性
- **User status**: 从 JS 变量 `var uin = "xxx";` 正则提取

### 下载 URL

通过 `getdownurl.php` API 获取 CDN 签名 URL：

```
GET /getdownurl.php?b={book_id}&v={vol_id}&mobi={fmt}&vip={line}&json=1
```

- `fmt`: MOBI=1, EPUB=2
- `line`: 下载服务器编号（0=VIP线1, 1=VIP线2）

### 库目录结构

```
{download_dir}/
  {sanitized_title}_{book_id}/
    library.json                            # 唯一元数据源
    [Kmoe][{title}]{vol_title}.{format}    # 下载文件
    *.zip / *.tar                           # 归档（内含 epub/mobi）
```

文件名清理：`/\:*?"<>|` → `_`，去首尾空白/点，截断 200 字符

### library.json

每个漫画目录下唯一的元数据文件，无根索引。格式：

```json
{
  "book_id": "55387",
  "comic_id": "55387",
  "title": "夏日時光",
  "meta": { /* ComicMeta */ },
  "downloaded_volumes": [
    {
      "vol_id": "1001",
      "title": "卷 01",
      "format": "epub",
      "filename": "[Kmoe][夏日時光]卷 01.epub",
      "downloaded_at": "2026-02-12T06:41:01Z",
      "size_bytes": 151703850
    }
  ],
  "total_volumes": 15,
  "last_checked": "2026-02-13T09:34:23Z",
  "is_complete": true
}
```

归档内文件的 `filename` 格式为 `archive.zip/file.epub`。

### 各命令与 library.json 的关系

| 命令 | 写 library.json | 校验体积 | 说明 |
|------|:-:|:-:|------|
| `download` | 是 | 否 | 下载成功后新增/更新记录 |
| `scan` | 是（覆盖） | 是 | 扫描磁盘文件 + 远端详情，重建整个 library.json |
| `link` | 是（覆盖） | 是 | 同 scan，但 comic_id 手动指定 |
| `update` | 间接 | 否 | 比对 library.json vs 远端 vol_ids，缺失的调 download |
| `library` | 否 | 否 | 只读，遍历子目录的 library.json 汇总展示 |

- **体积校验**：scan/link 构建 `downloaded_volumes` 时，跳过实际大小 < 预期大小 50% 的文件
- **update 不做磁盘检查**：只比较 vol_id 集合差集，磁盘完整性由 scan 负责

## 开发

### 环境搭建

```bash
uv sync                  # 安装所有依赖
uv run pytest            # 运行测试
uv run pytest --cov      # 测试 + 覆盖率
uv run ruff check src/   # Lint
uv run ruff format src/  # Format
uv run basedpyright src/ # 类型检查
```

### 测试策略

- 所有测试基于真实站点 HTML（`tests/fixtures/`）
- HTTP 请求全部 mock（respx），无网络调用
- 只测试公开 API，不测试私有函数
- 测试文件一对一映射源文件（`test_parser.py` ↔ `parser.py`）

### Lint 配置

Ruff 规则：E, W, F, I, B, C4, UP, ARG, SIM, TCH, PTH, ERA, RUF
- 行长度：100 字符
- 忽略：E501 (line length), RUF001 (中文字符), TC001

### 类型检查

basedpyright 标准模式，忽略 `platformdirs` 的可选导入错误

## CLI 命令

所有命令都是同步函数调用 `asyncio.run()` 包装异步实现。

| 命令 | 功能 |
|------|------|
| `login` | 邮箱登录，加密保存 session |
| `status` | 查看登录状态和配置 |
| `search` | 搜索漫画 |
| `info` | 查看漫画详情 |
| `download` | 下载漫画 |
| `library` | 查看本地库 |
| `update` | 检查远端新卷并下载 |
| `scan` | 扫描所有目录，重建 library.json |
| `link` | 手动关联目录到漫画 |

## 添加新功能

1. 不要创建新的抽象层或辅助函数，除非被多处（3+）调用
2. 优先内联简单逻辑（<5 行）
3. 公开函数只在 CLI 或其他模块需要时导出
4. 测试只测试对外接口（CLI 命令或导出函数）
5. 提交前确保：`uv run ruff check src/ && uv run ruff format --check src/ && uv run pytest` 全部通过

## 文件命名约定

- 下载文件：`[kmoe][{title}]{vol_title}.{format}`
- 目录：`{sanitized_title}_{book_id}`
- 元数据：`library.json`（JSON 格式，缩进 2 空格）
- 配置：`config.toml`（带注释）
- Session：`session.enc`（Fernet 加密）
