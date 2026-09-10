"""Markdown rendering: GFM + LaTeX protection + Mermaid + code highlight + TOC."""
from __future__ import annotations

import html
import os
import re
from typing import Optional, Tuple
from urllib.parse import quote

from markdown_it import MarkdownIt
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from app.config import config


def _highlight_code(code: str, lang: str) -> str:
    if not lang:
        lang = "text"
    try:
        lexer = get_lexer_by_name(lang, stripall=True)
    except ClassNotFound:
        lexer = get_lexer_by_name("text", stripall=True)
    return highlight(code, lexer, HtmlFormatter(style="monokai"))


def _fence_rule(tokens, idx, options, env):
    token = tokens[idx]
    lang = token.info.strip() if token.info else ""
    content = token.content
    if lang == "mermaid":
        escaped = html.escape(content)
        return '<pre class="mermaid-container"><div class="mermaid">%s</div></pre>' % escaped
    highlighted = _highlight_code(content, lang or "text")
    return '<div class="code-block-wrapper">%s</div>' % highlighted


def _create_parser() -> MarkdownIt:
    md = MarkdownIt(
        "gfm-like",
        {
            "html": True,
            "linkify": True,
            "typographer": True,
            "breaks": True,
            "highlight": _highlight_code,
        },
    )
    md.use(footnote_plugin)
    md.use(tasklists_plugin)
    md.use(deflist_plugin)
    for kind in ("note", "warning", "tip", "danger", "info", "success"):
        md.use(container_plugin, name=kind, marker="!")
    md.renderer.rules["fence"] = _fence_rule
    return md


_parser: Optional[MarkdownIt] = None


def get_parser() -> MarkdownIt:
    global _parser
    if _parser is None:
        _parser = _create_parser()
    return _parser


def _protect_math(text: str) -> Tuple[str, list, list]:
    """Extract ``$$...$$``/``$...$`` and ``\\[...\\]``/``\\(...\\)`` math so markdown-it can't mangle it."""
    block_math = []
    inline_math = []

    def _protect_block(m):
        block_math.append(m.group(1).strip())
        return "%%MATHBLOCK%d%%" % (len(block_math) - 1)

    # $$ ... $$ display math
    protected = re.sub(
        r"\$\$\s*(.+?)\s*\$\$",
        _protect_block,
        text,
        flags=re.DOTALL,
    )

    # \[ ... \] display math (LaTeX-style delimiters)
    protected = re.sub(
        r"\\\[\s*(.+?)\s*\\\]",
        _protect_block,
        protected,
        flags=re.DOTALL,
    )

    def _protect_inline(m):
        inner = m.group(1)
        if inner.startswith("%%MATH"):
            return m.group(0)
        inline_math.append(inner)
        return "%%MATHINLINE%d%%" % (len(inline_math) - 1)

    # $ ... $ inline math (single $, not preceded/followed by $)
    protected = re.sub(
        r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)",
        _protect_inline,
        protected,
    )

    # \( ... \) inline math (LaTeX-style delimiters)
    protected = re.sub(
        r"(?<!\\)\\\((.+?)\\\)",
        _protect_inline,
        protected,
        flags=re.DOTALL,
    )
    return protected, block_math, inline_math


def _restore_math(html_body: str, block_math: list, inline_math: list) -> str:
    for i, formula in enumerate(block_math):
        placeholder = "%%MATHBLOCK%d%%" % i
        safe_formula = html.escape(formula, quote=False)
        replacement = '<div class="math-block">\\[%s\\]</div>' % safe_formula
        html_body = html_body.replace(placeholder, replacement)
    for i, formula in enumerate(inline_math):
        placeholder = "%%MATHINLINE%d%%" % i
        safe_formula = html.escape(formula, quote=False)
        replacement = '<span class="math-inline">\\(%s\\)</span>' % safe_formula
        html_body = html_body.replace(placeholder, replacement)
    return html_body


def _fix_images(html_body: str, md_dir: str) -> str:
    """Rewrite relative image src to /api/files/<rel> inside the served root."""
    root_dir = config["root_dir"]

    def _candidate_rel(src: str):
        """Try md-relative, then root-relative (strip ../), return rel or None."""
        for candidate in (
            os.path.normpath(os.path.join(md_dir, src)),
            os.path.normpath(os.path.join(root_dir, re.sub(r"^(\.\./)+", "", src))),
        ):
            try:
                rel = os.path.relpath(candidate, root_dir)
            except ValueError:
                continue
            if rel.startswith("..") or os.path.isabs(rel):
                continue
            if os.path.exists(candidate):
                return rel
        return None

    def _fix(m):
        src = m.group(1)
        if src.startswith(("http://", "https://", "/", "data:", "#", "file:")):
            return m.group(0)
        rel = _candidate_rel(src)
        if rel is None:
            return m.group(0)
        return '<img src="/api/files/%s"' % quote(rel)

    return re.sub(r'<img\s+src="([^"]+)"', _fix, html_body)


def _attach_heading_ids(html_body: str):
    """Ensure h1-h3 have ids and build a TOC list."""
    toc_items = []
    used_ids = set()

    def _slugify(text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff\u3040-\u30ff-]+", "-", text.lower())
        slug = re.sub(r"-{2,}", "-", slug).strip("-")
        if not slug:
            slug = "section"
        base = slug
        n = 2
        while slug in used_ids:
            slug = "%s-%d" % (base, n)
            n += 1
        used_ids.add(slug)
        return slug

    def _replace(m):
        level = int(m.group(1))
        inner = m.group(3)
        text = re.sub(r"<[^>]+>", "", inner)
        text = html.unescape(text)
        hid = m.group(2) or _slugify(text)
        if level <= 3:
            toc_items.append((level, hid, text))
        return '<h%d id="%s">%s</h%d>' % (level, hid, inner, level)

    pattern = re.compile(
        r"<h([1-6])(?:\s+id=\"([^\"]*)\")?[^>]*>(.*?)</h\1>",
        flags=re.DOTALL,
    )
    html_body = pattern.sub(_replace, html_body)
    return html_body, toc_items


def _build_toc_html(toc_items) -> str:
    if not toc_items:
        return ""
    lines = ['<nav class="toc-nav"><ul>']
    for level, hid, title in toc_items:
        indent = "  " * max(0, level - 1)
        lines.append(
            '%s<li class="toc-l%d"><a href="#%s">%s</a></li>'
            % (indent, level, hid, html.escape(title))
        )
    lines.append("</ul></nav>")
    return "\n".join(lines)


def render_markdown(
    text: str, file_path: str = ""
) -> Tuple[str, str, bool]:
    """Render markdown to (html_body, toc_html, has_mermaid)."""
    protected, block_math, inline_math = _protect_math(text)

    parser = get_parser()
    html_body = parser.render(protected)

    html_body = _restore_math(html_body, block_math, inline_math)

    # Wrap tables for horizontal scrolling on mobile.
    html_body = re.sub(
        r"(<table>.*?</table>)",
        r'<div class="table-wrapper">\1</div>',
        html_body,
        flags=re.DOTALL,
    )

    if file_path:
        md_dir = os.path.dirname(os.path.abspath(file_path))
        html_body = _fix_images(html_body, md_dir)

    has_mermaid = 'class="mermaid"' in html_body
    html_body, toc_items = _attach_heading_ids(html_body)
    toc_html = _build_toc_html(toc_items) if config["markdown"].get("toc", True) else ""

    return html_body, toc_html, has_mermaid
