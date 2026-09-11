#!/usr/bin/env python3
"""「同目录其他文档」区块的布局回归测试（Playwright，多视口）。

历史 bug：在 codex报告/ 这类**长英文文件名**目录下，翻页链接（Phase_VDT13C_…）
无法断行（下划线不是断行点）→ 撑破卡片、压住下方文档列表，观感「堆叠混乱」，
390px 视口下页面 scrollWidth 达 766（视口 390）。

覆盖：超长英文名 / 中文名 / 阶段报告目录 × 390/768/1280 三种视口，
检查「页面横向溢出、子元素越界、元素真实矩形相交」三类问题。

用法：
    RWS_CONFIG=/tmp/rws_test.yaml ./venv/bin/python3 run.py &
    ./venv/bin/python3 tests/test_docnav_layout.py [base_url]
"""
import sys
from urllib.parse import quote
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
CASES = [
    ("超长英文名（codex报告）", "/view/" + quote("codex报告/Phase_VDT13D_HighResolution_Visual_Geometry_Closure.md")),
    ("中文名（文档）", "/view/" + quote("文档/README.md")),
    ("阶段报告", "/view/" + quote("阶段报告/VDT10-fair-budget-information-selection/README.md")),
]
WIDTHS = (390, 768, 1280)
fails = []

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox"])
    for label, url in CASES:
        for w in WIDTHS:
            page = browser.new_context(viewport={"width": w, "height": 900}).new_page()
            page.goto(BASE + url, wait_until="networkidle")
            page.wait_for_timeout(600)
            r = page.evaluate(
                """() => {
                  const nav = document.querySelector('.doc-nav');
                  if (!nav) return {none: true};
                  const vw = document.documentElement.clientWidth;
                  const rect = e => e.getBoundingClientRect();
                  const boxes = [...document.querySelectorAll(
                      '.doc-nav-pager a,.doc-nav-pager span,.doc-nav-list li')].map(rect);
                  const overflow = boxes.filter(b => b.right > vw + 1 || b.left < -1).length;
                  const nb = rect(nav);
                  const outOfCard = boxes.filter(b => b.right > nb.right + 1).length;
                  let overlap = 0;
                  for (let i = 0; i < boxes.length; i++)
                    for (let j = i + 1; j < boxes.length; j++) {
                      const a = boxes[i], c = boxes[j];
                      if (!(a.right <= c.left || c.right <= a.left ||
                            a.bottom <= c.top || c.bottom <= a.top)) overlap++;
                    }
                  return {vw, scrollW: document.documentElement.scrollWidth,
                          overflow, outOfCard, overlap};
                }"""
            )
            page.close()
            if r.get("none"):
                print(f"  ○ {label} @{w}px 无该区块")
                continue
            ok = r["scrollW"] <= r["vw"] + 1 and r["overflow"] == 0 and r["outOfCard"] == 0 and r["overlap"] == 0
            print(f"  {'✔' if ok else '✘'} {label} @{w}px  页面宽 {r['scrollW']}/{r['vw']} | "
                  f"越界 {r['overflow']} | 超出卡片 {r['outOfCard']} | 重叠 {r['overlap']}")
            if not ok:
                fails.append(f"{label}@{w}")
    browser.close()

print("\n结果:", "全部通过 ✔" if not fails else f"失败 {fails} ✘")
sys.exit(0 if not fails else 1)
