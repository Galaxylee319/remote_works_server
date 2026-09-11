"""Remote Works Server v2 — FastAPI application."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from app.auth import (
    SESSION_COOKIE,
    AuthMiddleware,
    client_ip,
    persist_password_hash,
    rate_limiter,
    sessions,
    verify_password,
)
from app.config import config
from app.file_browser import (
    build_nav_tree,
    get_file_info,
    get_recent_files,
    human_size,
    list_directory,
    resolve_safe_path,
    search_files,
    search_content,
    sibling_files,
    sibling_media,
    get_recent_files,
)
from app.markdown_utils import render_markdown
from app.pdf_utils import (
    build_pdf_html,
    close_browser,
    generate_pdf,
    get_cached_pdf,
    invalidate_pdf_cache,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("remote-works-server")

THUMB_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}

app = FastAPI(title="远程工作区服务", version="2.0.0")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

static_dir = os.path.join(BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.add_middleware(AuthMiddleware)


# 目录名汉化迁移表：旧英文路径 → 新中文路径
# 作用：历史书签、旧文档里写死的 URL、外部链接仍可访问（307 临时重定向，保留方法与查询串）。
PATH_ALIASES = {
    "archive": "归档",
    "data": "数据",
    "deliverables": "交付物",
    "docs": "文档",
    "experiments": "实验",
    "figures_paper": "论文插图",
    "figures_TypeI": "TypeI图表",
    "papers": "论文",
    "phases": "阶段报告",
    "plans": "计划",
    "reports": "报告",
    "scripts": "脚本",
    "typeI_logs": "TypeI日志",
    "paper_translation": "论文翻译",
}


class PathAliasMiddleware(BaseHTTPMiddleware):
    """把旧顶层目录名的 URL 重定向到新中文名。

    别名可能出现在第 1 段（根级）或第 2 段（`/browse/<别名>/…`、`/view/<别名>/…`、
    `/api/files/<别名>/…` 等），因此按路由前缀逐段匹配。
    """

    # 段数不定的前缀放后面匹配（先试更长的）
    ROUTE_PREFIXES = (
        "api/download-zip", "api/files", "api/pdf",
        "browse", "view", "pdf", "md", "download", "thumb",
    )

    async def dispatch(self, request: Request, call_next):
        parts = request.url.path.lstrip("/").split("/")
        new_parts = None
        for pref in self.ROUTE_PREFIXES:
            pseg = pref.split("/")
            if len(parts) > len(pseg) and parts[: len(pseg)] == pseg:
                head = parts[len(pseg)]
                if head in PATH_ALIASES and head != PATH_ALIASES[head]:
                    new_parts = parts[: len(pseg)] + [PATH_ALIASES[head]] + parts[len(pseg) + 1 :]
                break
        if new_parts is None and parts and parts[0] in PATH_ALIASES:
            new_parts = [PATH_ALIASES[parts[0]]] + parts[1:]
        if new_parts is not None:
            url = "/" + "/".join(new_parts)
            if request.url.query:
                url += "?" + request.url.query
            return RedirectResponse(url=url, status_code=307)
        return await call_next(request)


# 后添加的中间件在最外层：别名重定向先于鉴权执行，未登录也能被正确跳转
app.add_middleware(PathAliasMiddleware)

STARTED_AT = time.time()
TEXT_PREVIEW_LIMIT = 2 * 1024 * 1024  # 2 MiB


def ensure_sync_links() -> None:
    """Create configured external-dir symlinks under the served root."""
    root = config["root_dir"]
    for name, src in config.get("sync_dirs", {}).items():
        link = os.path.join(root, name)
        try:
            if os.path.lexists(link):
                if not os.path.isdir(link):
                    logger.warning("Sync path exists but is not a directory: %s", link)
                continue
            if not os.path.isdir(src):
                logger.warning("Sync source missing, skip link %s -> %s", link, src)
                continue
            os.symlink(src, link)
            logger.info("Created sync link %s -> %s", link, src)
        except OSError as e:
            logger.warning("Could not create sync link %s -> %s: %s", link, src, e)


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    os.makedirs(config["cache_dir"], exist_ok=True)
    os.makedirs(os.path.join(config["cache_dir"], "pdf"), exist_ok=True)
    root = config["root_dir"]
    if not os.path.isdir(root):
        logger.warning("Root directory missing: %s", root)
    else:
        ensure_sync_links()
    logger.info(
        "Started: root=%s cache=%s host=%s port=%s auth=%s",
        root,
        config["cache_dir"],
        config["host"],
        config["port"],
        config["auth"]["enabled"],
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    await close_browser()
    logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _context(request: Request, **kwargs) -> dict:
    ctx = {
        "request": request,
        "authenticated": True,
        "needs_auth": config["auth"]["enabled"],
        "pdf_enabled": config["pdf"].get("enabled", True),
        "zip_enabled": config["zip"].get("enabled", True),
    }
    ctx.update(kwargs)
    return ctx


def _breadcrumbs(rel_path: str) -> list:
    parts = [p for p in rel_path.strip("/").split("/") if p]
    crumbs = [{"name": "Home", "path": "/browse/"}]
    acc = ""
    for part in parts:
        acc += "/" + part
        crumbs.append({"name": part, "path": "/browse" + acc + "/"})
    return crumbs


def _error_response(request: Request, status_code: int, error: str, message: str = ""):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=status_code, content={"error": error, "message": message})
    return templates.TemplateResponse(
        "error.html",
        _context(request, error=error, message=message, title=error),
        status_code=status_code,
    )


def _resolve_or_error(request: Request, path: str, need_file: bool = False):
    """Resolve path; returns (abs_path, None) or (None, response)."""
    abs_path, err = resolve_safe_path(config["root_dir"], path)
    if err:
        return None, _error_response(request, 400, "路径错误", err)
    if need_file and not os.path.isfile(abs_path):
        return None, _error_response(request, 404, "文件不存在", f"文件不存在: {path}")
    return abs_path, None


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/browse/"):
    token = request.cookies.get(SESSION_COOKIE)
    if sessions.validate(token):
        return RedirectResponse(url=next, status_code=302)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "", "next": next, "needs_auth": True},
    )


@app.post("/api/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/browse/"),
):
    ip = client_ip(request)
    if rate_limiter.is_blocked(ip, username):
        return JSONResponse(
            status_code=429,
            content={"error": "登录尝试过于频繁，请稍后再试"},
        )

    expected_user = config["auth"]["username"]
    expected_hash = config["auth"]["password_hash"]
    if username != expected_user or not verify_password(password, expected_hash):
        rate_limiter.record_failure(ip, username)
        return JSONResponse(status_code=401, content={"error": "用户名或密码错误"})

    rate_limiter.reset(ip, username)
    token = sessions.create()
    if not next.startswith("/") or next.startswith("//"):
        next = "/browse/"
    response = RedirectResponse(url=next, status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=config["auth"]["session_ttl_days"] * 86400,
        httponly=True,
        samesite="lax",
        secure=config["auth"].get("cookie_secure", False),
        path="/",
    )
    return response


@app.get("/api/logout")
async def logout(request: Request):
    sessions.destroy(request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.post("/api/set-password")
async def set_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
):
    if not verify_password(current_password, config["auth"]["password_hash"]):
        return JSONResponse(status_code=403, content={"error": "当前密码不正确"})
    if len(new_password) < 8:
        return JSONResponse(status_code=400, content={"error": "新密码至少 8 位"})
    from app.auth import hash_password

    persist_password_hash(hash_password(new_password))
    sessions.clear()
    return JSONResponse(status_code=200, content={"status": "ok"})


# ---------------------------------------------------------------------------
# Browse routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/browse/", status_code=307)


@app.get("/browse/", response_class=HTMLResponse)
async def browse_root(request: Request, sort: str = Query("name")):
    return await browse_path(request, "", sort)


@app.get("/browse/{rel_path:path}", response_class=HTMLResponse)
async def browse_path(request: Request, rel_path: str, sort: str = Query("name")):
    abs_path, err_resp = _resolve_or_error(request, rel_path)
    if err_resp is not None:
        return err_resp

    if os.path.isfile(abs_path):
        return RedirectResponse(url="/view/" + rel_path.lstrip("/"), status_code=302)

    entries = list_directory(abs_path, config["root_dir"])
    if entries and "error" in entries[0]:
        return _error_response(request, 500, "目录读取失败", entries[0]["error"])

    reverse = sort.startswith("-")
    key = sort.lstrip("-")
    if key == "mtime":
        entries.sort(key=lambda e: (not e["is_dir"], e["mtime"]), reverse=reverse)
    elif key == "size":
        entries.sort(key=lambda e: (not e["is_dir"], e["size"]), reverse=reverse)
    else:
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()), reverse=reverse)

    nav_levels = build_nav_tree(config["root_dir"], rel_path)

    n_dirs = sum(1 for e in entries if e["is_dir"])
    n_files = len(entries) - n_dirs
    total_size = sum(e["size"] for e in entries if not e["is_dir"])
    stats = {
        "dirs": n_dirs,
        "files": n_files,
        "size_str": _human_size(total_size),
    }

    return templates.TemplateResponse(
        "browse.html",
        _context(
            request,
            entries=entries,
            current_path=rel_path,
            breadcrumbs=_breadcrumbs(rel_path),
            sort=sort,
            stats=stats,
            nav_levels=nav_levels,
            title="文件 · 远程工作区",
        ),
    )


def _human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


@app.get("/feed.xml")
async def feed(request: Request, path: str = Query(""), limit: int = Query(50, ge=1, le=200)):
    """「最近更新」RSS 2.0 订阅（需登录态；浏览器直接打开即可）。"""
    sub = path.strip().strip("/")
    root_real = os.path.realpath(config["root_dir"])
    target = os.path.join(config["root_dir"], sub) if sub else config["root_dir"]
    target_real = os.path.realpath(target)
    if target_real != root_real and not target_real.startswith(root_real + os.sep):
        raise HTTPException(status_code=400, detail="非法路径")
    if not os.path.isdir(target_real):
        raise HTTPException(status_code=404, detail="目录不存在")

    files = get_recent_files(target_real if sub else config["root_dir"], limit=limit)
    host = request.headers.get("host", "localhost")
    base = f"{request.url.scheme}://{host}"
    title = "远程工作区 · 最近更新" + (f"（{sub}）" if sub else "")

    def esc(value) -> str:
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    parts = []
    for f in files:
        rel = f["path"]
        link = base + "/view/" + quote(rel)
        dl = base + "/download/" + quote(rel)
        desc = (
            "<p><a href='" + link + "'>" + esc(rel) + "</a></p>"
            "<p>" + esc(f.get("size_str", "")) + " · " + esc(f.get("mtime_str", ""))
            + " · 类型 " + esc(f.get("type", "")) + "</p>"
            "<p><a href='" + dl + "'>下载</a></p>"
        )
        pub = time.strftime("%a, %d %b %Y %H:%M:%S +0800", time.localtime(f.get("mtime", 0)))
        parts.append(
            "    <item>\n"
            "      <title>" + esc(rel) + "</title>\n"
            "      <link>" + esc(link) + "</link>\n"
            '      <guid isPermaLink="false">' + esc(rel) + "</guid>\n"
            "      <pubDate>" + pub + "</pubDate>\n"
            "      <description>" + esc(desc) + "</description>\n"
            "    </item>\n"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n<channel>\n'
        "  <title>" + esc(title) + "</title>\n"
        "  <link>" + esc(base + "/recent") + "</link>\n"
        "  <description>" + esc(config.get("server", {}).get("title", "远程工作区")) + " · 最近更新的文件</description>\n"
        "  <lastBuildDate>" + time.strftime("%a, %d %b %Y %H:%M:%S +0800") + "</lastBuildDate>\n"
        + "".join(parts)
        + "</channel>\n</rss>\n"
    )
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


# ---------------------------------------------------------------------------
# View routes
# ---------------------------------------------------------------------------

@app.get("/view/{rel_path:path}", response_class=HTMLResponse)
async def view_file(request: Request, rel_path: str):
    abs_path, err_resp = _resolve_or_error(request, rel_path)
    if err_resp is not None:
        return err_resp
    if os.path.isdir(abs_path):
        return RedirectResponse(url="/browse/" + rel_path.lstrip("/") + "/", status_code=302)

    info = get_file_info(abs_path, config["root_dir"])
    if info is None:
        return _error_response(request, 404, "文件不存在", rel_path)

    ftype = info["type"]
    if ftype == "markdown":
        return await _markdown_page(request, rel_path)
    if ftype == "pdf":
        return _pdf_viewer(request, info)
    if ftype == "image":
        return _image_viewer(request, info, abs_path)
    if ftype in ("text", "code", "data", "web", "ros", "rosbag", "mesh", "pointcloud"):
        return await _text_viewer(request, rel_path, info)
    return _generic_viewer(request, info)


@app.get("/md/{rel_path:path}", response_class=HTMLResponse)
async def md_alias(request: Request, rel_path: str):
    return await _markdown_page(request, rel_path)


@app.get("/pdf/{rel_path:path}", response_class=HTMLResponse)
async def pdf_alias(request: Request, rel_path: str):
    abs_path, err_resp = _resolve_or_error(request, rel_path, need_file=True)
    if err_resp is not None:
        return err_resp
    info = get_file_info(abs_path, config["root_dir"])
    if info is None or info["type"] != "pdf":
        return _error_response(request, 404, "PDF 文件不存在", rel_path)
    return _pdf_viewer(request, info)


def _pdf_viewer(request: Request, info: dict):
    return templates.TemplateResponse(
        "pdf_viewer.html",
        _context(request, entry=info, title=f"PDF · {info['name']}"),
    )


def _image_viewer(request: Request, info: dict, abs_path: str):
    """单图查看页，附同目录兄弟图片以便上/下一张导航。"""
    siblings = sibling_media(abs_path, config["root_dir"])
    idx = next((i for i, s in enumerate(siblings) if s["path"] == info["path"]), -1)
    prev_item = siblings[idx - 1] if idx > 0 else None
    next_item = siblings[idx + 1] if 0 <= idx < len(siblings) - 1 else None
    return templates.TemplateResponse(
        "image_viewer.html",
        _context(
            request,
            entry=info,
            siblings=siblings,
            index=idx + 1 if idx >= 0 else 0,
            total=len(siblings),
            prev_item=prev_item,
            next_item=next_item,
            title=f"图片 · {info['name']}",
        ),
    )


def _generic_viewer(request: Request, info: dict):
    return templates.TemplateResponse(
        "generic_file.html",
        _context(request, entry=info, title=info["name"]),
    )


async def _text_viewer(request: Request, rel_path: str, info: dict):
    abs_path, _ = _resolve_or_error(request, rel_path, need_file=True)
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(TEXT_PREVIEW_LIMIT + 1)
    except OSError as e:
        return _error_response(request, 500, "文件读取失败", str(e))
    truncated = len(content) > TEXT_PREVIEW_LIMIT
    if truncated:
        content = content[:TEXT_PREVIEW_LIMIT]
    return templates.TemplateResponse(
        "text_viewer.html",
        _context(
            request,
            entry=info,
            content=content,
            truncated=truncated,
            title=info["name"],
        ),
    )


async def _markdown_page(request: Request, rel_path: str):
    abs_path, err_resp = _resolve_or_error(request, rel_path, need_file=True)
    if err_resp is not None:
        return err_resp
    info = get_file_info(abs_path, config["root_dir"])
    if info is None:
        return _error_response(request, 404, "文件不存在", rel_path)
    if info["type"] != "markdown":
        return _error_response(request, 400, "不是 Markdown 文件", rel_path)

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return _error_response(request, 500, "文件读取失败", str(e))

    try:
        html_body, toc_html, has_mermaid = render_markdown(text, abs_path)
    except Exception as e:
        logger.exception("Markdown render failed: %s", rel_path)
        return _error_response(request, 500, "Markdown 渲染失败", str(e))

    title = info["name"]
    import re

    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html_body, flags=re.DOTALL)
    if h1:
        clean = re.sub(r"<[^>]+>", "", h1.group(1)).strip()
        if clean:
            title = clean

    has_math = "$$" in text or "$" in text or "\\[" in text or "\\(" in text
    pdf_available = get_cached_pdf(abs_path, text) is not None

    # 同目录其他 Markdown：上一个/下一个 + 列表（便于连续阅读阶段报告）
    sibs = sibling_files(abs_path, config["root_dir"], (".md", ".markdown"), limit=300)
    sidx = next((i for i, x in enumerate(sibs) if x["path"] == info["path"]), -1)
    doc_prev = sibs[sidx - 1] if sidx > 0 else None
    doc_next = sibs[sidx + 1] if 0 <= sidx < len(sibs) - 1 else None
    others = [x for x in sibs if x["path"] != info["path"]]

    return templates.TemplateResponse(
        "markdown.html",
        _context(
            request,
            entry=info,
            title=title,
            doc_prev=doc_prev,
            doc_next=doc_next,
            doc_others=others[:12],
            doc_total=len(others),
            content_html=html_body,
            toc_html=toc_html,
            has_mermaid=has_mermaid and config["markdown"].get("mermaid", True),
            has_math=has_math and config["markdown"].get("math", True),
            enable_toc=config["markdown"].get("toc", True),
            enable_math=config["markdown"].get("math", True),
            enable_mermaid=config["markdown"].get("mermaid", True),
            enable_highlight=config["markdown"].get("highlight", True),
            file_path=rel_path,
            mtime=info["mtime_str"],
            pdf_available=pdf_available,
        ),
    )


# ---------------------------------------------------------------------------
# File serving
# ---------------------------------------------------------------------------

def _file_response(abs_path: str, disposition: str = "attachment") -> Response:
    content_type, _ = mimetypes.guess_type(abs_path)
    if content_type is None:
        content_type = "application/octet-stream"
    filename = os.path.basename(abs_path)
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    return FileResponse(
        abs_path,
        media_type=content_type,
        filename=filename,
        headers={
            "Content-Disposition": (
                f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/files/{rel_path:path}")
async def serve_file(request: Request, rel_path: str):
    abs_path, err_resp = _resolve_or_error(request, rel_path, need_file=True)
    if err_resp is not None:
        return err_resp
    ext = os.path.splitext(abs_path)[1].lower()
    disposition = "inline" if ext in (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp") else "attachment"
    return _file_response(abs_path, disposition)


@app.get("/download/{rel_path:path}")
async def download_file(request: Request, rel_path: str):
    abs_path, err_resp = _resolve_or_error(request, rel_path, need_file=True)
    if err_resp is not None:
        return err_resp
    return _file_response(abs_path, "attachment")


@app.get("/api/download-zip/{rel_path:path}")
async def download_directory_zip(request: Request, rel_path: str):
    if not config["zip"].get("enabled", True):
        return JSONResponse(status_code=501, content={"error": "ZIP 下载未启用"})
    abs_path, err_resp = _resolve_or_error(request, rel_path)
    if err_resp is not None:
        return err_resp
    if not os.path.isdir(abs_path):
        return JSONResponse(status_code=400, content={"error": "只能打包下载目录"})

    import zipfile

    max_files = config["zip"].get("max_files", 5000)
    max_bytes = config["zip"].get("max_bytes", 2 * 1024 ** 3)
    fd, tmp_path = tempfile.mkstemp(suffix=".zip", dir=config["cache_dir"])
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            count = 0
            total = 0
            root = config["root_dir"]
            base = os.path.basename(abs_path.rstrip("/")) or "files"
            for dirpath, dirnames, filenames in os.walk(abs_path):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for name in filenames:
                    if name.startswith("."):
                        continue
                    full = os.path.join(dirpath, name)
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        continue
                    if count >= max_files or total + size > max_bytes:
                        return JSONResponse(
                            status_code=413,
                            content={"error": "目录过大，超出打包限制", "max_files": max_files},
                        )
                    arcname = os.path.join(base, os.path.relpath(full, abs_path))
                    zf.write(full, arcname)
                    count += 1
                    total += size
        return FileResponse(
            tmp_path,
            media_type="application/zip",
            filename=f"{base}.zip",
            background=BackgroundTask(_remove_file, tmp_path),
        )
    except Exception as e:
        _remove_file(tmp_path)
        logger.exception("Zip failed: %s", rel_path)
        return JSONResponse(status_code=500, content={"error": f"打包失败: {e}"})


@app.post("/api/download-selected")
async def download_selected(request: Request):
    """把勾选的多个文件/目录打包为一个 ZIP（表单 POST，浏览器直接下载）。"""
    if not config["zip"].get("enabled", True):
        return JSONResponse(status_code=501, content={"error": "ZIP 下载未启用"})

    form = await request.form()
    raw_paths = [str(v) for v in form.getlist("paths")][:1000]
    if not raw_paths:
        return JSONResponse(status_code=400, content={"error": "未选择任何文件"})

    root = config["root_dir"]
    resolved = []
    for rel in raw_paths:
        abs_p, err = resolve_safe_path(root, rel)
        if err or not abs_p:
            continue
        if os.path.exists(abs_p):
            resolved.append(abs_p)
    if not resolved:
        return JSONResponse(status_code=400, content={"error": "所选路径无效"})

    # 去重：父目录已选中的，其子项不再重复打包（排序后父在前）
    resolved = sorted(set(resolved))
    kept = []
    for pth in resolved:
        if any(pth == k or pth.startswith(k.rstrip(os.sep) + os.sep) for k in kept):
            continue
        kept.append(pth)

    import zipfile

    max_files = config["zip"].get("max_files", 5000)
    max_bytes = config["zip"].get("max_bytes", 2 * 1024 ** 3)
    fd, tmp_path = tempfile.mkstemp(suffix=".zip", dir=config["cache_dir"])
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            count = 0
            total = 0
            for target in kept:
                if os.path.isfile(target):
                    size = os.path.getsize(target)
                    if count >= max_files or total + size > max_bytes:
                        return JSONResponse(status_code=413, content={"error": "所选内容超出打包限制"})
                    zf.write(target, os.path.relpath(target, root))
                    count += 1
                    total += size
                    continue
                for dirpath, dirnames, filenames in os.walk(target):
                    dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                    for name in filenames:
                        if name.startswith("."):
                            continue
                        full = os.path.join(dirpath, name)
                        try:
                            size = os.path.getsize(full)
                        except OSError:
                            continue
                        if count >= max_files or total + size > max_bytes:
                            return JSONResponse(status_code=413, content={"error": "所选内容超出打包限制"})
                        zf.write(full, os.path.relpath(full, root))
                        count += 1
                        total += size
        stamp = time.strftime("%Y%m%d-%H%M")
        return FileResponse(
            tmp_path,
            media_type="application/zip",
            filename=f"remote-works-{stamp}.zip",
            background=BackgroundTask(_remove_file, tmp_path),
        )
    except Exception as exc:
        _remove_file(tmp_path)
        logger.exception("Selected zip failed")
        return JSONResponse(status_code=500, content={"error": f"打包失败: {exc}"})


def _remove_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Search / Recent
# ---------------------------------------------------------------------------

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = Query(""), mode: str = Query("name")):
    """文件名检索（mode=name）或正文全文检索（mode=content）。"""
    q = q.strip()
    mode = "content" if mode == "content" else "name"
    if not q:
        results = []
    elif mode == "content":
        results = search_content(config["root_dir"], q)
    else:
        results = search_files(config["root_dir"], q)
    return templates.TemplateResponse(
        "search.html",
        _context(request, query=q, mode=mode, results=results,
                 title=f"搜索：{q or '全部'}"),
    )


@app.get("/recent", response_class=HTMLResponse)
async def recent_page(request: Request, limit: int = Query(50, le=200)):
    files = get_recent_files(config["root_dir"], limit=limit)
    return templates.TemplateResponse(
        "recent.html",
        _context(request, files=files, title="最近更新"),
    )


@app.get("/api/search")
async def api_search(request: Request, q: str = Query(..., min_length=1), mode: str = Query("name")):
    q = q.strip()
    if mode == "content":
        return {"mode": "content", "results": search_content(config["root_dir"], q)}
    return {"mode": "name", "results": search_files(config["root_dir"], q)}


@app.get("/thumb/{rel_path:path}")
async def thumbnail(request: Request, rel_path: str, w: int = Query(360, ge=64, le=1280)):
    """按需生成并缓存图片缩略图（磁盘缓存，借鉴 filebrowser/copyparty 的网格视图）。"""
    abs_path, err_resp = _resolve_or_error(request, rel_path, need_file=True)
    if err_resp is not None:
        return err_resp
    if os.path.splitext(abs_path)[1].lower() not in THUMB_EXTS:
        raise HTTPException(status_code=400, detail="该文件不是可生成缩略图的图片")
    try:
        st = os.stat(abs_path)
    except OSError:
        raise HTTPException(status_code=404, detail="文件不存在")
    thumbs_dir = os.path.join(config["cache_dir"], "thumbs")
    os.makedirs(thumbs_dir, exist_ok=True)
    key = hashlib.sha1(
        f"{abs_path}|{st.st_mtime_ns}|{st.st_size}|{w}".encode("utf-8")
    ).hexdigest()[:32]
    out_path = os.path.join(thumbs_dir, key + ".jpg")
    if not os.path.exists(out_path):
        try:
            from PIL import Image, ImageOps

            with Image.open(abs_path) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((w, w * 4))
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(out_path, "JPEG", quality=82, optimize=True)
        except Exception as exc:  # 损坏/不支持格式
            logger.warning("thumbnail failed for %s: %s", abs_path, exc)
            raise HTTPException(status_code=415, detail="无法生成缩略图")
    return FileResponse(
        out_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@app.get("/api/recent")
async def api_recent(request: Request, limit: int = Query(30, le=200)):
    return {"files": get_recent_files(config["root_dir"], limit=limit)}


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

async def _generate_pdf_response(request: Request, rel_path: str, force: bool = False,
                                inline: bool = False):
    abs_path, err_resp = _resolve_or_error(request, rel_path, need_file=True)
    if err_resp is not None:
        return err_resp
    info = get_file_info(abs_path, config["root_dir"])
    if info is None or info["type"] != "markdown":
        return JSONResponse(status_code=400, content={"error": "仅支持 Markdown 文件导出 PDF"})

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return JSONResponse(status_code=500, content={"error": f"读取文件失败: {e}"})

    if force:
        invalidate_pdf_cache(abs_path, text)

    t_pdf = time.time()
    try:
        html_body, _, has_mermaid = render_markdown(text, abs_path)
        has_math = "$$" in text or "$" in text or "\\[" in text or "\\(" in text
        full_html = build_pdf_html(html_body, info["name"], has_mermaid, has_math)
        pdf_path = await generate_pdf(abs_path, text, html_body, full_html)
    except Exception as e:
        logger.exception("PDF generation failed: %s", rel_path)
        return JSONResponse(status_code=500, content={"error": f"PDF 生成失败: {e}"})

    if pdf_path is None:
        return JSONResponse(
            status_code=500,
            content={
                "error": "PDF 生成失败：Chromium 不可用或渲染超时",
                "hint": "请检查服务端 Playwright Chromium 安装：python3 -m playwright install chromium",
            },
        )

    filename = os.path.splitext(info["name"])[0] + ".pdf"
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    # 默认 attachment（按钮语义是「下载 PDF」）：手机浏览器对内嵌 PDF 的渲染常常长时间转圈；
    # 需要站内预览时用 ?inline=1。
    disposition = "inline" if inline else "attachment"
    size_kb = os.path.getsize(pdf_path) // 1024 if os.path.exists(pdf_path) else 0
    logger.info(
        "PDF %s: %.2fs, %sKB, %s, %s",
        rel_path, time.time() - t_pdf, size_kb, disposition,
        "强制重算" if force else "正常",
    )
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=filename,
        headers={
            "Content-Disposition": (
                f"{disposition}; filename=\"{ascii_name}\"; "
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/pdf/{rel_path:path}/regenerate")
async def pdf_regenerate(request: Request, rel_path: str):
    return await _generate_pdf_response(request, rel_path, force=True)


@app.get("/api/pdf/{rel_path:path}")
async def pdf_get(request: Request, rel_path: str, inline: int = Query(0)):
    return await _generate_pdf_response(request, rel_path, force=False, inline=bool(inline))


@app.post("/api/pdf/{rel_path:path}")
async def pdf_post(request: Request, rel_path: str):
    return await _generate_pdf_response(request, rel_path, force=False)


# ---------------------------------------------------------------------------
# Status / health
# ---------------------------------------------------------------------------

@app.get("/favicon.ico")
async def favicon():
    """浏览器默认请求 /favicon.ico；此前无路由导致 404，这里指向站内图标。"""
    return RedirectResponse(url="/static/favicon.svg", status_code=307)


@app.get("/api/health")
async def health():
    root = config["root_dir"]
    return {
        "status": "ok",
        "version": "2.0.0",
        "uptime_seconds": int(time.time() - STARTED_AT),
        "root_exists": os.path.isdir(root),
    }


@app.get("/api/status")
async def status():
    root = config["root_dir"]
    info = {"root_dir": root, "exists": os.path.isdir(root)}
    if os.path.isdir(root):
        entries = list_directory(root, root)
        info["top_level_count"] = len(entries)
    pdf_dir = os.path.join(config["cache_dir"], "pdf")
    info["cached_pdf_count"] = len(os.listdir(pdf_dir)) if os.path.isdir(pdf_dir) else 0
    return info


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return _error_response(request, exc.status_code, "请求错误", str(exc.detail))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return _error_response(request, 500, "服务器内部错误", str(exc))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
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
