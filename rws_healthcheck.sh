#!/usr/bin/env bash
# Remote Works Server 健康自检
#   1) HTTP /api/health 可用性
#   2) PDF 渲染链路（Playwright + Chromium 能否真正启动并出 PDF）—— 本次事故正出自这里
#   3) sync_dirs 实时镜像服务是否存活
#   4) 根分区剩余空间
# 结果写入 ~/.local/state/rws-health.json；失败时额外写 rws-health-alert.txt
set -u
STATE_DIR="$HOME/.local/state"
STATE="$STATE_DIR/rws-health.json"
ALERT="$STATE_DIR/rws-health-alert.txt"
VENV=/home/galaxybot/remote_works_server/venv/bin/python3
mkdir -p "$STATE_DIR"
fails=()

# 1) HTTP
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8088/api/health 2>/dev/null || echo 000)
[ "$code" = "200" ] || fails+=("http_health=$code")

# 2) PDF 链路（真实调用 Chromium 生成 PDF）
if ! "$VENV" - <<'PY' >/dev/null 2>&1
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    pg = b.new_page()
    pg.set_content("<h1>healthcheck</h1>")
    pdf = pg.pdf()
    assert pdf[:4] == b"%PDF", "PDF header missing"
    b.close()
PY
then fails+=("pdf_chain_broken"); fi

# 3) 同步服务
systemctl --user is-active --quiet rws-sync.service || fails+=("rws_sync_inactive")

# 4) 磁盘
avail=$(df -Pk / | awk 'NR==2{print $4}')
[ "$avail" -lt 3145728 ] && fails+=("disk_low_$((avail/1024))MB")

now=$(date -Is)
if [ ${#fails[@]} -eq 0 ]; then
  printf '{"time":"%s","status":"ok","disk_avail_mb":%s}\n' "$now" "$((avail/1024))" > "$STATE"
  rm -f "$ALERT"
  echo "[rws-healthcheck] OK  disk_avail=$((avail/1024))MB"
else
  msg=$(IFS='; '; echo "${fails[*]}")
  printf '{"time":"%s","status":"fail","failures":"%s"}\n' "$now" "$msg" > "$STATE"
  printf 'Remote Works Server 自检失败\n时间: %s\n失败项: %s\n' "$now" "$msg" > "$ALERT"
  echo "[rws-healthcheck] FAIL: $msg"
  exit 1
fi
