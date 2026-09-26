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

当前公网 IP：`47.121.24.54`，统一生产与求职展示入口为 `http://47.121.24.54/`。生产 Compose 支持 Let’s Encrypt 的短期 IP 证书。默认 `TLS_ENABLED=false`，即使证书已经签发也会继续提供 HTTP；只有确认安全组已放行 TCP 443，并在服务器共享 `.env` 中设置 `TLS_ENABLED=true` 后，Nginx 才会启用 HTTPS并把HTTP重定向到HTTPS。

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
5. Vercel 在阿里云最终验收前保留为回退入口，确认迁移完成后再单独下线。Render 已退出部署方案，不再保留仓库部署配置。

## 旧 Render 部署下线

2026-09-26 核验：阿里云前端连接内部 `backend`，后端连接本机 Compose 的 `postgres` 和 `redis`；运行中的后端环境未发现 Render 服务地址。仓库删除了定义 `sparklearn-backend` 和 `sparklearn-db` 的 `render.yaml`。

**云端下线尚未完成。** Render 控制台登录受 GitHub 二次验证阻塞；已有 GitHub 凭据可以管理代码仓库，但没有应用安装管理权限，仓库也没有可单独关闭的部署 Webhook。不能据此声称旧服务已关闭、旧数据库已删除或后续邮件已停止。

在恢复账号访问前，提交信息包含 `[skip render]` 可以跳过这次提交在 Render 上的自动部署；它不关闭服务，也不阻止手动、API 或 Blueprint 配置变更触发的部署。阿里云按提交号更新，不依赖此标记。

恢复 Render 控制台访问后，按以下顺序完成：

1. 在 `sparklearn-backend` 的 Settings 中将 Auto-Deploy 设为 Off；如受 Blueprint 管理，先关闭 Auto Sync 并解除该 Blueprint 对旧资源的管理，避免同步时重新创建。
2. 删除旧 Web Service `sparklearn-backend`，重新检查服务列表确认已移除。
3. 单独核对 `sparklearn-db` 中是否有需保留的数据，完成必要备份并确认迁移后再删除数据库。
4. 核对旧 Blueprint、项目相关部署入口及资源列表，确认不再引用已下线资源。只处理本项目，不撤销其他项目的集成。

官方说明：[跳过自动部署](https://render.com/docs/deploys#skipping-an-auto-deploy)、[Blueprint 资源删除](https://render.com/docs/infrastructure-as-code#deleting-resources)。删除仓库配置不会自动删除云端资源。

## 无域名 HTTPS

2026-09-22 起可使用官方 `certbot/certbot:v5.4.0` 容器申请 IP 证书，无需在宿主机安装 Certbot。证书私有数据仍只保存在服务器 `/etc/letsencrypt`。仓库的 `sparklearn-cert-renew.timer` 每日两次检查续期，由 `renew-ip-certificate.sh` 在宿主机重载 Nginx。发布器发现证书后自动安装并启用定时器。

首次启用时先设置 `TLS_ENABLED=true`、`TLS_REDIRECT=false`，从公网验证 HTTPS 证书和登录链路后，再将 `TLS_REDIRECT=true` 开启 HTTP 跳转。Next 容器不开放公网端口；只有覆盖代理头的 Nginx 可访问它，Compose 显式启用 `TRUST_PROXY_HEADERS`。

个人 API Key 以加密形式存在 `model_preferences`，生产应配置独立的 `MODEL_KEY_ENCRYPTION_SECRET`（至少32个随机字符）；未配置时本地兼容模式使用 `AUTH_SECRET` 派生。备份数据库时须保留对应加密密钥；换掉加密密钥后个人 API Key 须重新填写。独立配置可避免轮换登录密钥影响模型设置。接口不返回密钥或密文，日志不能记录设置请求体。

Let’s Encrypt IP 证书有效期约 6 天，因此必须自动续期，并确保安全组同时放行 TCP 80 与 TCP 443。首次通过容器签发：

```bash
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /opt/sparklearn/shared/letsencrypt-webroot:/var/www/certbot \
  certbot/certbot:v5.4.0 certonly --no-directory-hooks \
  --preferred-profile shortlived \
  --webroot \
  --webroot-path /var/www/certbot \
  --ip-address 47.121.24.54
```

证书签发且安全组已放行 TCP 443 后，在 `/opt/sparklearn/shared/.env` 中设置 `TLS_ENABLED=true`，再重建 Nginx：

```bash
cd /opt/sparklearn/current
IMAGE_TAG="$(cat /opt/sparklearn/shared/deployed_commit)" docker compose --env-file /opt/sparklearn/shared/.env -f docker-compose.prod.yml up -d --no-deps --force-recreate nginx
```

当前容器续期禁用目录 hook，由宿主机 `renew-ip-certificate.sh` 检查配置后重载 Nginx。保留的 `certbot-renew-hook.sh` 仅兼容旧宿主机安装。`TLS_ENABLED` 与 `TLS_REDIRECT` 两阶段开关避免 443 尚未验证时跳转到不可达入口。
