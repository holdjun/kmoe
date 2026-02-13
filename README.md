# kmoe

[English](README_EN.md)

kxx.moe / kzz.moe / koz.moe 漫画站点的命令行下载工具。

## 功能

- 邮箱登录，Session 加密存储
- 搜索漫画，支持语言筛选
- 查看漫画详情和卷列表
- 下载漫画（MOBI / EPUB），支持并发下载
- 本地库管理：查看、导入、关联、更新
- 多镜像自动故障转移

## 安装

需要 Python 3.12+。

```bash
pip install kmoe
```

或从源码安装：

```bash
git clone https://github.com/holdjun/kmoe.git
cd kmoe
pip install .
```

开发模式：

```bash
pip install uv
uv sync
```

## 使用

### 登录

```bash
kmoe login -u your@email.com
kmoe status                            # 查看登录状态和配置
```

首次登录会引导配置下载目录、默认格式等参数。

### 搜索

```bash
kmoe search "龍珠"
kmoe search "SAKAMOTO" --lang jp --page 2
```

搜索结果显示每部漫画的 **Comic ID**（`ID` 列），后续操作需要用到。

### 查看详情

```bash
kmoe info 18488
```

显示漫画元数据、每卷的 Vol ID 及文件体积。

### 下载

```bash
kmoe download 18488                    # 下载全部卷
kmoe download 18488 -V 1001,1002      # 指定 Vol ID
kmoe download 18488 -f epub            # 指定格式
```

### 本地库

```bash
kmoe library                           # 查看已下载
kmoe update 18488                      # 更新漫画（下载新卷）
kmoe scan --dry-run                    # 预览导入
kmoe scan                              # 导入已有目录
kmoe link /path/to/manga 12345         # 手动关联
```

## 配置

配置文件位于 `~/.local/share/kmoe/config.toml`，登录时自动创建。

可配置项：下载目录、默认格式、首选镜像、并发数等。

## License

[MIT](LICENSE)
