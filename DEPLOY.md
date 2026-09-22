# Remote Works Server — 部署指南（新机器）

> 目标：在另一台 Ubuntu 机器上跑起本服务（FastAPI + systemd，默认端口 8088）。
> 本文件随仓库分发，命令可直接复制执行。

---

## 0. 交付物说明

| 文件 | 用途 |
|---|---|
| `remote_works_server.bundle` | **git bundle**，含全部提交历史，可 `git clone` 还原仓库（推荐） |
| `remote_works_server_deploy_<日期>.tar.gz` | 源码快照（不含 venv/.git/config.yaml），解压即用 |
| `sha256sums.txt` | 两个包的 SHA-256 校验值 |

> 两种包任选其一即可；都含本指南与 `install.sh`。

---

## 1. 前置要求

- Ubuntu 20.04 / 22.04（本服务在 20.04 验证）
- `python3` / `python3-venv` / `python3-pip`（install.sh 会尝试 `sudo apt` 自动装）
- 磁盘 **≥ 2 GB**（venv + Playwright Chromium 约 600 MB+）
- 首次安装需要网络（装 Python 依赖与 Chromium）；离线部署见第 8 节

---

## 2. 获取代码（三选一）

### A. 从 bundle 克隆（推荐，保留提交历史）
```bash
git clone /path/to/remote_works_server.bundle remote_works_server
cd remote_works_server
git remote remove origin          # 以后要推 GitHub 再 add
```

### B. 解压源码包
```bash
tar xzf remote_works_server_deploy_<日期>.tar.gz
cd remote_works_server
```

### C. 从 GitHub 克隆
```bash
git clone <你的仓库地址> remote_works_server && cd remote_works_server
```

---

## 3. 生成配置

```bash
cp config.yaml.example config.yaml
${EDITOR:-nano} config.yaml
```

至少确认这几项：
- `root_dir`：要浏览的内容目录（默认 `~/remote_works`，**必须真实存在**，见第 6 节）
- `sync_dirs`：外部目录实时镜像，不用就保持 `{}`
- `port`：默认 8088

> `config.yaml` 含密码哈希，**不入版本库**，每台机器一份。

---

## 4. 安装（venv + 依赖 + Playwright + 登录密码）

```bash
./install.sh
```

脚本会依次：建 `venv/` → 装 `requirements.txt` → 装 Playwright Chromium（PDF 生成用）→
交互式提示输入**登录密码**（bcrypt 哈希写入 `config.yaml`）→ 建缓存目录。
需要 sudo 权限（apt 安装 python3-venv / chromium）。

---

## 5. 注册 systemd 服务

```bash
sudo cp remote-works-server.service /etc/systemd/system/
# 若新机器用户名 / 路径与 galaxybot 不同，用下面一行自动改写（在仓库目录内执行）
sudo sed -i "s|/home/galaxybot/remote_works_server|$PWD|g; s|User=galaxybot|User=$USER|; s|Group=galaxybot|Group=$USER|" /etc/systemd/system/remote-works-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now remote-works-server
systemctl status remote-works-server --no-pager
```

> 注意：unit 里的 `ReadWritePaths` 需包含 `root_dir`（内容目录）与缓存目录，否则沙箱保护会导致只读失败。
> 默认值是 `/home/galaxybot/.cache/remote_works_server`、`/home/galaxybot/remote_works_server`、`/home/galaxybot/remote_works`，路径不同请一并改。

---

## 6. 准备内容目录（服务只负责浏览，不产生内容）

```bash
mkdir -p ~/remote_works
```

把内容放进去，三种方式：
1. **git bundle**（若目标内容也是 git 仓库）：`git clone xxx.bundle ~/remote_works`
2. **rsync 从旧机器拉**（含大文件）：
   ```bash
   rsync -av --exclude 'typeI_logs' --exclude 'data' user@旧机器:~/remote_works/ ~/remote_works/
   ```
3. **大目录单独同步**：`data/`、`typeI_logs/` 未入 git（体积大），需要就单独 rsync。

---

## 7. 验证

```bash
curl -s http://127.0.0.1:8088/api/health      # 期望返回 JSON 健康信息
./rws.sh status                                # 服务状态
./rws.sh test                                  # 内置健康检查
./rws.sh logs                                  # 查看日志
```

浏览器访问 `http://<本机IP>:8088`，用第 4 步设置的密码登录。

可选：外部目录镜像服务（仅当 `sync_dirs` 非空时）
```bash
sudo cp rws-sync.service /etc/systemd/system/
sudo sed -i "s|/home/galaxybot/remote_works_server|$PWD|g" /etc/systemd/system/rws-sync.service
sudo systemctl daemon-reload && sudo systemctl enable --now rws-sync
```

---

## 8. 离线部署（无外网）

在旧机器上把 venv 一起打包，新机器解压到同路径后直接起服务：
```bash
# 旧机器
tar czf rws_venv.tar.gz -C ~ remote_works_server/venv
# 新机器（保持用户名/路径一致最省事）
tar xzf rws_venv.tar.gz -C ~
~/remote_works_server/venv/bin/python3 ~/remote_works_server/run.py
```
注意：venv 内含绝对路径，用户名或目录不同时建议改用 `./install.sh` 重建。

---

## 9. 安全须知

1. **`config.yaml` 不入库**：含 bcrypt 密码哈希；旧提交历史中仍有历史哈希，
   仓库若设为公开，请重新设置密码（install.sh 或改密接口），或先做历史重写。
2. **公网访问必须加 HTTPS**（Caddy/nginx 反代），并设 `auth.cookie_secure: true`。
3. 默认监听 `0.0.0.0:8088`，请确认防火墙/安全组策略。
4. 登录接口有 5 次失败锁定 300 秒的限速，但仍建议用强密码。
