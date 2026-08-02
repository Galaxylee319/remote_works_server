"""PDF generation using Playwright (headless Chromium HTML→PDF)."""
from __future__ import annotations

import html as html_module
import os
import hashlib
import asyncio
from typing import Optional

from app.config import config


def _cache_key(file_path: str, text: str) -> str:
    """Generate a cache key based on file path and content hash."""
    h = hashlib.sha256()
    h.update(file_path.encode("utf-8"))
    h.update(text.encode("utf-8"))
    return h.hexdigest()[:32]


def get_cached_pdf(file_path: str, text: str) -> Optional[str]:
    """Return cached PDF path if valid, else None."""
    if not config["pdf"]["cache"]:
        return None

    key = _cache_key(file_path, text)
    cache_dir = os.path.join(config["cache_dir"], "pdf")
    pdf_path = os.path.join(cache_dir, f"{key}.pdf")

    if os.path.exists(pdf_path):
        return pdf_path
    return None


async def generate_pdf(file_path: str, text: str, html_body: str, full_html: str) -> Optional[str]:
    """Generate PDF from rendered HTML using Playwright.

    Args:
        file_path: Original markdown file path (for cache key).
        text: Raw markdown text (for cache key).
        html_body: The rendered HTML body content.
        full_html: Complete HTML page with styles and scripts.

    Returns:
        Path to generated PDF file, or None on failure.
    """
    key = _cache_key(file_path, text)
    cache_dir = os.path.join(config["cache_dir"], "pdf")
    os.makedirs(cache_dir, exist_ok=True)
    pdf_path = os.path.join(cache_dir, f"{key}.pdf")

    # Check cache
    if config["pdf"]["cache"] and os.path.exists(pdf_path):
        return pdf_path

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 1024},
                device_scale_factor=2,
            )
            page = await context.new_page()

            # Set content and wait for rendering
            await page.set_content(full_html, wait_until="networkidle")

            # Wait for MathJax/KaTeX and Mermaid to render
            try:
                # Wait for Mermaid if present
                has_mermaid = 'class="mermaid"' in full_html
                if has_mermaid:
                    await page.wait_for_function(
                        "() => document.querySelectorAll('.mermaid svg').length > 0",
                        timeout=15000,
                    )
                    await asyncio.sleep(0.5)
            except Exception:
                pass  # Continue even if Mermaid doesn't render fully

            try:
                # Wait for KaTeX
                if 'class="katex"' in full_html or 'class="katex-inline"' in full_html:
                    await page.wait_for_function(
                        "() => document.querySelectorAll('.katex-html, .katex').length > 0",
                        timeout=10000,
                    )
            except Exception:
                pass

            # Generate PDF
            await page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
            )

            await browser.close()

        return pdf_path if os.path.exists(pdf_path) else None

    except Exception as e:
        print(f"[PDF ERROR] {e}")
        return None


def build_pdf_html(html_body: str, title: str, with_mermaid: bool, with_math: bool) -> str:
    """Build a complete HTML page suitable for PDF printing."""
    mermaid_script = ""
    if with_mermaid:
        mermaid_script = """
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        <script>mermaid.initialize({startOnLoad:true, theme:'default', logLevel:1});</script>
        """

    math_script = ""
    if with_math:
        math_script = """
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.css">
        <script src="https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/katex@0.16/dist/contrib/auto-render.min.js"></script>
        <script>
        document.addEventListener('DOMContentLoaded', function() {
          renderMathInElement(document.body, {
            delimiters: [
              {left: '$$', right: '$$', display: true},
              {left: '$', right: '$', display: false}
            ],
            throwOnError: false
          });
        });
        </script>
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
    font-size: 13pt;
    line-height: 1.7;
    color: #1a1a1a;
    max-width: 100%;
    padding: 0;
    margin: 0;
  }}
  h1 {{ font-size: 1.6em; margin-top: 1.2em; }}
  h2 {{ font-size: 1.3em; border-bottom: 1px solid #ddd; padding-bottom: 0.3em; }}
  h3 {{ font-size: 1.15em; }}
  code {{ background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 0.9em; }}
  pre {{ background: #f5f5f5; padding: 12px; border-radius: 5px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ccc; padding: 8px 10px; text-align: left; }}
  th {{ background: #f0f0f0; }}
  img {{ max-width: 100%; height: auto; }}
  blockquote {{ border-left: 4px solid #ccc; margin: 1em 0; padding: 0.5em 1em; color: #555; }}
  .mermaid svg {{ max-width: 100%; height: auto; }}
  .katex-block {{ text-align: center; margin: 1em 0; overflow-x: auto; }}
  .admonition {{ padding: 10px 15px; margin: 1em 0; border-left: 4px solid #2196F3; background: #f5f9ff; }}
  .task-list-item {{ list-style: none; }}
  .footnotes {{ font-size: 0.9em; color: #666; border-top: 1px solid #ddd; margin-top: 2em; }}
  @media print {{ .no-print {{ display: none; }} }}
</style>
{mermaid_script}
{math_script}
</head>
<body>
{html_body}
</body>
</html>"""
