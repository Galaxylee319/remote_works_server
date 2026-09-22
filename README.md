# Remote Works Server

**轻量、移动端友好的远程文件浏览与 Markdown 阅读服务** —— 把任意目录变成一个可在手机/平板上浏览、全文检索、预览并一键导出 PDF 的私人文档站。

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Ubuntu%2020.04%2B-orange)

---

## 它解决什么问题

服务器或工作站上往往已经堆了大量 Markdown 文档、实验数据、日志、PDF 和图片，但想在手机/平板上随时查阅时，通常要面对三件麻烦事：开 SSH、装同步盘、或把资料上传到第三方云。

Remote Works Server 用一个单进程、只读的 Web 服务解决它：

- **只读**：没有任何上传/删除/重命名接口，不怕误操作
- **私有**：bcrypt 登录 + 随机会话 token，数据不出本机
- **移动优先**：手机/平板浏览体验优先，支持手势与抽屉导航
- **零加工**：root_dir 指向哪，站点就是哪，不需要导入或转换

典型用途：科研实验记录与论文草稿、运维/部署文档、数据集与日志索引、团队内部知识库。

---

## 特性

### 浏览与检索
- **文件浏览**：面包屑导航、文件名搜索、最近更新、按名称/时间/大小排序
- **正文全文检索**：跨 Markdown / 文本 / 代码 / 数据文件搜索内容，返回命中片段 + 行号 + 高亮，按命中数排序；中文无需分词（扩展名白名单、按 (mtime, size) 的内存缓存）
- **目录统计**：当前目录的目录数 · 文件数 · 文件总大小
- **文件类型图标**：目录 / 报告 / PDF / 图片 / 文本 / 代码 / 数据 / 压缩包 / 网页 分别显示不同图标
- **网格视图缩略图**：图片目录可切换网格，服务端按需生成并落盘缓存（懒加载、失败回退图标、偏好存 localStorage）
- **目录导航抽屉**：从根到当前目录逐层列出子目录，当前分支高亮
- **多选打包下载**：勾选多个文件/目录打成单个 ZIP（路径校验、父子去重、上限保护；表单提交，禁用 JS 亦可用）
- **RSS 订阅**：/feed.xml 输出最近更新，支持 ?path= 限定子目录

### 阅读与导出
- **Markdown 实时渲染**：GFM、LaTeX（MathJax，支持 $$/$ 与 \[ / \( 分隔符）、Mermaid、代码高亮、TOC、脚注、任务列表
- **同目录文档导航**：页尾提供上一份/下一份与同目录文档列表，键盘 ←/→ 翻页
- **图片浏览**：查看器支持键盘 ←/→ 与手机左右滑动，相邻图片预取
- **日志实时 tail**：文本/日志预览支持自动刷新（3 秒）与滚动跟随
- **PDF 导出**：Playwright/Chromium 服务端渲染 HTML→PDF，按内容哈希缓存（文件改动自动失效）
- **在线预览**：PDF / 图片 / 文本 / CSV / 日志

### 运维与安全
- **systemd 托管**：开机自启、崩溃自动重启，unit 内含沙箱加固（ProtectSystem=strict、ProtectHome=read-only、NoNewPrivileges、PrivateTmp）
- **外部目录实时镜像**：sync_dirs 把外部目录映射进站点（符号链接，或 sync_external_dirs.py 看护进程做实时 rsync 镜像）
- **认证**：bcrypt 密码哈希、随机 48 字节会话 token（内存态）、登录失败限速（默认 5 次 / 300 秒）
- **路径安全**：所有访问经 realpath 校验，必须落在 root_dir 或显式允许的 sync_dirs 内，符号链接逃逸被拒绝
- **隐藏文件**：以 . 开头的文件在浏览/搜索中默认不可见

---

## 技术栈

| 组件 | 选型 |
|------|------|
| Web 框架 | FastAPI + uvicorn（单进程，会话存内存） |
| 模板 | Jinja2 |
| Markdown | markdown-it-py + mdit-py-plugins + Pygments |
| 数学公式 | MathJax 3（CDN） |
| 图表 | Mermaid 10（CDN） |
| PDF | Playwright + Chromium（HTML→PDF） |
| 缩略图 | Pillow |
| 认证 | bcrypt + secrets 随机 token |
| 文件监听 | watchdog |
| 部署 | systemd（Ubuntu 20.04 验证） |

---

## 快速开始

```bash
git clone https://github.com/Galaxylee319/remote_works_server.git
cd remote_works_server

cp config.yaml.example config.yaml     # 至少改 root_dir 指向你要浏览的目录
./install.sh                           # 建 venv + 装依赖 + 装 Playwright Chromium + 设置登录密码
./rws.sh start                         # 启动（前台调试可直接 ./start.sh）
./rws.sh test                          # 健康检查
```

启动后浏览器访问 http://<主机IP>:8088 ，用安装时设置的密码登录。

> install.sh 需要 sudo 权限（apt 安装 python3-venv / chromium 相关库）。

---

## 部署为 systemd 服务

```bash
sudo cp remote-works-server.service /etc/systemd/system/
# 若用户名/路径与 unit 默认值不同，先改写（在仓库目录内执行）
sudo sed -i "s|/home/galaxybot/remote_works_server|$PWD|g; s|User=galaxybot|User=$USER|; s|Group=galaxybot|Group=$USER|" \
  /etc/systemd/system/remote-works-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now remote-works-server
systemctl status remote-works-server --no-pager
```

注意 unit 里的 **ReadWritePaths** 必须包含内容目录（root_dir）与缓存目录，否则沙箱防护会导致读取失败。

部署到新机器的完整清单（内容目录准备、外部目录镜像服务、离线部署、HTTPS 反代建议）见 **[DEPLOY.md](DEPLOY.md)**。

---

## 配置（config.yaml）

配置模板见 [config.yaml.example](config.yaml.example)，复制为 config.yaml 后按需修改。config.yaml 含密码哈希与本机路径，**不入版本控制**（已加入 .gitignore）。

| 键 | 说明 | 默认 |
|------|------|------|
| root_dir | 服务根目录（站点内容） | ~/remote_works |
| cache_dir | PDF / 缩略图 / 临时缓存 | ~/.cache/remote_works_server |
| host / port | 监听地址与端口 | 0.0.0.0 / 8088 |
| auth.enabled | 是否启用登录 | true |
| auth.username / auth.password_hash | 登录用户名与 bcrypt 哈希（由 install.sh 写入） | — |
| auth.session_ttl_days | 会话有效期（天） | 30 |
| auth.cookie_secure | HTTPS 部署时设为 true | false |
| auth.max_login_attempts / login_lockout_seconds | 登录失败阈值 / 锁定时长 | 5 / 300 |
| markdown.math / mermaid / toc / highlight | 渲染开关 | 全开 |
| pdf.enabled / engine / cache / page_format | PDF 导出设置 | true / playwright / true / A4 |
| search.exclude_dirs | 搜索与最近更新跳过的目录 | data, typeI_logs, .git |
| search.content_search | 正文全文检索总开关 | true |
| search.max_files / content_max_files / content_max_file_mb | 索引上限 / 命中文件数 / 单文件读取上限 | 50000 / 60 / 2 |
| zip.max_files / max_bytes | 打包下载上限 | 5000 / 2 GiB |
| sync_dirs | 外部目录实时镜像映射（显示名 → 绝对路径） | 空 |

---

## 常用命令

```bash
./rws.sh start|stop|restart|status    # 服务管理（systemd）
./rws.sh enable|disable               # 开机自启开关
./rws.sh logs [N]                     # 查看日志
./rws.sh set-password                 # 修改登录密码（所有会话立即失效）
./rws.sh test                         # 健康检查
```

等价的 systemd 原生命令：

```bash
sudo systemctl restart remote-works-server
journalctl -u remote-works-server -f
```

清理缓存（按内容哈希命名，删除无害）：rm -rf ~/.cache/remote_works_server/pdf ~/.cache/remote_works_server/thumbs

---

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | / | 首页（根目录浏览） |
| GET | /browse/{path} | 目录浏览 / 文件视图 |
| GET | /view/{path} | 按文件类型预览 |
| GET | /md/{path} | Markdown 阅读页 |
| GET | /pdf/{path} | PDF 阅读页 |
| GET | /api/files/{path} | 内联内容（图片/PDF 等） |
| GET | /thumb/{path} | 图片缩略图（服务端生成 + 缓存） |
| GET | /download/{path} | 下载原文件 |
| GET | /api/download-zip/{path} | 目录打包下载 |
| POST | /api/download-selected | 多选打包下载 |
| GET | /search 与 /api/search | 搜索页 / 搜索 API（mode=content 走全文检索） |
| GET | /recent 与 /api/recent | 最近更新页 / API |
| GET | /feed.xml | RSS 2.0 订阅（支持 ?path=） |
| GET / POST | /api/pdf/{path} | 获取 / 生成 PDF |
| POST | /api/pdf/{path}/regenerate | 强制重新生成 PDF |
| GET | /login 与 /api/login、/api/logout | 登录 / 登出 |
| POST | /api/set-password | 修改密码 |
| GET | /api/health 与 /api/status | 健康检查 / 运行状态 |

---

## 安全模型

- 所有文件访问经 resolve_safe_path 校验：realpath 必须位于 root_dir 内，或位于 sync_dirs 明确允许的外部目录中，其他符号链接逃逸一律拒绝。
- 服务**只读**：没有上传、删除、重命名接口。
- 密码以 bcrypt 哈希保存；会话 token 随机生成且仅存内存（**重启服务后需要重新登录**，这是有意的设计）。
- 登录接口有滑动窗口限速，连续失败会临时锁定。
- 隐藏文件（. 开头）在浏览与搜索中默认不可见。
- 公网部署建议前置 Caddy/nginx 做 HTTPS，并把 auth.cookie_secure 设为 true。

---

## 目录结构

```
remote_works_server/
├── app/                      # v2 主实现（唯一运行入口）
│   ├── main.py               # FastAPI 路由
│   ├── config.py             # 配置加载（顶层键为准，兼容旧 paths.*）
│   ├── auth.py               # 认证中间件 / 会话 / 限速
│   ├── file_browser.py       # 安全路径解析 / 列表 / 搜索 / 最近更新
│   ├── markdown_utils.py     # Markdown 渲染
│   ├── pdf_utils.py          # PDF 生成与缓存
│   └── templates/            # v2 页面模板
├── templates/ static/        # UI 资源与静态文件（pdf.js 等）
├── tests/                    # Playwright UI 回归 + 后端边界测试
├── config.yaml.example       # 配置模板（config.yaml 不入库）
├── install.sh / start.sh / rws.sh / rws_healthcheck.sh
├── run.py                    # 入口（systemd 与 start.sh 均指向它）
├── sync_external_dirs.py     # sync_dirs 实时镜像看护进程
├── remote-works-server.service / rws-sync.service
├── DEPLOY.md                 # 新机器部署指南
└── server.py, auth.py, ...   # v1 遗留实现（仅存档，不再运行）
```

---

## 测试

```bash
# 一键：起临时实例 → 跑全部测试 → 清理
./tests/run_all.sh

# 或单独运行（需自备免认证实例）
./venv/bin/python3 tests/test_mobile_layout.py     # 移动端布局：横向溢出 / JS 错误 / 资源失败
./venv/bin/python3 tests/test_browse_ui.py         # 列表/网格切换与缩略图
./venv/bin/python3 tests/test_navpane_ui.py        # 目录导航抽屉
./venv/bin/python3 tests/test_selected_zip_ui.py   # 多选打包（真实下载并校验 ZIP）
./tests/test_selected_zip_api.sh                   # 多选打包后端边界（穿越/空选/去重）
```

> 涉及界面的改动**必须**用真实浏览器验证。历史上出现过「列表视图下网格仍然显示」这类 curl 查不出来的样式问题，只有 Playwright 能发现。

---

## 常见问题

| 现象 | 原因与处理 |
|------|-----------|
| 网格视图缩略图全部显示为占位图标（/thumb 返回 415） | 缺 Pillow：./venv/bin/pip install Pillow（已列入 requirements.txt） |
| 导出 PDF 失败 / 一直转圈 | Playwright Chromium 未安装：./venv/bin/python3 -m playwright install chromium；或补系统库 sudo apt-get install -y libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 libasound2 |
| 重启服务后需要重新登录 | 会话仅存内存（有意的设计）；如需长期会话请调大 auth.session_ttl_days |
| 页面显示根目录为空 | config.yaml 的 root_dir 不存在或为空：mkdir -p 后放入文件 |
| 端口被占用 | 改 config.yaml 的 port，并同步调整防火墙/反代 |
| 改了 sync_dirs 不生效 | 重启镜像服务：sudo systemctl restart rws-sync |

---

## 相关文档

- [DEPLOY.md](DEPLOY.md) —— 新机器部署完整指南（含离线部署与 systemd 细节）
- [开源方案调研_2026-09-10.md](开源方案调研_2026-09-10.md) —— 同类开源项目对比（copyparty / filebrowser / Pagefind 等）与借鉴落地说明

---

## License

[MIT](LICENSE) © 2026 Galaxylee319
