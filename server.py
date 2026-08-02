"""Remote Works Server - FastAPI application for file browsing and document rendering."""

import asyncio
import mimetypes
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Response, Form, HTTPException, Query
from fastapi.responses import (
    HTMLResponse,
    FileResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from auth import get_auth
from file_index import get_index
from markdown_renderer import render_markdown
from pdf_generator import get_pdf_generator

import yaml

# Load config
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

# Templates
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Markdown/PDF
md_config = config.get("markdown", {})
ENABLE_MATH = md_config.get("math", True)
ENABLE_MERMAID = md_config.get("mermaid", True)
ENABLE_TOC = md_config.get("toc", True)
ENABLE_HIGHLIGHT = md_config.get("highlight", True)

PDF_ENABLED = config.get("pdf", {}).get("enabled", True)

app = FastAPI(title="Remote Works Server", version="1.0.0")

# Static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============================================================================
# Authentication Middleware
# ============================================================================

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    auth = get_auth()

    # Skip auth for static files and login page
    path = request.url.path
    skip_paths = ["/static", "/login", "/api/health"]

    if any(path.startswith(p) for p in skip_paths):
        return await call_next(request)

    if auth.needs_auth() and not auth.is_authenticated(request):
        # API requests return 401
        if path.startswith("/api/") or path.startswith("/download/"):
            return Response(
                content='{"error": "Unauthorized"}',
                status_code=401,
                media_type="application/json",
            )
        # Browser requests redirect to login
        return RedirectResponse(url=f"/login?redirect={path}", status_code=302)

    return await call_next(request)


# ============================================================================
# Template helper functions
# ============================================================================

def template_context(request: Request, **kwargs) -> dict:
    """Build template context with common variables."""
    auth = get_auth()
    return {
        "request": request,
        "authenticated": auth.is_authenticated(request),
        "needs_auth": auth.needs_auth(),
        "pdf_enabled": PDF_ENABLED,
        **kwargs,
    }


# ============================================================================
# Auth Routes
# ============================================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, redirect: str = "/"):
    auth = get_auth()
    if auth.is_authenticated(request):
        return RedirectResponse(url=redirect)
    return templates.TemplateResponse(
        "login.html", template_context(request, redirect=redirect)
    )


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    redirect: str = Form("/"),
):
    auth = get_auth()
    if username == auth.username and auth.verify_password(password):
        token = auth.create_session(username)
        resp = RedirectResponse(url=redirect, status_code=302)
        resp.set_cookie(
            "rws_session",
            token,
            httponly=True,
            max_age=86400 * 7,
            samesite="lax",
            secure=False,  # Set to True if using HTTPS
        )
        return resp

    return templates.TemplateResponse(
        "login.html",
        template_context(request, error="Invalid username or password", redirect=redirect),
        status_code=401,
    )


@app.get("/logout")
async def logout(request: Request):
    auth = get_auth()
    token = request.cookies.get("rws_session")
    if token:
        auth.destroy_session(token)
    resp = RedirectResponse(url="/login")
    resp.delete_cookie("rws_session")
    return resp


# ============================================================================
# File Browser Routes
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/browse/")


@app.get("/browse/", response_class=HTMLResponse)
async def browse_root(request: Request):
    """Browse root directory."""
    index = get_index()
    entries = index.list_directory("")
    breadcrumbs = [{"name": "Home", "path": "/browse/"}]
    return templates.TemplateResponse(
        "browse.html",
        template_context(
            request,
            entries=[e.to_dict() for e in entries],
            current_path="",
            breadcrumbs=breadcrumbs,
        ),
    )


@app.get("/browse/{rel_path:path}", response_class=HTMLResponse)
async def browse_path(request: Request, rel_path: str):
    """Browse a specific directory."""
    index = get_index()

    # Check if it's a directory
    target = index._resolve_path(rel_path)
    if target is None:
        return templates.TemplateResponse(
            "error.html",
            template_context(request, error="Path not found", message=f"Invalid path: {rel_path}"),
            status_code=404,
        )

    if target.is_file():
        # Redirect to view
        return RedirectResponse(url=f"/view/{rel_path}")

    entries = index.list_directory(rel_path)

    # Build breadcrumbs
    parts = rel_path.strip("/").split("/")
    breadcrumbs = [{"name": "Home", "path": "/browse/"}]
    acc = ""
    for part in parts:
        if part:
            acc += "/" + part
            breadcrumbs.append({"name": part, "path": f"/browse{acc}/"})

    return templates.TemplateResponse(
        "browse.html",
        template_context(
            request,
            entries=[e.to_dict() for e in entries],
            current_path=rel_path,
            breadcrumbs=breadcrumbs,
        ),
    )


# ============================================================================
# File View Routes
# ============================================================================

@app.get("/view/{rel_path:path}", response_class=HTMLResponse)
async def view_file(request: Request, rel_path: str):
    """View a file - renders markdown, displays PDF/image, or offers download."""
    index = get_index()
    entry = index.get_file_info(rel_path)

    if entry is None:
        return templates.TemplateResponse(
            "error.html",
            template_context(request, error="File not found", message=f"File not found: {rel_path}"),
            status_code=404,
        )

    if entry.is_dir:
        return RedirectResponse(url=f"/browse/{rel_path}")

    file_type = entry.type

    if file_type == "markdown":
        return await view_markdown(request, rel_path, entry)
    elif file_type == "pdf":
        return view_pdf(request, rel_path, entry)
    elif file_type == "image":
        return view_image(request, rel_path, entry)
    elif file_type in ("text", "code", "data", "web", "ros", "rosbag"):
        return await view_text(request, rel_path, entry)
    else:
        # Generic file - show download page
        return templates.TemplateResponse(
            "generic_file.html",
            template_context(request, entry=entry.to_dict()),
        )


async def view_markdown(request: Request, rel_path: str, entry):
    """Render markdown file as HTML."""
    index = get_index()
    content = index.read_file(rel_path)

    if content is None:
        return templates.TemplateResponse(
            "error.html",
            template_context(
                request,
                error="Cannot read file",
                message=f"Unable to read: {rel_path}",
            ),
            status_code=500,
        )

    try:
        md_html = render_markdown(content, base_path=rel_path)
    except Exception as e:
        return templates.TemplateResponse(
            "error.html",
            template_context(
                request,
                error="Markdown rendering failed",
                message=str(e),
            ),
            status_code=500,
        )

    return templates.TemplateResponse(
        "markdown.html",
        template_context(
            request,
            entry=entry.to_dict(),
            content_html=md_html,
            enable_math=ENABLE_MATH,
            enable_mermaid=ENABLE_MERMAID,
            enable_toc=ENABLE_TOC,
            enable_highlight=ENABLE_HIGHLIGHT,
            pdf_enabled=PDF_ENABLED,
        ),
    )


def view_pdf(request: Request, rel_path: str, entry):
    """Preview PDF file in browser."""
    return templates.TemplateResponse(
        "pdf_viewer.html",
        template_context(
            request,
            entry=entry.to_dict(),
            pdf_url=f"/download/{rel_path}",
        ),
    )


def view_image(request: Request, rel_path: str, entry):
    """Preview image file."""
    return templates.TemplateResponse(
        "image_viewer.html",
        template_context(
            request,
            entry=entry.to_dict(),
            image_url=f"/download/{rel_path}",
        ),
    )


async def view_text(request: Request, rel_path: str, entry):
    """View text/code file."""
    index = get_index()
    content = index.read_file(rel_path)

    if content is None:
        return templates.TemplateResponse(
            "error.html",
            template_context(request, error="Cannot read file", message=f"Unable to read: {rel_path}"),
            status_code=500,
        )

    return templates.TemplateResponse(
        "text_viewer.html",
        template_context(request, entry=entry.to_dict(), content=content),
    )


# ============================================================================
# Download Routes
# ============================================================================

@app.get("/download/{rel_path:path}")
async def download_file(request: Request, rel_path: str):
    """Download any file from root directory."""
    index = get_index()
    target = index._resolve_path(rel_path)

    if target is None or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Guess MIME type
    mime_type, _ = mimetypes.guess_type(str(target))
    if mime_type is None:
        mime_type = "application/octet-stream"

    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type=mime_type,
    )


# ============================================================================
# PDF Generation Route
# ============================================================================

@app.get("/api/pdf/{rel_path:path}")
async def generate_pdf(request: Request, rel_path: str):
    """Generate and download PDF for a markdown file."""
    index = get_index()
    entry = index.get_file_info(rel_path)

    if entry is None:
        raise HTTPException(status_code=404, detail="File not found")

    if entry.type != "markdown":
        raise HTTPException(status_code=400, detail="PDF generation only supports Markdown files")

    content = index.read_file(rel_path)
    if content is None:
        raise HTTPException(status_code=500, detail="Cannot read file")

    try:
        md_html = render_markdown(content, base_path=rel_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Markdown rendering failed: {e}")

    # Build full HTML page for PDF rendering
    pdf_html = build_pdf_html(entry.name, md_html)

    generator = get_pdf_generator()
    pdf_data = await generator.generate_pdf(pdf_html, rel_path, entry.mtime)

    if pdf_data is None:
        raise HTTPException(
            status_code=500,
            detail="PDF generation failed. The server may not have Chromium installed.",
        )

    # Return PDF with RFC 5987 encoded filename for Unicode support
    pdf_filename = Path(rel_path).stem + ".pdf"
    from urllib.parse import quote
    encoded_filename = quote(pdf_filename)
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
    )


@app.post("/api/pdf/{rel_path:path}/regenerate")
async def regenerate_pdf(request: Request, rel_path: str):
    """Force regenerate PDF, bypassing cache."""
    index = get_index()
    entry = index.get_file_info(rel_path)
    if entry is None:
        raise HTTPException(status_code=404, detail="File not found")

    generator = get_pdf_generator()
    # Invalidate by removing cached file
    cache_key = generator.get_cache_key(rel_path, entry.mtime)
    cache_path = generator.pdf_cache_dir / f"{cache_key}.pdf"
    if cache_path.exists():
        cache_path.unlink()

    return await generate_pdf(request, rel_path)


def build_pdf_html(title: str, md_html: str) -> str:
    """Build a complete HTML document for PDF printing."""
    math_config = ""
    mermaid_config = ""

    if ENABLE_MATH:
        math_config = """
        <script>
        window.MathJax = {
            tex: { inlineMath: [['$','$'], ['\\\\(','\\\\)']],
                   displayMath: [['$$','$$'], ['\\\\[','\\\\]']] },
            svg: { fontCache: 'global' }
        };
        </script>
        <script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
        """

    if ENABLE_MERMAID:
        mermaid_config = """
        <script>
        document.addEventListener('DOMContentLoaded', function() {
            if (typeof mermaid !== 'undefined') {
                mermaid.initialize({ startOnLoad: true, theme: 'default' });
            }
        });
        </script>
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
{math_config}
{mermaid_config}
<style>
  @page {{
    size: A4;
    margin: 20mm 15mm 20mm 15mm;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans SC', sans-serif;
    line-height: 1.6;
    max-width: 100%;
    margin: 0;
    padding: 0;
    color: #1a1a1a;
    font-size: 11pt;
  }}
  pre, code {{
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 9pt;
  }}
  pre {{
    background: #2d2d2d;
    color: #f8f8f2;
    padding: 12px;
    border-radius: 4px;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    page-break-inside: avoid;
  }}
  code {{
    background: #f0f0f0;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 9pt;
  }}
  pre code {{
    background: none;
    padding: 0;
  }}
  .table-wrapper {{
    overflow-x: auto;
    page-break-inside: avoid;
    margin: 1em 0;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 0;
    font-size: 9.5pt;
  }}
  th, td {{
    border: 1px solid #ddd;
    padding: 6px 10px;
    text-align: left;
  }}
  th {{ background: #f5f5f5; font-weight: 600; }}
  img {{ max-width: 100%; height: auto; page-break-inside: avoid; }}
  h1 {{ font-size: 18pt; border-bottom: 2px solid #eee; padding-bottom: 6px; page-break-after: avoid; }}
  h2 {{ font-size: 14pt; border-bottom: 1px solid #eee; padding-bottom: 4px; page-break-after: avoid; }}
  h3 {{ font-size: 12pt; page-break-after: avoid; }}
  h4 {{ font-size: 11pt; page-break-after: avoid; }}
  blockquote {{
    border-left: 4px solid #ccc;
    margin: 1em 0;
    padding: 8px 16px;
    color: #555;
    background: #f9f9f9;
  }}
  .footnote-ref {{ font-size: 0.8em; vertical-align: super; }}
  .task-list-item {{ list-style: none; }}
  .task-list-item input {{ margin-right: 6px; }}
</style>
</head>
<body>
{md_html}
</body>
</html>"""


# ============================================================================
# API Routes
# ============================================================================

@app.get("/api/search")
async def search_files(request: Request, q: str = Query(..., min_length=1)):
    """Search files."""
    index = get_index()
    results = index.search(q)
    return {"results": [e.to_dict() for e in results]}


@app.get("/api/recent")
async def recent_files(request: Request, limit: int = Query(30, le=100)):
    """Get recently modified files."""
    index = get_index()
    entries = index.recent_files(limit=limit)
    return {"files": [e.to_dict() for e in entries]}


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(
        "error.html",
        template_context(request, error="Page not found", message="The requested page does not exist."),
        status_code=404,
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return templates.TemplateResponse(
        "error.html",
        template_context(request, error="Server error", message="An internal error occurred."),
        status_code=500,
    )


# ============================================================================
# Main
# ============================================================================

def main():
    server_cfg = config.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = server_cfg.get("port", 8088)

    print(f"Starting Remote Works Server on http://{host}:{port}")
    print(f"Serving: {config.get('paths', {}).get('root_dir', '~/remote_works')}")

    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
