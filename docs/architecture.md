# kmoe 技术架构

> 实现细节、数据模型、关键算法。开发规则见 [CLAUDE.md](../CLAUDE.md)，产品说明见 [README.md](../README.md)。

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

## 模块依赖

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
本地库条目：`book_id`（可为空）, `title`, `meta`（可为 null）, `downloaded_volumes`, `last_checked`, `is_complete`（三态：true/false/null=未知）

### DownloadedVolume
下载记录：`vol_id`, `title`, `format`, `filename`, `downloaded_at`, `size_bytes`, `source`
- `source="download"`: 通过 kmoe 下载，rescan 时校验体积
- `source="scan"`: 本地关联，不校验体积

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
2. 登录后将 cookies 加密存储到 `~/.config/kmoe/session.enc`
3. 加载时解密并恢复到 httpx client
4. 机器标识变化时解密失败，返回 `None`

### HTML 解析

`parser.py` 使用 selectolax CSS 选择器 + 正则：

- **Comic detail**: 从 `<title>` 提取标题/作者，JS 变量提取 `bookid`/`bookstatus`
- **Volume data**: 从 `book_data.php` 响应中解析 `postMessage("volinfo=...")` 调用
- **Search results**: 解析 `disp_divinfo()` JS 调用，提取 URL/封面/标签/评分/标题等
- **User status**: 从 JS 变量和 `my.php` 页面提取额度信息

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

每个漫画目录下唯一的元数据文件，无根索引。根据来源分两种格式：

download 来源（有线上 ID 和元数据）：

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
      "size_bytes": 151703850,
      "source": "download"
    }
  ],
  "total_volumes": 15,
  "last_checked": "2026-02-13T09:34:23Z",
  "is_complete": true
}
```

scan 来源（纯本地，无线上信息）：

```json
{
  "book_id": "",
  "comic_id": "",
  "title": "夏日時光",
  "meta": null,
  "downloaded_volumes": [
    {
      "vol_id": "",
      "title": "卷 01",
      "format": "epub",
      "filename": "[Kmoe][夏日時光]卷 01.epub",
      "downloaded_at": "2026-02-12T06:41:01Z",
      "size_bytes": 151703850,
      "source": "scan"
    }
  ],
  "total_volumes": 1,
  "last_checked": "2026-02-13T09:34:23Z",
  "is_complete": null
}
```

归档内文件的 `filename` 格式为 `archive.zip/file.epub`。

### 各命令与 library.json 的关系

| 命令 | 写 library.json | 校验体积 | 联网 | 说明 |
|------|:-:|:-:|:-:|------|
| `download` | 是 | 否 | 是 | 下载成功后新增/更新记录，source=download |
| `scan` | 是（覆盖） | 仅 download 源 | **否** | 纯本地扫描磁盘文件，维护 library.json |
| `update` | 间接 | 否 | 是 | 仅 download 源，比对 library.json vs 远端 vol_ids，缺失的调 download |
| `library` | 否 | 否 | 否 | 只读，遍历子目录的 library.json 汇总展示（含 scan 和 download 来源） |

- **两种来源**：`source="download"`（通过 kmoe 下载，有线上 ID）和 `source="scan"`（本地关联，无线上信息）
- **体积校验**：scan 时仅对 `source="download"` 的卷校验（实际大小 < 已记录 size_bytes 的 80% 则移除）；`source="scan"` 的卷只检查文件是否存在
- **update 仅作用于 download 来源**：跳过 `book_id` 和 `comic_id` 均为空的条目
- **update 不做磁盘检查**：只比较 vol_id 集合差集，磁盘完整性由 scan 负责

## 测试策略

- 所有测试基于真实站点 HTML（`tests/fixtures/`）
- HTTP 请求全部 mock（respx），无网络调用
- 只测试公开 API，不测试私有函数
- 测试文件一对一映射源文件（`test_parser.py` ↔ `parser.py`）

## Lint 配置

Ruff 规则：E, W, F, I, B, C4, UP, ARG, SIM, TCH, PTH, ERA, RUF
- 行长度：100 字符
- 忽略：E501 (line length), RUF001 (中文字符), TC001

## 类型检查

basedpyright 标准模式，忽略 `platformdirs` 的可选导入错误
