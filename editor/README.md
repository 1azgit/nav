# OmniNav NAS 编辑器

该服务在 NAS 上提供可视化编辑器，并把 `config.json` 发布到固定的 Tailscale SSH 目标。“常用”是配置中的 `favorites` 普通分组，可直接拖拽服务调整顺序。

1. 先在项目根目录执行 `python migrate_config.py` 生成 `config.json`。
2. 复制 `.env.example` 为 `.env`，填写远端 Tailscale 主机、SSH 用户、认证方式和目标 JSON 路径。
3. 在 `editor/` 目录运行 `docker compose up -d --build`。
4. 通过 NAS/Tailscale 地址打开 `http://NAS地址:8080/`。

认证支持私钥或密码：私钥模式填写 `REMOTE_KEY_PATH_HOST` 并留空 `REMOTE_PASSWORD`；密码模式填写 `REMOTE_PASSWORD`，将 `REMOTE_KEY_PATH_HOST` 设为 `/dev/null`。容器仍会严格校验 `known_hosts`，远端主机必须已登记。密码只存在于容器环境变量中，不会由浏览器提交或写入配置文件。发布使用临时文件上传后原子 `mv`，不会创建备份。

图标更新脚本位于项目根目录，与 `config.json` 同目录。运行 `python fetch_icons.py` 会获取服务页面图标并原子更新 `config.json` 的 `icon_path` 字段。

保存文件权限：编辑器会将新生成的 `config.json` 设置为 `0664`，便于 NAS 用户读取和覆盖。升级前如果旧文件仍是 `0600`，在 NAS 上执行一次：

```bash
chmod 664 /root/docker/nav/config.json
```
