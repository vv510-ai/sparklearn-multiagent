# SparkLearn 阿里云自动部署

## 生产链路

```text
本地完成并验证改动
        ↓
commit + push origin main
        ↓
阿里云 systemd timer 每 2 分钟只读检查 GitHub main
        ↓
发现新提交后创建独立 release 并执行 Docker Compose 构建
        ↓
容器健康检查 + 本机 HTTP 检查
        ↓
成功：切换 /opt/sparklearn/current
失败：恢复上一个健康 release
```

当前公网 IP：`47.86.40.230`，统一生产与求职展示入口为 `http://47.86.40.230/`。生产 Compose 支持 Let’s Encrypt 的短期 IP 证书。默认 `TLS_ENABLED=false`，即使证书已经签发也会继续提供 HTTP；只有确认安全组已放行 TCP 443，并在服务器共享 `.env` 中设置 `TLS_ENABLED=true` 后，Nginx 才会启用 HTTPS并把HTTP重定向到HTTPS。

## 哪些内容会自动更新

- GitHub `main` 中的后端、前端、Docker、Nginx 和部署脚本会自动更新。
- `/opt/sparklearn/shared/.env` 不进入 GitHub，也不会被发布覆盖。
- PostgreSQL、Redis、生成文件和上传资料使用 Docker 持久卷，不随代码 release 删除。
- GitHub 部署密钥为仓库只读密钥，只允许服务器拉取，不能从服务器向仓库写代码。

## 服务器目录

| 路径 | 作用 |
| --- | --- |
| `/opt/sparklearn/repository` | 只读拉取 GitHub 的本地仓库 |
| `/opt/sparklearn/releases/<commit>` | 每个 Git 提交的独立代码 release |
| `/opt/sparklearn/current` | 当前健康 release 的符号链接 |
| `/opt/sparklearn/shared/.env` | 生产密钥与环境变量，仅服务器保存 |
| `/opt/sparklearn/shared/deployed_commit` | 当前已部署提交号 |
| `/root/.ssh/sparklearn_github_deploy_ed25519` | GitHub 只读部署私钥 |
| `/opt/sparklearn/shared/letsencrypt-webroot` | Let’s Encrypt HTTP-01 验证目录 |
| `/etc/letsencrypt` | 短期 IP 证书与自动续期状态 |

## 常用检查命令

```bash
# 查看两分钟定时器
systemctl status sparklearn-auto-deploy.timer
systemctl list-timers sparklearn-auto-deploy.timer

# 立即检查并部署一次
systemctl start sparklearn-auto-deploy.service

# 查看最近部署日志
journalctl -u sparklearn-auto-deploy.service -n 200 --no-pager

# 查看当前部署的 Git 提交
cat /opt/sparklearn/shared/deployed_commit

# 查看容器
docker compose --project-name sparklearn \
  --env-file /opt/sparklearn/shared/.env \
  -f /opt/sparklearn/current/docker-compose.prod.yml ps
```

## 首次安装

服务器已经准备好 `/opt/sparklearn/shared/.env` 和只读 Deploy Key 后，在仓库 release 中执行：

```bash
sudo bash deploy/install-auto-deploy.sh
```

安装脚本会复制自动部署程序和 systemd 单元、启动定时器，并立即触发第一次部署。以后不需要再次执行安装脚本；每次推送 `main` 后等待约 2 分钟即可。部署链路自身也属于仓库代码，健康发布成功后会同步刷新服务器上的脚本和 systemd 单元。

## 发布规则

1. 只部署 GitHub `main`，不部署尚未提交的本地文件。
2. 改动后先运行相关测试；测试失败不得推送生产。
3. 只提交本任务文件，不顺带提交其他工作区改动或 `.env`。
4. 推送后必须核对服务器的 `deployed_commit` 与 GitHub 提交一致，并检查公网入口及本轮真实功能。
5. Vercel / Render 在阿里云最终验收前保留为回退入口，确认迁移完成后再单独下线。

## 无域名 HTTPS

Let’s Encrypt IP 证书有效期约 6 天，因此必须依赖 Certbot 自动续期。服务器需安装 Certbot 5.4 或更高版本，并确保安全组同时放行 TCP 80 与 TCP 443。首次签发使用 webroot：

```bash
certbot certonly \
  --preferred-profile shortlived \
  --webroot \
  --webroot-path /opt/sparklearn/shared/letsencrypt-webroot \
  --ip-address 47.76.129.100
```

证书签发且安全组已放行 TCP 443 后，在 `/opt/sparklearn/shared/.env` 中设置 `TLS_ENABLED=true`，再重建 Nginx：

```bash
cd /opt/sparklearn/current
docker compose --env-file /opt/sparklearn/shared/.env -f docker-compose.prod.yml up -d --force-recreate nginx
```

仓库中的 `deploy/certbot-renew-hook.sh` 会被自动部署到 Certbot 的 deploy hook 目录，在新证书生成后重启该容器加载证书。`TLS_ENABLED` 保护开关可以防止证书签发后、443 尚未放行时误把 HTTP 流量重定向到不可达的 HTTPS。
