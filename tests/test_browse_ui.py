#!/usr/bin/env python3
"""浏览页 UI 回归测试（Playwright 真实浏览器）。

覆盖历史 bug：列表视图下网格视图仍然显示（CSS 作者样式的 display 覆盖了
浏览器默认的 [hidden]{display:none}）。

用法：
    # 1) 另起一个免认证实例（或用已登录的会话）
    RWS_CONFIG=/tmp/rws_ui.yaml ./venv/bin/python3 run.py &
    # 2) 运行
    ./venv/bin/python3 tests/test_browse_ui.py [base_url] [path]
    默认 base_url=http://127.0.0.1:8099 path=/browse/figures_paper/
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
PATH = sys.argv[2] if len(sys.argv) > 2 else "/browse/figures_paper/"
fails = []


def check(name, got, want):
    ok = got == want
    print(f"  {'✔' if ok else '✘'} {name}: {got} (期望 {want})")
    if not ok:
        fails.append(name)


def visible(page, sel):
    return page.eval_on_selector(sel, "el => !!(el.offsetParent !== null || el.getClientRects().length)")


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 420, "height": 900})
    page.goto(BASE + PATH, wait_until="networkidle")

    print("【默认：列表视图】")
    check("列表容器可见", visible(page, "#file-list"), True)
    check("网格容器隐藏", visible(page, "#grid-view"), False)

    print("【切换到网格】")
    page.click("#view-toggle")
    page.wait_for_timeout(600)
    check("列表容器隐藏", visible(page, "#file-list"), False)
    check("网格容器可见", visible(page, "#grid-view"), True)
    n = page.eval_on_selector_all("#grid-view .grid-item", "els => els.length")
    check("网格条目数>0", n > 0, True)
    if n:
        loaded = page.eval_on_selector(
            "#grid-view img.grid-thumb",
            "el => el.complete && el.naturalWidth > 0",
        )
        check("首张缩略图加载成功", loaded, True)

    print("【刷新保持偏好】")
    page.reload(wait_until="networkidle")
    check("网格仍为当前视图", visible(page, "#grid-view"), True)

    print("【切回列表】")
    page.click("#view-toggle")
    page.wait_for_timeout(400)
    check("列表容器可见", visible(page, "#file-list"), True)
    check("网格容器隐藏", visible(page, "#grid-view"), False)

    browser.close()

print("\n结果:", "全部通过 ✔" if not fails else f"失败 {len(fails)} 项 ✘ {fails}")
sys.exit(0 if not fails else 1)
