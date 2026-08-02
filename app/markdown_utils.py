"""Markdown rendering with LaTeX, Mermaid, and full GitHub-style features."""
from __future__ import annotations

import os
import re
import html as html_module
from typing import Optional

from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock
from mdit_py_plugins import (
    admon,
    deflist,
    footnote,
    tasklists,
)
from mdit_py_plugins.attrs import attrs_block_plugin, attrs_plugin

from app.config import config


# ---- Custom fenced-code renderer to handle Mermaid blocks ----
def _mermaid_replacer(match):
    """Wrap a Mermaid code block in a <div class='mermaid'> for client-side rendering."""
    code = match.group(1)
    escaped = html_module.escape(code)
    return f'<pre class="mermaid-container"><div class="mermaid">{escaped}</div></pre>\n'


def build_md():
    """Build and return a configured MarkdownIt instance."""
    md = (
        MarkdownIt(
            "gfm-like",
            options_update={
                "highlight": None,  # We use pymdownx-style highlight via HTML
                "linkify": True,
                "typographer": True,
                "breaks": True,
                "html": True,
            },
        )
        .enable("table")
        .enable("strikethrough")
        .use(admon.admon_plugin)
        .use(deflist.deflist_plugin)
        .use(footnote.footnote_plugin)
        .use(tasklists.tasklists_plugin)
    )

    # Add attrs support
    md.use(attrs_block_plugin)
    md.use(attrs_plugin)

    # Add custom fence renderer for Mermaid
    default_fence = md.renderer.rules["fence"]

    def _fence(tokens, idx, options, env):
        token = tokens[idx]
        info = token.info.strip() if token.info else ""
        # LaTeX block via ```math or ```latex
        if info in ("math", "latex", "katex"):
            content = html_module.escape(token.content.strip())
            return f'<div class="katex-block">$${content}$$</div>\n'
        # Mermaid
        if info == "mermaid":
            escaped = html_module.escape(token.content)
            return f'<pre class="mermaid-container"><div class="mermaid">{escaped}</div></pre>\n'
        # Default: use default_fence or our own code block
        if default_fence:
            return default_fence(tokens, idx, options, env)
        escaped = html_module.escape(token.content)
        lang = f' class="language-{html_module.escape(info)}"' if info else ""
        return f'<pre><code{lang}>{escaped}</code></pre>\n'

    md.renderer.rules["fence"] = _fence

    # Custom inline code renderer for LaTeX inline: $...$
    # We need to handle this BEFORE markdown-it processes $ as punctuation
    # Strategy: pre-process the markdown to protect inline math
    return md


def preprocess_math(text: str) -> str:
    """Pre-process markdown to protect LaTeX expressions from markdown-it processing.

    Inline math $...$ and block math $$...$$ are wrapped in custom placeholders
    that survive markdown processing.
    """
    # Block math: $$...$$ -> replace with custom fenced block
    # We'll convert to ```math blocks first
    def _block_math(m):
        content = m.group(1).strip()
        return f"```math\n{content}\n```\n"

    text = re.sub(r'\$\$\s*\n(.*?)\n\s*\$\$', _block_math, text, flags=re.DOTALL)
    text = re.sub(r'\$\$(.+?)\$\$', _block_math, text, flags=re.DOTALL)

    # Inline math: $...$ -> protect with special marker
    # Only match $ that are not part of $$ and have proper content
    # This is a rough filter; KaTeX JS on client side handles the real rendering
    def _inline_math(m):
        content = m.group(1)
        # Don't match if it looks like a number with $ signs
        if re.match(r'^\d+$', content):
            return m.group(0)
        return f'<span class="katex-inline">${content}$</span>'

    # Raw inline math - careful not to match $$ or stray $ signs
    text = re.sub(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)', _inline_math, text)

    return text


def render_markdown(text: str, file_path: str = "") -> str:
    """Render Markdown text to HTML with LaTeX and Mermaid support.

    Args:
        text: Raw markdown text.
        file_path: Path to the original .md file (for resolving relative image paths).

    Returns:
        HTML string.
    """
    # Pre-process LaTeX
    text = preprocess_math(text)

    # Resolve relative image paths
    if file_path:
        abs_dir = os.path.dirname(os.path.abspath(file_path))
        root_dir = config["root_dir"]

        def _fix_img_src(m):
            src = m.group(1)
            if src.startswith(("http://", "https://", "/", "data:")):
                return m.group(0)
            # Try to resolve relative to the md file
            possible = os.path.join(abs_dir, src)
            if os.path.exists(possible):
                # Create a download link for the image
                rel = os.path.relpath(possible, root_dir)
                return f'<img src="/api/files/{rel}" alt="{m.group(2)}" />'
            return m.group(0)

        text = re.sub(r'<img\s+src="([^"]+)"\s+alt="([^"]*)"\s*/?>', _fix_img_src, text)
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', lambda m: f'<img src="/api/files/{os.path.relpath(os.path.join(abs_dir, m.group(2)), root_dir)}" alt="{m.group(1)}" />', text)

    # Render with markdown-it
    md = build_md()
    html_body = md.render(text)

    # Add Mermaid initialization script if there's any mermaid content
    has_mermaid = 'class="mermaid"' in html_body

    # Build full HTML
    toc_html = _build_toc(html_body) if config["markdown"]["toc"] else ""

    return html_body, toc_html, has_mermaid


def _build_toc(html_body: str) -> str:
    """Extract headings and build a table of contents."""
    headings = re.findall(r'<h([2-3])\s+id="([^"]*)"[^>]*>(.*?)</h\1>', html_body)
    if not headings:
        return ""

    items = []
    for level, hid, title in headings:
        indent = "  " * (int(level) - 2)
        clean_title = re.sub(r'<[^>]+>', '', title)
        items.append(f'{indent}<li><a href="#{hid}">{clean_title}</a></li>')

    toc = f"""
    <nav id="toc" class="toc">
      <h3>📑 Table of Contents</h3>
      <ul>
        {''.join(items)}
      </ul>
    </nav>
    """
    return toc
