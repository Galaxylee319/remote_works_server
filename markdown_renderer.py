"""Markdown to HTML rendering with GFM, LaTeX, Mermaid, code highlighting."""

import os
import re
from pathlib import Path
from typing import List, Optional

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.anchors import anchors_plugin
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound


def _highlight_code(code, lang):
    if not lang:
        lang = "text"
    try:
        lexer = get_lexer_by_name(lang, stripall=True)
    except ClassNotFound:
        lexer = get_lexer_by_name("text", stripall=True)
    return highlight(code, lexer, HtmlFormatter(style="monokai"))


def _create_parser():
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
    md.use(anchors_plugin)
    for kind in ["note", "warning", "tip", "danger", "info", "success"]:
        md.use(container_plugin, name=kind, marker="!")
    return md


def _render_fence(tokens, idx, options, env):
    token = tokens[idx]
    lang = token.info.strip() if token.info else ""
    content = token.content
    if lang == "mermaid":
        return '<pre class="mermaid">%s</pre>' % content
    highlighted = _highlight_code(content, lang or "text")
    return '<div class="code-block-wrapper">%s</div>' % highlighted


_parser = None


def get_parser():
    global _parser
    if _parser is None:
        _parser = _create_parser()
        _parser.renderer.rules["fence"] = _render_fence
    return _parser


def render_markdown(md_content, base_path=None):
    """Render markdown to HTML with LaTeX math protection.

    Strategy:
    1. Protect $$...$$ blocks and $...$ inline math from markdown parsing
    2. Parse markdown normally
    3. Restore math as MathJax-compatible \\(...\\) and \\[...\\] format
    """
    # Step 1: Protect $$...$$ block math
    block_math = []

    def _protect_block(m):
        block_math.append(m.group(1).strip())
        return "%%MATHBLOCK%d%%" % (len(block_math) - 1)

    protected = re.sub(
        r"\$\$\s*(.+?)\s*\$\$",
        _protect_block,
        md_content,
        flags=re.DOTALL,
    )

    # Step 2: Protect $...$ inline math (single $, not preceded/followed by $)
    inline_math = []

    def _protect_inline(m):
        inner = m.group(1)
        if inner.startswith("%%MATH"):
            return m.group(0)
        inline_math.append(inner)
        return "%%MATHINLINE%d%%" % (len(inline_math) - 1)

    protected = re.sub(
        r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)",
        _protect_inline,
        protected,
    )

    # Step 3: Render markdown
    parser = get_parser()
    html = parser.render(protected)

    # Step 4: Restore block math as \[ ... \]
    for i, formula in enumerate(block_math):
        placeholder = "%%MATHBLOCK%d%%" % i
        replacement = '<div class="math-block">\\[%s\\]</div>' % formula
        html = html.replace(placeholder, replacement)

    # Step 5: Restore inline math as \( ... \)
    for i, formula in enumerate(inline_math):
        placeholder = "%%MATHINLINE%d%%" % i
        replacement = '<span class="math-inline">\\(%s\\)</span>' % formula
        html = html.replace(placeholder, replacement)

    # Step 6: Wrap tables in scrollable containers for mobile
    html = re.sub(
        r'(<table>.*?</table>)',
        r'<div class="table-wrapper">\1</div>',
        html,
        flags=re.DOTALL,
    )

    # Step 7: Resolve relative image paths to /download/ URLs
    if base_path:
        base_dir = os.path.dirname(base_path)

        def _fix_img_src(m):
            src = m.group(1)
            alt = m.group(2) if m.lastindex >= 2 else ""
            # Skip absolute URLs, data URIs, and already-absolute paths
            if src.startswith(("http://", "https://", "/", "data:")):
                return m.group(0)
            # Resolve relative to the markdown file
            resolved = os.path.normpath(os.path.join(base_dir, src))
            return '<img src="/download/%s" alt="%s"' % (resolved, alt)

        html = re.sub(
            r'<img\s+src="([^"]+)"(?:\s+alt="([^"]*)")?',
            _fix_img_src,
            html,
        )

    return html
