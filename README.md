# Remote Works Server

A lightweight, mobile-friendly web server for browsing, reading, and downloading files in `~/remote_works/`. Designed for researchers who want to remotely view experiment results, Markdown reports, and PDF documents from their phone or tablet.

## Features

- **File Browser** — browse directories, search files, sort by modification time
- **Markdown Rendering** — GitHub Flavored Markdown with LaTeX math, Mermaid diagrams, syntax highlighting, tables, and task lists
- **PDF Export** — generate PDF from any Markdown file with one click
- **PDF Preview** — view PDF files directly in the browser
- **Image Preview** — view PNG, JPG, GIF, SVG, WebP images
- **Text/Code Viewer** — view text, CSV, log, and source code files
- **Mobile-First UI** — designed for phone/tablet vertical browsing
- **Authentication** — username + bcrypt password protection
- **Auto-Start** — systemd service for boot-time startup and crash recovery

## Tech Stack

| Component | Choice | Purpose |
|-----------|--------|---------|
| Web framework | FastAPI + uvicorn | Async Python web server |
| Markdown | markdown-it-py + mdit-py-plugins | GFM rendering |
| LaTeX | MathJax 3 (CDN) | Client-side math rendering |
| Diagrams | Mermaid.js (CDN) | Client-side diagram rendering |
| Code highlight | Pygments (Monokai theme) | Syntax highlighting |
| PDF generation | Playwright (Chromium) | HTML-to-PDF printing |
| Auth | bcrypt + session cookies | Password protection |
| File watching | watchdog | Real-time file change detection |
| Deployment | systemd | Auto-start, auto-restart |

### Why This Stack?

- **Stability**: Python FastAPI is production-proven, single-process, minimal moving parts
- **Mobile reading**: MathJax and Mermaid render client-side with excellent mobile support
- **PDF quality**: Playwright uses real Chromium rendering — handles MathJax, Mermaid, and CSS correctly
- **Simple deployment**: One virtualenv, one systemd unit, no Docker required
- **Ubuntu 20.04 native**: All dependencies available via apt + pip

### Alternatives Considered

- **File Browser + separate Markdown service**: More moving parts, two services to manage
- **MkDocs Material**: Static site generator, requires rebuild on every file change
- **Node.js stack**: Added language dependency; user's environment is Python-centric

## Quick Start

```bash
# 1. Install
cd ~/remote_works_server
./install.sh

# 2. Edit config (optional)
nano config.yaml

# 3. Start server
./start.sh

# 4. Open browser
# http://<host-ip>:8088
```

## Configuration

Edit `config.yaml`:

```yaml
server:
  host: "0.0.0.0"       # Listen on all interfaces
  port: 8088             # HTTP port
  secret_key: "..."      # Session cookie secret (auto-generated)

paths:
  root_dir: "/home/galaxybot/remote_works"   # Served directory (read-only)
  cache_dir: "/home/galaxybot/.cache/remote_works_server"

auth:
  enabled: true
  username: "galaxybot"
  password_hash: "..."   # bcrypt hash (set by install.sh)

markdown:
  math: true             # LaTeX via MathJax
  mermaid: true          # Mermaid diagrams
  toc: true              # Table of contents
  highlight: true        # Code syntax highlighting

pdf:
  enabled: true
  engine: "playwright"   # PDF engine
  cache: true            # Cache generated PDFs
  page_format: "A4"
```

## Systemd Service (Auto-Start)

```bash
# Install service
sudo cp ~/remote_works_server/remote-works-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now remote-works-server

# Management commands
sudo systemctl start remote-works-server     # Start
sudo systemctl stop remote-works-server      # Stop
sudo systemctl restart remote-works-server   # Restart
sudo systemctl status remote-works-server    # Status
journalctl -u remote-works-server -f         # View logs (follow)
journalctl -u remote-works-server -n 50      # Last 50 lines
```

## Access from Phone/Tablet

### Option 1: Tailscale (Recommended)

If you use Tailscale, the server is automatically accessible at:

```
http://<tailscale-ip>:8088
```

Your phone just needs the Tailscale app installed and connected to the same tailnet.

### Option 2: Caddy Reverse Proxy + HTTPS

```bash
sudo apt-get install caddy

# /etc/caddy/Caddyfile
your-domain.example.com {
    reverse_proxy localhost:8088
}
```

### Option 3: Direct IP + Firewall

```bash
sudo ufw allow 8088/tcp
# Then access http://<host-public-ip>:8088
```

**Warning**: Direct IP access without HTTPS is insecure. Use Tailscale or Caddy+HTTPS for production.

## Managing Passwords

### Set/Change Password

```bash
cd ~/remote_works_server
source venv/bin/activate
python3 -c "from auth import get_auth; get_auth().set_password('new-password')"
deactivate
```

### Disable Authentication

Edit `config.yaml` and set `auth.enabled: false`, then restart the server.

## Managing Cache

```bash
# Clear PDF cache
rm -rf ~/.cache/remote_works_server/pdf/*

# Clear all cache
rm -rf ~/.cache/remote_works_server/*
```

Cache is automatically invalidated when source files are modified.

## Security

- All file access is restricted to `~/remote_works/` only
- Path traversal attacks are blocked (`../` is resolved and verified)
- Passwords are bcrypt-hashed, never stored in plaintext
- Session cookies are HttpOnly and SameSite=Lax
- Default mode is read-only — no upload, delete, or rename
- Static file serving is scoped to the static/ directory only
- systemd service uses `ProtectSystem=strict` and `NoNewPrivileges=yes`

## Testing

Test files are in `~/remote_works/`:

| File | Tests |
|------|-------|
| `test_markdown.md` | Headings, code, lists, blockquotes, images, links |
| `test_formula.md` | LaTeX inline (`$...$`) and block (`$$...$$`) formulas |
| `test_mermaid.md` | Mermaid flowcharts, sequence diagrams |
| `test_table.md` | Complex tables with alignment and formatting |
| `test_pdf.pdf` | PDF preview capability |

## Troubleshooting

### PDF generation fails

```bash
# Install Chromium system dependencies
sudo apt-get install -y chromium-browser

# Or install Playwright system deps
cd ~/remote_works_server
source venv/bin/activate
python3 -m playwright install --with-deps chromium
```

### Port already in use

```bash
# Change port in config.yaml, or kill existing process
sudo lsof -i :8088
```

### File changes not showing

The server reads files directly from disk on each request. Just refresh the browser page.

### Permission denied

Ensure the server user can read `~/remote_works/`:
```bash
chmod -R +r ~/remote_works/
```

## License

MIT
