#!/usr/bin/env bash
# 一键运行全部回归测试：自起免认证临时实例 → 跑 5 套测试 → 清理
# 用法：./tests/run_all.sh [port]
set -u
PORT="${1:-8099}"
BASE="http://127.0.0.1:$PORT"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "▶ 准备临时实例（端口 $PORT，免认证）…"
python3 - "$PORT" <<'PY'
import sys, yaml, io
port = int(sys.argv[1])
cfg = yaml.safe_load(io.open('config.yaml', encoding='utf-8'))
cfg.update(host='127.0.0.1', port=port, cache_dir='/tmp/rws_runall_cache')
cfg['auth']['enabled'] = False
cfg['pdf']['enabled'] = False
cfg['sync_dirs'] = {}
cfg.pop('paths', None)
io.open('/tmp/rws_runall.yaml', 'w', encoding='utf-8').write(
    yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
PY
mkdir -p /tmp/rws_runall_cache
RWS_CONFIG=/tmp/rws_runall.yaml nohup ./venv/bin/python3 run.py >/tmp/rws_runall.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; rm -f /tmp/rws_runall.yaml /tmp/rws_runall.log; rm -rf /tmp/rws_runall_cache' EXIT
for i in $(seq 1 20); do
  sleep 1
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$BASE/api/health" || echo 000)" = "200" ] && break
done
echo "▶ 实例就绪（PID $SRV）"
echo

fails=0
run() { echo "── $1"; shift; "$@" >/tmp/_t.log 2>&1 && echo "   ✔ 通过" || { echo "   ✘ 失败"; tail -15 /tmp/_t.log | sed 's/^/     /'; fails=$((fails+1)); }; }
run "移动端布局（12 页）"      ./venv/bin/python3 tests/test_mobile_layout.py "$BASE"
run "浏览页 网格/列表视图"      ./venv/bin/python3 tests/test_browse_ui.py "$BASE"
run "目录导航抽屉"             ./venv/bin/python3 tests/test_navpane_ui.py "$BASE"
run "多选打包（UI + 真实下载）" ./venv/bin/python3 tests/test_selected_zip_ui.py "$BASE"
run "多选打包（后端边界）"      ./tests/test_selected_zip_api.sh "$BASE"

echo
echo "════════════════════════"
if [ "$fails" -eq 0 ]; then echo "全部测试通过 ✔"; else echo "失败 $fails 套 ✘"; fi
exit "$fails"
