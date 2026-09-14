#!/usr/bin/env bash
# Remote Works Server 健康自检（含自愈）
#   1) HTTP /api/health 可用性
#   2) PDF 渲染链路（Playwright + Chromium）—— 失败时**自动重装浏览器后复检**
#   3) sync_dirs 实时镜像服务是否存活
#   4) 根分区剩余空间
# 结果：写 ~/.local/state/rws-health.json（机器可读）、rws-health-alert.txt（失败告警）
#       以及 ~/remote_works/服务状态.md（服务根可见，便于在文件浏览器里直接看到）
set -u
STATE_DIR="$HOME/.local/state"
STATE="$STATE_DIR/rws-health.json"
ALERT="$STATE_DIR/rws-health-alert.txt"
VISIBLE="$HOME/remote_works/服务状态.md"
BROWSERS="$HOME/playwright-browsers"
VENV=/home/galaxybot/remote_works_server/venv/bin/python3
# 浏览器固定放在受保护路径（~/.cache 曾被磁盘清理删除，两次导致 PDF 失效）
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$BROWSERS}"
mkdir -p "$STATE_DIR"
fails=(); notes=()

# ── 1) HTTP ──────────────────────────────────────────────────────────────
http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8088/api/health 2>/dev/null || echo 000)
if [ "$http_code" = "200" ]; then http_state="ok"; else http_state="失败($http_code)"; fails+=("http_health=$http_code"); fi

# ── 2) PDF 链路（失败即尝试自愈）────────────────────────────────────────
check_pdf() {
  "$VENV" - <<'PY' >/dev/null 2>&1
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    pg = b.new_page()
    pg.set_content("<h1>healthcheck</h1>")
    assert pg.pdf()[:4] == b"%PDF"
    b.close()
PY
}
if check_pdf; then
  pdf_state="ok"
else
  notes+=("Chromium 不可用，触发自动重装")
  if timeout 900 "$VENV" -m playwright install chromium >/dev/null 2>&1 && check_pdf; then
    pdf_state="已自动修复（重装 Chromium 成功）"
    notes+=("PDF 链路已恢复")
  else
    pdf_state="失败（自动重装未成功）"
    fails+=("pdf_chain_broken")
  fi
fi

# ── 3) 同步服务 ─────────────────────────────────────────────────────────
if systemctl --user is-active --quiet rws-sync.service; then sync_state="ok"; else sync_state="未运行"; fails+=("rws_sync_inactive"); fi

# ── 4) 磁盘 ─────────────────────────────────────────────────────────────
avail=$(df -Pk / | awk 'NR==2{print $4}')
avail_mb=$((avail/1024))
if [ "$avail" -lt 3145728 ]; then disk_state="偏低(${avail_mb}MB)"; fails+=("disk_low_${avail_mb}MB"); else disk_state="ok(${avail_mb}MB 可用)"; fi

now=$(date -Is)
if [ ${#fails[@]} -eq 0 ]; then
  printf '{"time":"%s","status":"ok","http":"%s","pdf":"%s","sync":"%s","disk_avail_mb":%s}\n' \
    "$now" "$http_state" "$pdf_state" "$sync_state" "$avail_mb" > "$STATE"
  rm -f "$ALERT"; overall="✅ 正常"
else
  msg=$(IFS='; '; echo "${fails[*]}")
  printf '{"time":"%s","status":"fail","failures":"%s","pdf":"%s"}\n' "$now" "$msg" "$pdf_state" > "$STATE"
  printf 'Remote Works Server 自检失败\n时间: %s\n失败项: %s\n' "$now" "$msg" > "$ALERT"
  overall="⚠️ 异常"
fi

# ── 服务根可见状态文件（便于在文件服务器里一眼看到）──────────────────────
{
  echo "# 服务状态"
  echo
  echo "> 由 \`rws-healthcheck.timer\` 自动生成（每日 00:00 与开机 5 分钟后），请勿手动编辑。"
  echo
  echo "| 项目 | 状态 |"
  echo "|---|---|"
  echo "| **总体** | $overall |"
  echo "| 网页服务 | $http_state |"
  echo "| PDF 导出链路 | $pdf_state |"
  echo "| 目录实时同步 | $sync_state |"
  echo "| 磁盘可用 | $disk_state |"
  echo "| 检查时间 | $now |"
  if [ ${#notes[@]} -gt 0 ]; then
    echo
    echo "**自愈动作**："
    for n in "${notes[@]}"; do echo "- $n"; done
  fi
  if [ ${#fails[@]} -gt 0 ]; then
    echo
    echo "**失败项**：\`$(IFS='; '; echo "${fails[*]}")\`"
    echo
    echo "详见 \`journalctl --user -u rws-healthcheck.service\`"
  fi
} > "$VISIBLE" 2>/dev/null

if [ ${#fails[@]} -eq 0 ]; then
  echo "[rws-healthcheck] OK  http=$http_state pdf=$pdf_state sync=$sync_state disk=${avail_mb}MB"
  [ ${#notes[@]} -gt 0 ] && printf '[rws-healthcheck] 自愈: %s\n' "${notes[*]}"
else
  echo "[rws-healthcheck] FAIL: $(IFS='; '; echo "${fails[*]}")"
  exit 1
fi
