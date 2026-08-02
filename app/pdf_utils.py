"""PDF generation: Playwright/Chromium HTML->PDF with content-hash cache (v2)."""
from __future__ import annotations

import asyncio
import hashlib
import html as html_module
import os
import re
from typing import Optional

from app.config import config


_browser = None
_playwright = None
_browser_lock: Optional[asyncio.Lock] = None


def _cache_key(file_path: str, text: str) -> str:
    h = hashlib.sha256()
    h.update(file_path.encode("utf-8"))
    h.update(text.encode("utf-8"))
    return h.hexdigest()[:32]


def _cache_path(key: str) -> str:
    return os.path.join(config["cache_dir"], "pdf", f"{key}.pdf")


def get_cached_pdf(file_path: str, text: str) -> Optional[str]:
    """Return cached PDF path if present and cache is enabled."""
    if not config["pdf"].get("cache", True):
        return None
    path = _cache_path(_cache_key(file_path, text))
    return path if os.path.exists(path) else None


def invalidate_pdf_cache(file_path: str, text: str) -> None:
    path = _cache_path(_cache_key(file_path, text))
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


async def _get_browser():
    """Lazily launch a single Chromium instance (guarded by a lock)."""
    global _browser, _playwright, _browser_lock
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    async with _browser_lock:
        if _browser is None:
            from playwright.async_api import async_playwright

            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                ],
            )
    return _browser


async def close_browser() -> None:
    """Close the shared browser on shutdown."""
    global _browser, _playwright
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None


def _localize_image_urls(full_html: str) -> str:
    """Rewrite /api/files/<rel> to file:// URLs so headless Chromium can load them."""
    root_dir = config["root_dir"]

    def _fix(m):
        rel = m.group(1)
        candidate = os.path.realpath(os.path.join(root_dir, rel.lstrip("/")))
        root_real = os.path.realpath(root_dir)
        if candidate != root_real and not candidate.startswith(root_real + os.sep):
            return m.group(0)
        if os.path.isfile(candidate):
            return 'src="file://%s"' % candidate
        return m.group(0)

    return re.sub(r'src="/api/files/([^"]+)"', _fix, full_html)


def build_pdf_html(html_body: str, title: str, with_mermaid: bool, with_math: bool) -> str:
    """Build a self-contained HTML document for PDF printing."""
    mermaid_script = ""
    if with_mermaid:
        mermaid_script = """
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        <script>mermaid.initialize({startOnLoad:true, theme:'default', logLevel:1});</script>
        """

    math_script = ""
    if with_math:
        math_script = """
        <script>
        window.MathJax = {
          tex: {
            inlineMath: [['$','$'], ['\\(','\\)']],
            displayMath: [['$$','$$'], ['\\[','\\]']],
            processEscapes: true
          },
          svg: { fontCache: 'global' }
        };
        </script>
        <script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
        """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html_module.escape(title)}</title>
<style>
  @page {{ size: A4; margin: 20mm 15mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a1a;
    max-width: 100%;
    margin: 0;
    padding: 0;
  }}
  h1 {{ font-size: 18pt; border-bottom: 2px solid #eee; padding-bottom: 6px; page-break-after: avoid; }}
  h2 {{ font-size: 14pt; border-bottom: 1px solid #eee; padding-bottom: 4px; page-break-after: avoid; }}
  h3 {{ font-size: 12pt; page-break-after: avoid; }}
  code {{ background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 0.9em; }}
  pre {{ background: #f5f5f5; padding: 12px; border-radius: 5px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; page-break-inside: avoid; }}
  pre code {{ background: none; padding: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; page-break-inside: avoid; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; font-size: 9.5pt; }}
  th {{ background: #f0f0f0; }}
  img {{ max-width: 100%; height: auto; page-break-inside: avoid; }}
  blockquote {{ border-left: 4px solid #ccc; margin: 1em 0; padding: 0.5em 1em; color: #555; background: #f9f9f9; }}
  .table-wrapper {{ overflow-x: auto; }}
  .mermaid svg {{ max-width: 100%; height: auto; }}
  .math-block {{ overflow-x: auto; margin: 1em 0; }}
  .admonition {{ padding: 10px 15px; margin: 1em 0; border-left: 4px solid #2196F3; background: #f5f9ff; }}
  .task-list-item {{ list-style: none; }}
  .footnotes {{ font-size: 0.9em; color: #666; border-top: 1px solid #ddd; margin-top: 2em; }}
</style>
{mermaid_script}
{math_script}
</head>
<body>
{html_body}
</body>
</html>"""


async def generate_pdf(
    file_path: str, text: str, html_body: str, full_html: str
) -> Optional[str]:
    """Generate a PDF for a markdown file. Returns PDF path or None."""
    if not config["pdf"].get("enabled", True):
        return None

    key = _cache_key(file_path, text)
    pdf_path = _cache_path(key)
    if config["pdf"].get("cache", True) and os.path.exists(pdf_path):
        return pdf_path

    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    full_html = _localize_image_urls(full_html)

    try:
        browser = await _get_browser()
        page = await browser.new_page()
        try:
            await page.set_content(full_html, wait_until="load", timeout=60000)

            if 'class="mermaid"' in full_html:
                try:
                    await page.wait_for_function(
                        "() => {"
                        "  const nodes = document.querySelectorAll('.mermaid');"
                        "  return nodes.length === 0 || Array.from(nodes).every(n => n.querySelector('svg'));"
                        "}",
                        timeout=20000,
                    )
                except Exception:
                    pass

            if "math-inline" in full_html or "math-block" in full_html:
                try:
                    await page.wait_for_function(
                        "() => typeof MathJax === 'undefined' || "
                        "document.querySelectorAll('mjx-container').length > 0 || "
                        "document.querySelectorAll('.math-block, .math-inline').length === 0",
                        timeout=20000,
                    )
                except Exception:
                    pass

            await page.pdf(
                path=pdf_path,
                format=config["pdf"].get("page_format", "A4"),
                print_background=True,
                margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
                prefer_css_page_size=True,
            )
        finally:
            await page.close()
    except Exception as e:
        print(f"[PDF ERROR] {e}")
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except OSError:
            pass
        return None

    return pdf_path if os.path.exists(pdf_path) else None

