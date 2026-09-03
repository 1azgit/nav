# OmniNav

轻量 NAS 服务导航页与本地配置编辑器。线上端是静态文件，配置编辑在 NAS 内网完成，保存后可通过 Tailscale SSH 原子发布到固定服务器路径。

## 功能

- 本地网络 / Tailscale 地址切换
- 服务分组、组内排序和常用服务区域
- 每组独立列数与最大显示数量，线上支持展开/收起
- 从 `icons/` 目录选择图标，缺失图标自动回退为首字母
- NAS Web 编辑器：拖拽排序、跨分组移动、服务属性编辑、草稿保存
- 通过固定 Tailscale SSH/SFTP 目标发布 `config.json`
- 发布使用临时文件和原子替换，不创建远端备份

## 项目结构

```text
index.html              线上静态导航页
config.json             当前导航配置，线上正式读取此文件
icons/                  服务图标
migrate_config.py       从旧 config.toml 生成 config.json
editor/                 NAS 编辑器和发布 API
editor/compose.yaml     Docker Compose 部署文件
editor/.env.example     远端发布环境变量模板
config.toml             旧配置，仅用于迁移或兼容留档
sync_config.sh           旧的 GitHub 拉取脚本，已不作为正式发布流程
```

## 线上静态页

将以下文件部署到任意静态 Web 服务器，同一目录必须包含 `index.html`、`config.json` 和 `icons/`：

```text
index.html
config.json
icons/
```

本地预览可以使用 Python 静态服务器：

```bash
python -m http.server 8000
```

然后打开 `http://127.0.0.1:8000/`。线上页面不会请求 Google Fonts、二维码 CDN 或其他外部资源。

## 配置格式

编辑器使用 JSON，顶层结构如下：

```json
{
  "version": 1,
  "groups": [
    {
      "id": "media",
      "name": "影视工具",
      "order": 10,
      "columns": 5,
      "max_items": null
    }
  ],
  "services": [
    {
      "id": "emby-1",
      "name": "emby",
      "group_id": "media",
      "local_ip": "10.10.10.250",
      "tailscale_ip": "100.70.38.51",
      "port": "8096",
      "pinned": true,
      "tag": "",
      "icon_path": "icons/emby.ico",
      "order": 10,
      "position": null
    }
  ]
}
```

`order` 控制显示顺序；`columns` 允许 `1-12`；`max_items` 为 `null` 时不限制显示数量；`position` 暂为未来自由定位预留。每个 `id` 必须唯一，服务的 `group_id` 必须引用现有分组。

## NAS 编辑器部署

### 1. 生成或迁移配置

首次从旧 TOML 配置迁移：

```bash
python migrate_config.py
```

脚本会生成根目录 `config.json`，当前数据应包含 31 个服务和 5 个分组。

### 2. 配置远端目标

在 `editor/` 目录复制环境变量模板：

```bash
cp .env.example .env
```

填写以下变量：

| 变量 | 说明 |
| --- | --- |
| `REMOTE_HOST` | 服务器的 Tailscale 主机名或地址 |
| `REMOTE_PORT` | SSH 端口，默认 `22` |
| `REMOTE_USER` | SSH 用户 |
| `REMOTE_CONFIG_PATH` | 远端固定 JSON 文件路径，必须以 `.json` 结尾 |
| `REMOTE_KEY_PATH_HOST` | NAS 上 SSH 私钥的绝对路径 |
| `REMOTE_KNOWN_HOSTS_HOST` | NAS 上 `known_hosts` 的绝对路径 |

SSH 用户需要拥有目标目录的写权限。远端主机必须已经写入 `known_hosts`。

### 3. 启动编辑器

在 `editor/` 目录执行：

```bash
docker compose up -d --build
```

通过 NAS 或 Tailscale 地址访问：

```text
http://NAS地址:8080/
```

编辑流程是“保存草稿”和“发布到服务器”分离。保存只更新 NAS 上的 `config.json`；发布前会再次校验，然后上传临时文件并在远端执行原子替换。前端不能提交任意远端路径。

## API

编辑器服务提供：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/config` | 读取 NAS 草稿 |
| `PUT` | `/api/config` | 校验并原子保存草稿 |
| `GET` | `/api/icons` | 列出可选图标 |
| `POST` | `/api/validate` | 只校验，不写文件 |
| `POST` | `/api/publish` | 校验并发布到固定服务器 |

编辑器默认监听 `0.0.0.0:8080`。首版不提供应用层账号，访问控制依赖 Tailscale ACL、NAS 防火墙和 Docker 网络策略。

## 测试与检查

在项目根目录运行：

```bash
python -m unittest editor.test_server
python -m py_compile migrate_config.py editor/server.py editor/test_server.py
node --check editor/static/app.js
```

## 旧发布流程

`config.toml` 和 `sync_config.sh` 仅为旧部署保留。正式流程应使用 NAS 编辑器生成并发布 `config.json`；服务器上的静态站点也必须改为读取 `config.json`。
