# Remote Works Server (v2)

轻量、移动端友好的远程文件浏览与 Markdown 实时渲染服务。
服务 `~/remote_works/`，登录后可在手机/平板浏览、预览、下载文件，
并一键把 Markdown 导出为 PDF。

## 功能

### 浏览与检索
- 文件浏览：面包屑、文件名搜索、最近更新、按名称/时间/大小排序
- **正文全文检索**：跨 Markdown/文本/代码/数据文件的内容搜索（扩展名白名单、`(mtime,size)` 内存缓存、
  命中片段 + 行号 + 高亮、按命中数排序；中文无需分词）→ `/search?mode=content`
- **目录统计**：当前目录的「目录数 · 文件数 · 文件总大小」
- **文件类型图标**：目录/报告/PDF/图片/文本/代码/数据/压缩包/网页/ROS 分别显示不同图标
- **网格视图**：图片目录可切换缩略图网格（`/thumb` 端点用 Pillow 生成并落盘缓存，
  懒加载、失败回退图标、localStorage 记忆偏好），列表/网格勾选状态互通
- **目录导航抽屉**：从根到当前目录逐层列出子目录，当前分支高亮（点遮罩/ESC/× 关闭）
- **多选打包下载**：勾选多个文件/目录 → 单个 ZIP（`POST /api/download-selected`，
  路径校验、父子去重、上限保护；表单提交，无 JS 亦可用）
- **RSS 订阅**：`/feed.xml`（RSS 2.0，最近更新，支持 `?path=` 限定子目录）

### 阅读
- Markdown 实时渲染：GFM、LaTeX（MathJax，支持 `$$`/`$` 与 `\[`/`\(` 分隔符）、Mermaid、代码高亮、TOC、脚注、任务列表
- **同目录文档导航**：Markdown 页底部提供上一份/下一份 + 同目录文档列表（键盘 ←/→ 翻页）
- **图片上/下一张**：查看器支持键盘 ←/→ 与手机左右滑动，相邻图片预取
- **文本/日志实时 tail**：自动刷新开关（3 秒），滚动到底自动跟随
- PDF 导出：Playwright/Chromium 服务端渲染，内容哈希缓存（文件修改后自动失效）
- PDF / 图片 / 文本 / CSV / 日志在线预览
- 站点图标（favicon）：`/favicon.ico` → `/static/favicon.svg`（此前缺失导致 404）

### 运维与安全
- 实时同步：通过 `sync_dirs` 把外部目录映射到服务根目录，可用符号链接或 `sync_external_dirs.py` 实时镜像，源目录内容变化即时可见
- 目录打包下载（ZIP，带文件数与大小上限）
- 认证：bcrypt 密码 + 随机会话 token + 登录限速
- 安全：路径穿越防护（realpath 校验）、只读服务、隐藏文件默认不可见
- 稳定性：systemd 开机自启、崩溃自动重启、沙箱加固（ProtectSystem/ProtectHome）

## 技术栈

| 组件 | 选择 |
|------|------|
| Web 框架 | FastAPI + uvicorn（单进程，会话存内存） |
| Markdown | markdown-it-py + mdit-py-plugins + Pygments |
| LaTeX | MathJax 3（CDN） |
| Mermaid | Mermaid.js 10（CDN） |
| PDF | Playwright + Chromium（HTML→PDF） |
| 认证 | bcrypt + secrets 随机 token |
| 部署 | systemd（Ubuntu 20.04 已验证） |

## 目录结构

```
remote_works_server/
├── app/                    # v2 主实现（唯一运行入口）
│   ├── main.py             # FastAPI 路由
│   ├── config.py           # 配置加载（顶层键 + 旧 paths.* 兼容）
│   ├── auth.py             # 认证中间件/会话/限速
│   ├── file_browser.py     # 安全路径解析/列表/搜索/最近更新
│   ├── markdown_utils.py   # Markdown 渲染
│   └── pdf_utils.py        # PDF 生成与缓存
├── templates/ static/      # 移动端优先 UI
├── config.yaml             # 配置
├── run.py                  # 入口（systemd 与 start.sh 均指向它）
├── sync_external_dirs.py   # 实时镜像 sync_dirs 外部目录的看护进程
├── install.sh / start.sh / rws.sh
├── remote-works-server.service
└── server.py auth.py ...   # 【旧版遗留】v1 实现，已不再运行，仅存档
```

## 快速开始

```bash
cd ~/remote_works_server
./install.sh                 # 首次安装（venv + 依赖 + Playwright Chromium + 密码）
./rws.sh start               # 前台可 ./start.sh
./rws.sh test                # 健康检查
```

浏览器访问 `http://<tailscale-ip>:8088`，登录后即可使用。

## 配置（config.yaml）

| 键 | 说明 | 默认 |
|------|------|------|
| `root_dir` | 服务根目录 | `~/remote_works` |
| `cache_dir` | PDF/临时缓存 | `~/.cache/remote_works_server` |
| `host` / `port` | 监听地址 | `0.0.0.0` / `8088` |
| `auth.enabled` | 是否启用登录 | `true` |
| `auth.session_ttl_days` | 会话有效期 | `30` |
| `auth.cookie_secure` | HTTPS 下设为 `true` | `false` |
| `auth.max_login_attempts` | 登录失败锁定阈值 | `5` |
| `auth.login_lockout_seconds` | 锁定窗口 | `300` |
| `markdown.*` | math/mermaid/toc/highlight 开关 | 全开 |
| `pdf.cache` | PDF 内容哈希缓存 | `true` |
| `search.exclude_dirs` | 搜索/最近更新跳过的目录 | `data, typeI_logs, .git` |
| `zip.max_files/max_bytes` | 目录打包上限 | 5000 文件 / 2GiB |
| `sync_dirs` | 外部目录实时同步映射（名字→绝对路径）；启动时会在 `root_dir` 下建符号链接，也可用 `sync_external_dirs.py` 做实时镜像 | 空 |

## 常用命令

```bash
./rws.sh start|stop|restart|status     # 服务管理
./rws.sh logs [N]                      # 日志
./rws.sh set-password                  # 修改密码（所有会话失效）
./rws.sh test                          # 健康检查
./sync_external_dirs.py &              # 实时镜像外部目录（可选，符号链接方案无需启动）
```

等价 systemd 命令（服务为系统级）：

```bash
sudo systemctl restart remote-works-server
journalctl -u remote-works-server -f
```

清理 PDF 缓存：`rm -rf ~/.cache/remote_works_server/pdf`（缓存按内容哈希命名，删除无害）。

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/browse/{path}` | 目录浏览 / 文件视图 |
| GET | `/view/{path}` | 按类型预览 |
| GET | `/md/{path}` | Markdown 阅读页 |
| GET | `/api/files/{path}` | 内联预览（图片/PDF） |
| GET | `/download/{path}` | 下载原文件 |
| GET | `/api/download-zip/{path}` | 目录打包下载 |
| GET | `/search?q=` `/recent` | 搜索 / 最近更新页面 |
| GET/POST | `/api/pdf/{path}` | 导出 PDF |
| POST | `/api/pdf/{path}/regenerate` | 强制重新生成 |
| POST | `/api/login` `/api/logout` `/api/set-password` | 认证 |
| GET | `/api/health` `/api/status` | 健康/状态检查 |

## 安全说明

- 所有文件访问经 `resolve_safe_path` 校验（realpath 必须位于 `root_dir` 内，或位于 `sync_dirs` 明确允许的外部目录中；其他符号链接逃逸被拒绝）。
- 服务只读，无上传/删除/重命名接口。
- 密码为 bcrypt 哈希，随机会话 token 存内存，登录有滑动窗口限速。
- 隐藏文件（`.` 开头）在浏览/搜索中默认不可见。
- systemd 加固：`ProtectSystem=strict`、`ProtectHome=read-only`、`NoNewPrivileges`、`PrivateTmp`。
- 公网部署建议在前面加 Caddy/nginx HTTPS，并把 `auth.cookie_secure` 设为 `true`。

## v2 升级说明（2026-08-02）

**修复/优化**

1. 合并两套实现：原先 systemd 运行旧 `server.py`，`app/` 是未完成的重构
   （模板缺失、固定会话 token、配置键不一致、无启动入口）。
2. 认证升级：随机 48 字节会话 token + 有效期；登录限速；改密后全部会话失效。
3. PDF 生成：单例浏览器 + asyncio 锁（修复并发重复启动）；内容哈希缓存
   （原按 mtime，缓存失效不可靠）；失败清理临时文件；明确错误提示。
4. 稳定性：统一异常处理（API 返回 JSON、页面返回错误页）；文本预览 2MB 截断；
   大目录打包上限；隐藏 `.git` 等目录；搜索/最近更新跳过 `data`、`typeI_logs`。
5. 运维：`rws.sh` 修正为系统级 systemd 命令（原为 `--user`，无法工作）；
   新增 `set-password`、`test` 子命令；systemd 增加沙箱加固。
6. 配置统一：顶层 `root_dir/cache_dir/host/port` 为准，兼容旧 `paths.*`。

**回滚**：项目已用 git 管理，升级前基线为 commit `837ac63`。
`git checkout 837ac63 -- .` 可恢复旧实现（systemd 需改回 `server.py` 入口）。

## License

MIT

## 测试

```bash
# 一键：自动起临时实例 → 跑全部测试 → 清理
./tests/run_all.sh

# 或单独运行（需自备免认证实例）
./venv/bin/python3 tests/test_mobile_layout.py      # 移动端布局：横向溢出/JS错误/资源失败
./venv/bin/python3 tests/test_browse_ui.py          # 列表/网格视图切换与缩略图
./venv/bin/python3 tests/test_navpane_ui.py         # 目录导航抽屉
./venv/bin/python3 tests/test_selected_zip_ui.py    # 多选打包（含真实下载与 ZIP 校验）
./tests/test_selected_zip_api.sh                    # 多选打包后端边界（穿越/空选/去重）
```

> 界面类改动**必须**用 Playwright 真实浏览器验证（曾出现「列表视图下网格仍显示」这类
> curl 查不出的样式问题）。

## 相关文档

- `开源方案调研_2026-09-10.md`：同类开源项目对比（copyparty/filebrowser/Pagefind 等）与借鉴落地说明
- `运维报告_2026-09-10.md`：文件服务器运维记录（故障处置、服务归一、健康自检）
