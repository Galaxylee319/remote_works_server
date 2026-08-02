#!/usr/bin/env bash
# Remote Works Server - Management Script
# Usage: ./rws.sh {start|stop|restart|status|logs|enable|disable}

SERVICE="remote-works-server"

case "${1:-help}" in
  start)
    echo "Starting $SERVICE..."
    systemctl --user start $SERVICE
    sleep 2
    systemctl --user is-active --quiet $SERVICE && echo "✅ Running" || echo "❌ Failed"
    ;;
  stop)
    echo "Stopping $SERVICE..."
    systemctl --user stop $SERVICE
    echo "✅ Stopped"
    ;;
  restart)
    echo "Restarting $SERVICE..."
    systemctl --user restart $SERVICE
    sleep 2
    systemctl --user is-active --quiet $SERVICE && echo "✅ Running" || echo "❌ Failed"
    ;;
  status)
    systemctl --user status $SERVICE
    ;;
  logs)
    journalctl --user -u $SERVICE -n 50 --no-pager "${@:2}"
    ;;
  logs-follow|follow)
    journalctl --user -u $SERVICE -f
    ;;
  enable)
    systemctl --user enable $SERVICE
    loginctl enable-linger 2>/dev/null
    echo "✅ Service will start on boot"
    ;;
  disable)
    systemctl --user disable $SERVICE
    echo "✅ Service disabled from auto-start"
    ;;
  test-page)
    echo "Opening test page..."
    curl -s http://127.0.0.1:8088/login | head -5
    ;;
  *)
    echo "Remote Works Server Manager"
    echo ""
    echo "Usage:"
    echo "  ./rws.sh start       Start the server"
    echo "  ./rws.sh stop        Stop the server"
    echo "  ./rws.sh restart     Restart the server"
    echo "  ./rws.sh status      Show service status"
    echo "  ./rws.sh logs        Show last 50 log lines"
    echo "  ./rws.sh follow      Follow logs in real-time"
    echo "  ./rws.sh enable      Enable auto-start on boot"
    echo "  ./rws.sh disable     Disable auto-start on boot"
    echo ""
    echo "Config file:  config.yaml (edit then restart)"
    echo "Cache dir:    ~/.cache/remote_works_server/"
    echo "File root:    ~/remote_works/"
    ;;
esac
