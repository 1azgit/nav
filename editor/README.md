# OmniNav NAS 编辑器

该服务在 NAS 上提供可视化编辑器，并把 `config.json` 发布到固定的 Tailscale SSH 目标。

1. 先在项目根目录执行 `python migrate_config.py` 生成 `config.json`。
2. 复制 `.env.example` 为 `.env`，填写远端 Tailscale 主机、SSH 用户、私钥挂载路径和目标 JSON 路径。
3. 在 `editor/` 目录运行 `docker compose up -d --build`。
4. 通过 NAS/Tailscale 地址打开 `http://NAS地址:8080/`。

容器需要以只读方式挂载 SSH 私钥和 `known_hosts`。远端主机必须已登记；发布使用临时文件上传后原子 `mv`，不会创建备份。
