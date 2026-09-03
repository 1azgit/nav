#!/usr/bin/env sh
set -eu

# LEGACY: VPS 定时同步脚本（已由 NAS 编辑器的 Tailscale 发布取代）。
# 仅为旧部署保留，不应再作为 config.json 的正式发布流程。
# 默认拉取 GitHub 项目 yangzeon/nav 的 main 分支 config.toml，
# 原子替换本地导航站 config.toml。
#
# crontab 示例：每天 03:10 执行
# 10 3 * * * /path/to/nav/sync_config.sh >> /var/log/nav-config-sync.log 2>&1
#
# 可按需覆盖：
# CONFIG_URL="https://raw.githubusercontent.com/yangzeon/nav/main/config.toml"
# TARGET_CONFIG="/var/www/nav/config.toml"

CONFIG_URL="${CONFIG_URL:-https://raw.githubusercontent.com/yangzeon/nav/main/config.toml}"
TARGET_CONFIG="${TARGET_CONFIG:-$(cd "$(dirname "$0")" && pwd)/config.toml}"
TARGET_DIR="$(dirname "$TARGET_CONFIG")"
TMP_FILE="${TARGET_CONFIG}.tmp.$$"
BACKUP_FILE="${TARGET_CONFIG}.bak"

mkdir -p "$TARGET_DIR"

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$CONFIG_URL" -o "$TMP_FILE"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$TMP_FILE" "$CONFIG_URL"
else
  echo "需要安装 curl 或 wget" >&2
  exit 1
fi

if ! grep -q '^\[\[services\]\]' "$TMP_FILE"; then
  echo "下载到的文件不像 config.toml，已取消替换" >&2
  rm -f "$TMP_FILE"
  exit 1
fi

if [ -f "$TARGET_CONFIG" ]; then
  cp "$TARGET_CONFIG" "$BACKUP_FILE"
fi

mv "$TMP_FILE" "$TARGET_CONFIG"
echo "config.toml synced: $TARGET_CONFIG"
