"""Main FastAPI application for remote-works-server."""
from __future__ import annotations

import os
import sys
import time
import asyncio
import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Response, Form, Query
from fastapi.responses import (
    HTMLResponse,
    FileResponse,
    RedirectResponse,
    JSONResponse,
    PlainTextResponse,
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from app.config import config
from app.auth import AuthMiddleware, verify_password, hash_password, SESSION_COOKIE, SESSION_TOKEN
from app.file_browser import resolve_safe_path, list_directory, get_file_info, search_files, get_recent_files
from app.markdown_utils import render_markdown
from app.pdf_utils import generate_pdf, build_pdf_html, get_cached_pdf
from app import cache_utils
from app.watcher import FileWatcher

# ---- App Initialization ----

app = FastAPI(title="Remote Works Server", version="1.0.0")

# Set up Jinja2 templates
templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Add auth middleware
app.add_middleware(AuthMiddleware)

# Static files (CSS, JS)
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)

# ---- Startup / Shutdown Events ----

@app.on_event("startup")
async def startup():
    """Initialize the application."""
    # Initialize cache DB
    cache_utils._init_db()

    # Start file watcher
    if config["file_watcher"]["enabled"]:
        watcher = FileWatcher(interval=config["file_watcher"]["interval_seconds"])
        watcher.start()
        app.state.watcher = watcher
        print("[Startup] File watcher started")

    # Run initial full scan
    from app.file_browser import search_files as search, get_recent_files as recent
    print(f"[Startup] Remote Works Server started")
    print(f"[Startup] Root directory: {config['root_dir']}")
    print(f"[Startup] Listening on {config['host']}:{config['port']}")
    if config["auth"]["enabled"]:
        print(f"[Startup] Auth enabled (user: {config['auth']['username']})")


@app.on_event("shutdown")
async def shutdown():
    """Clean up on shutdown."""
    if hasattr(app.state, "watcher"):
        app.state.watcher.stop()
        print("[Shutdown] File watcher stopped")

# ---- Helper Functions ----

def _get_breadcrumbs(request_path: str) -> list:
    """Generate breadcrumb navigation for a given path."""
    parts = request_path.strip("/").split("/") if request_path.strip("/") else []
    crumbs = [{"name": "🏠 Home", "path": "/"}]
    for i, part in enumerate(parts):
        crumb_path = "/" + "/".join(parts[:i+1])
        crumbs.append({"name": part, "path": crumb_path})
    return crumbs


# ---- Routes ----

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    """Show login page."""
    # If already logged in, redirect to home
    session = request.cookies.get(SESSION_COOKIE)
    if session == SESSION_TOKEN:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error}
    )


@app.post("/api/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle login form submission."""
    cfg_auth = config["auth"]
    expected_user = cfg_auth["username"]
    expected_hash = cfg_auth["password_hash"]

    if username != expected_user:
        return RedirectResponse(url="/login?error=Invalid credentials", status_code=302)

    if not expected_hash:
        # First login — set password to whatever was entered
        config["auth"]["password_hash"] = hash_password(password)
        # Persist to config file
        _persist_password_hash(config["auth"]["password_hash"])
    elif not verify_password(password, expected_hash):
        return RedirectResponse(url="/login?error=Invalid credentials", status_code=302)

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=SESSION_TOKEN,
        max_age=86400 * 30,  # 30 days
        httponly=True,
        samesite="lax",
    )
    return response


@app.get("/api/logout")
async def logout():
    """Log out by clearing the session cookie."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key=SESSION_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, path: str = Query(""), sort: str = Query("name")):
    """File browser home page."""
    root_dir = config["root_dir"]
    request_path = path or ""

    if request_path:
        abs_path, error = resolve_safe_path(root_dir, request_path)
        if error:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": error, "title": "Error"},
                status_code=400,
            )
    else:
        abs_path = root_dir

    # Check if path exists
    if not os.path.exists(abs_path):
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "File or directory not found", "title": "Not Found"},
            status_code=404,
        )

    if os.path.isfile(abs_path):
        # Direct file access: handle based on type
        ext = os.path.splitext(abs_path)[1].lower()
        rel_path = os.path.relpath(abs_path, root_dir)

        if ext == ".md":
            return await _render_markdown(request, rel_path)
        elif ext == ".pdf":
            return await _view_pdf(request, rel_path)
        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            return await _serve_file(request, rel_path)
        else:
            # Offer download
            return await _serve_file(request, rel_path)

    # List directory contents
    entries = list_directory(abs_path, root_dir)
    crumbs = _get_breadcrumbs(request_path)
    current_dir = os.path.basename(abs_path) if request_path else "remote_works"

    # Sort
    reverse = False
    sort_key = sort.lstrip("-")
    if sort.startswith("-"):
        reverse = True
    if sort_key == "name":
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()), reverse=reverse)
    elif sort_key == "mtime":
        entries.sort(key=lambda e: (not e["is_dir"], e["mtime"]), reverse=reverse)
    elif sort_key == "size":
        entries.sort(key=lambda e: (not e["is_dir"], e["size"]), reverse=reverse)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "entries": entries,
            "breadcrumbs": crumbs,
            "current_path": request_path,
            "current_dir": current_dir,
            "sort": sort,
            "title": f"Files - {current_dir}",
        }
    )


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = Query("")):
    """Search files by name."""
    root_dir = config["root_dir"]
    if not q.strip():
        return RedirectResponse(url="/", status_code=302)

    results = search_files(root_dir, q.strip())
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "results": results,
            "query": q.strip(),
            "title": f"Search: {q}",
        }
    )


@app.get("/recent", response_class=HTMLResponse)
async def recent(request: Request):
    """Show recently modified files."""
    root_dir = config["root_dir"]
    files = get_recent_files(root_dir, limit=50)
    return templates.TemplateResponse(
        "recent.html",
        {
            "request": request,
            "files": files,
            "title": "Recent Files",
        }
    )


# ---- File Serving ----

@app.get("/api/files/{path:path}")
async def _serve_file(request: Request, path: str):
    """Serve a file for download or preview."""
    root_dir = config["root_dir"]
    abs_path, error = resolve_safe_path(root_dir, path)
    if error:
        raise HTTPException(status_code=400, detail=error)

    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Determine content type
    content_type, _ = mimetypes.guess_type(abs_path)
    if content_type is None:
        content_type = "application/octet-stream"

    # For images and PDFs, allow inline preview
    ext = os.path.splitext(abs_path)[1].lower()
    disposition = "inline"
    if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
        disposition = "attachment"

    filename = os.path.basename(abs_path)
    return FileResponse(
        abs_path,
        media_type=content_type,
        filename=filename,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@app.get("/api/download/{path:path}")
async def download_file(path: str):
    """Force download a file."""
    root_dir = config["root_dir"]
    abs_path, error = resolve_safe_path(root_dir, path)
    if error:
        raise HTTPException(status_code=400, detail=error)

    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="File not found")

    content_type, _ = mimetypes.guess_type(abs_path)
    if content_type is None:
        content_type = "application/octet-stream"

    filename = os.path.basename(abs_path)
    return FileResponse(
        abs_path,
        media_type=content_type,
        filename=filename,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@app.get("/api/download-zip/{path:path}")
async def download_directory_zip(path: str):
    """Download a directory as a ZIP file. (Placeholder for future implementation)"""
    return JSONResponse(
        status_code=501,
        content={"error": "Directory ZIP download not yet implemented"}
    )


# ---- Markdown Routes ----

@app.get("/api/render-md/{path:path}")
async def api_render_markdown(path: str):
    """API endpoint that returns rendered HTML for a markdown file."""
    root_dir = config["root_dir"]
    abs_path, error = resolve_safe_path(root_dir, path)
    if error:
        raise HTTPException(status_code=400, detail=error)

    if not os.path.isfile(abs_path) or not abs_path.endswith(".md"):
        raise HTTPException(status_code=404, detail="Markdown file not found")

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        html_body, toc, has_mermaid = render_markdown(text, abs_path)
        return {"html": html_body, "toc": toc, "has_mermaid": has_mermaid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render error: {str(e)}")


@app.get("/md/{path:path}", response_class=HTMLResponse)
async def _render_markdown(request: Request, path: str):
    """Render a Markdown file as a full HTML page."""
    root_dir = config["root_dir"]
    abs_path, error = resolve_safe_path(root_dir, path)
    if error:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": error, "title": "Error"},
            status_code=400,
        )

    if not os.path.isfile(abs_path) or not abs_path.endswith(".md"):
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Markdown file not found", "title": "Not Found"},
            status_code=404,
        )

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        html_body, toc_html, has_mermaid = render_markdown(text, abs_path)
        has_math = "$" in text or "$$" in text
        title = os.path.basename(abs_path)
        # Extract first h1 for title
        import re
        h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html_body)
        if h1_match:
            title = re.sub(r'<[^>]+>', '', h1_match.group(1))

        # Get file mtime for display
        st = os.stat(abs_path)
        mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))

        # Check if PDF is cached
        pdf_available = get_cached_pdf(abs_path, text) is not None

        return templates.TemplateResponse(
            "markdown.html",
            {
                "request": request,
                "title": title,
                "html_body": html_body,
                "toc": toc_html,
                "has_mermaid": has_mermaid,
                "has_math": has_math and config["markdown"]["math"],
                "file_path": path,
                "mtime": mtime_str,
                "pdf_available": pdf_available,
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": f"Markdown rendering error: {str(e)}", "title": "Render Error"},
            status_code=500,
        )


@app.post("/api/md-to-pdf/{path:path}")
async def markdown_to_pdf(path: str):
    """Convert a Markdown file to PDF and return the file."""
    root_dir = config["root_dir"]
    abs_path, error = resolve_safe_path(root_dir, path)
    if error:
        raise HTTPException(status_code=400, detail=error)

    if not os.path.isfile(abs_path) or not abs_path.endswith(".md"):
        raise HTTPException(status_code=404, detail="Markdown file not found")

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        # Check cache first
        cached = get_cached_pdf(abs_path, text)
        if cached:
            filename = os.path.splitext(os.path.basename(abs_path))[0] + ".pdf"
            return FileResponse(
                cached,
                media_type="application/pdf",
                filename=filename,
                headers={"Content-Disposition": f'inline; filename="{filename}"'},
            )

        # Render markdown
        html_body, _, has_mermaid = render_markdown(text, abs_path)
        has_math = "$" in text or "$$" in text
        title = os.path.basename(abs_path)

        # Build full HTML for PDF
        full_html = build_pdf_html(html_body, title, has_mermaid, has_math)

        # Generate PDF
        pdf_path = await generate_pdf(abs_path, text, html_body, full_html)
        if pdf_path is None or not os.path.exists(pdf_path):
            return JSONResponse(
                status_code=500,
                content={
                    "error": "PDF generation failed. Check that Chromium is installed.",
                    "hint": "Run: playwright install chromium",
                },
            )

        # Update cache tracking
        import hashlib
        key = hashlib.sha256(abs_path.encode("utf-8") + text.encode("utf-8")).hexdigest()[:32]
        st = os.stat(abs_path)
        cache_utils.mark_cache(key, os.path.relpath(abs_path, root_dir), "pdf", st.st_mtime, os.path.getsize(pdf_path))

        filename = os.path.splitext(os.path.basename(abs_path))[0] + ".pdf"
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=filename,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"PDF generation error: {str(e)}"},
        )


# ---- PDF Viewing ----

@app.get("/pdf/{path:path}", response_class=HTMLResponse)
async def _view_pdf(request: Request, path: str):
    """View a PDF file in the browser."""
    root_dir = config["root_dir"]
    abs_path, error = resolve_safe_path(root_dir, path)
    if error:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": error, "title": "Error"},
            status_code=400,
        )

    if not os.path.isfile(abs_path) or not abs_path.endswith(".pdf"):
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "PDF file not found", "title": "Not Found"},
            status_code=404,
        )

    filename = os.path.basename(abs_path)
    return templates.TemplateResponse(
        "pdf_view.html",
        {
            "request": request,
            "file_path": path,
            "filename": filename,
            "title": f"PDF - {filename}",
        }
    )


# ---- Config API (for first-time setup) ----

@app.get("/api/status")
async def status():
    """Return server status."""
    from app.file_browser import list_directory
    root_dir = config["root_dir"]
    exists = os.path.isdir(root_dir)
    stats = {"root_dir": root_dir, "exists": exists}
    if exists:
        entries = list_directory(root_dir, root_dir)
        stats["file_count"] = len([e for e in entries if not e.get("error")])
    return stats


@app.post("/api/set-password")
async def set_password(current_password: str = Form(...), new_password: str = Form(...)):
    """Change the login password."""
    cfg_auth = config["auth"]
    if not verify_password(current_password, cfg_auth["password_hash"]):
        raise HTTPException(status_code=403, detail="Current password is incorrect")

    new_hash = hash_password(new_password)
    config["auth"]["password_hash"] = new_hash
    _persist_password_hash(new_hash)
    return {"status": "ok", "message": "Password updated successfully"}


def _persist_password_hash(password_hash: str):
    """Persist the password hash to the config file."""
    import yaml
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f) or {}
        if "auth" not in cfg:
            cfg["auth"] = {}
        cfg["auth"]["password_hash"] = password_hash
        with open(config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)


# ---- Entry Point ----

def run():
    """Run the application with uvicorn."""
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=config["host"],
        port=config["port"],
        log_level="info",
        reload=False,
        workers=1,
    )


if __name__ == "__main__":
    run()
