"""PDF generation from rendered Markdown HTML using Playwright."""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

import yaml


class PDFGenerator:
    """Generates PDF from HTML using Playwright (Chromium)."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        pdf_cfg = config.get("pdf", {})
        self.enabled = pdf_cfg.get("enabled", True)
        self.cache = pdf_cfg.get("cache", True)
        self.page_format = pdf_cfg.get("page_format", "A4")

        paths = config.get("paths", {})
        self.cache_dir = Path(
            os.path.expanduser(paths.get("cache_dir", "~/.cache/remote_works_server"))
        )
        self.pdf_cache_dir = self.cache_dir / "pdf"
        self.pdf_cache_dir.mkdir(parents=True, exist_ok=True)

        self._browser = None

    async def _get_browser(self):
        """Lazy-load Playwright browser."""
        if self._browser is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
        return self._browser

    def get_cache_key(self, md_path: str, mtime: float) -> str:
        """Generate a cache key for a markdown file."""
        raw = f"{md_path}:{mtime}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get_cached_pdf(self, cache_key: str) -> Optional[bytes]:
        """Get cached PDF if it exists."""
        cache_path = self.pdf_cache_dir / f"{cache_key}.pdf"
        if cache_path.exists():
            return cache_path.read_bytes()
        return None

    def save_cached_pdf(self, cache_key: str, pdf_data: bytes):
        """Cache a generated PDF."""
        cache_path = self.pdf_cache_dir / f"{cache_key}.pdf"
        cache_path.write_bytes(pdf_data)

    async def generate_pdf(
        self, html_content: str, md_path: str, mtime: float
    ) -> Optional[bytes]:
        """Generate PDF from HTML content using Playwright.

        Args:
            html_content: Full HTML page content
            md_path: Original markdown file path (for cache key)
            mtime: Modification time of the markdown file

        Returns:
            PDF bytes or None on failure
        """
        if not self.enabled:
            return None

        cache_key = self.get_cache_key(md_path, mtime)

        # Check cache
        if self.cache:
            cached = self.get_cached_pdf(cache_key)
            if cached is not None:
                return cached

        try:
            browser = await self._get_browser()
            page = await browser.new_page()

            # Convert /download/ paths to file:// URLs for local rendering
            root_dir = self._get_root_dir()
            if root_dir:
                import re as _re
                root = os.path.abspath(root_dir)

                def _to_file_url(m):
                    rel_path = m.group(1)
                    abs_path = os.path.join(root, rel_path)
                    if os.path.exists(abs_path):
                        return f'src="file://{abs_path}"'
                    return m.group(0)

                html_content = _re.sub(
                    r'src="/download/([^"]+)"',
                    _to_file_url,
                    html_content,
                )

            # Write HTML to temp file so file:// images resolve correctly
            import tempfile
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.html', delete=False, encoding='utf-8'
            ) as f:
                f.write(html_content)
                temp_path = f.name

            # Set viewport for consistent rendering
            await page.set_viewport_size({"width": 1200, "height": 800})

            # Load HTML from file:// so file:// image URLs are allowed
            await page.goto(f"file://{temp_path}", wait_until="networkidle")

            # Wait for MathJax to finish rendering
            try:
                await page.wait_for_function(
                    "() => typeof MathJax === 'undefined' || "
                    "document.querySelectorAll('mjx-container, .MathJax').length > 0 || "
                    "document.querySelectorAll('[class*=\"math\"]').length === 0",
                    timeout=10000,
                )
            except Exception:
                pass

            # Wait for Mermaid to render
            try:
                await page.wait_for_function(
                    "() => {"
                    "  const mermaids = document.querySelectorAll('pre.mermaid');"
                    "  return mermaids.length === 0 || "
                    "    Array.from(mermaids).every(m => m.querySelector('svg'));"
                    "}",
                    timeout=15000,
                )
            except Exception:
                pass

            # Extra wait to ensure rendering is complete
            await asyncio.sleep(2)

            # Generate PDF
            pdf_data = await page.pdf(
                format=self.page_format,
                print_background=True,
                margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
                prefer_css_page_size=True,
            )

            await page.close()

            # Clean up temp file
            try:
                os.unlink(temp_path)
            except Exception:
                pass

            # Cache the result
            if self.cache:
                self.save_cached_pdf(cache_key, pdf_data)

            return pdf_data

        except Exception as e:
            print(f"PDF generation failed: {e}")
            return None

    def _get_root_dir(self) -> str:
        """Get the root directory from config."""
        config_path = Path(__file__).parent / "config.yaml"
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            paths = config.get("paths", {})
            return os.path.expanduser(paths.get("root_dir", "~/remote_works"))
        except Exception:
            return os.path.expanduser("~/remote_works")

    def invalidate_cache(self, md_path: str):
        """Remove cached PDFs for a given markdown path."""
        # We don't know the exact mtime, so we can't invalidate by path alone.
        # Cache cleanup based on age is done separately.
        pass

    async def cleanup(self):
        """Close browser instance."""
        if self._browser:
            await self._browser.close()
            self._browser = None


# Singleton
pdf_generator: Optional[PDFGenerator] = None


def get_pdf_generator() -> PDFGenerator:
    global pdf_generator
    if pdf_generator is None:
        pdf_generator = PDFGenerator()
    return pdf_generator
