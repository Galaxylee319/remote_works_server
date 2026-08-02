#!/usr/bin/env bash
# Remote Works Server - Management Script (system-level systemd)
# Usage: ./rws.sh {start|stop|restart|status|logs|enable|disable|set-password|test}

SERVICE="remote-works-server"

case "${1:-help}" in
  start)
    sudo systemctl start "$SERVICE"
    sleep 2
    sudo systemctl is-active --quiet "$SERVICE" && echo "✅ Running" || echo "❌ Failed"
    ;;
  stop)
    sudo systemctl stop "$SERVICE"
    echo "✅ Stopped"
    ;;
  restart)
    sudo systemctl restart "$SERVICE"
    sleep 2
    sudo systemctl is-active --quiet "$SERVICE" && echo "✅ Running" || echo "❌ Failed"
    ;;
  status)
    systemctl status "$SERVICE" --no-pager -l
    ;;
  logs)
    journalctl -u "$SERVICE" -n "${2:-50}" --no-pager
    ;;
  follow|logs-follow)
    journalctl -u "$SERVICE" -f
    ;;
  enable)
    sudo systemctl enable "$SERVICE"
    echo "✅ Service will start on boot"
    ;;
  disable)
    sudo systemctl disable "$SERVICE"
    echo "✅ Service disabled from auto-start"
    ;;
  set-password)
    read -rsp "New password (>=8 chars): " PASSWORD
    echo ""
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    "$SCRIPT_DIR/venv/bin/python3" - "$PASSWORD" <<'PYEOF'
import sys
from app.auth import hash_password, persist_password_hash
persist_password_hash(hash_password(sys.argv[1]))
print("✅ Password updated. All sessions invalidated.")
PYEOF
    ;;
  test)
    curl -s -m 5 http://127.0.0.1:8088/api/health && echo ""
    ;;
  *)
    echo "Remote Works Server Manager (v2)"
    echo ""
    echo "用法:"
    echo "  ./rws.sh start          启动服务"
    echo "  ./rws.sh stop           停止服务"
    echo "  ./rws.sh restart        重启服务"
    echo "  ./rws.sh status         查看状态"
    echo "  ./rws.sh logs [N]       查看最近 N 条日志（默认 50）"
    echo "  ./rws.sh follow         实时跟踪日志"
    echo "  ./rws.sh enable         开机自启"
    echo "  ./rws.sh disable        关闭开机自启"
    echo "  ./rws.sh set-password   修改登录密码（会使所有会话失效）"
    echo "  ./rws.sh test           健康检查"
    echo ""
    echo "配置文件:  config.yaml（改后需 restart）"
    echo "缓存目录:  ~/.cache/remote_works_server/"
    echo "服务根目录: ~/remote_works/"
    ;;
esac

