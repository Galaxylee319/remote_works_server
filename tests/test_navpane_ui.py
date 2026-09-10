"""目录导航抽屉 UI 回归测试（Playwright，手机视口）。

覆盖：默认隐藏、点击展开、遮罩、层级渲染、当前分支高亮、无横向溢出、跳转、ESC 关闭。

用法：
    RWS_CONFIG=/tmp/rws_test.yaml ./venv/bin/python3 run.py &
    ./venv/bin/python3 tests/test_navpane_ui.py [base_url]
"""
import sys
from playwright.sync_api import sync_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
fails=[]
def check(n, got, want=True):
    ok = got == want; print(f"  {'✔' if ok else '✘'} {n}: {got}")
    if not ok: fails.append(n)
with sync_playwright() as p:
    b=p.chromium.launch(args=["--no-sandbox"]); ctx=b.new_context(viewport={"width":390,"height":844}); pg=ctx.new_page()
    pg.goto(f"{BASE}/browse/阶段报告/VDT10-fair-budget-information-selection/", wait_until="networkidle")
    off = pg.eval_on_selector("#navpane", "el => el.getBoundingClientRect().left >= window.innerWidth - 2")
    check("默认隐藏（在视口外）", off)
    pg.click("#navpane-toggle"); pg.wait_for_timeout(500)
    vis = pg.eval_on_selector("#navpane", "el => el.classList.contains('open') && el.getBoundingClientRect().left < window.innerWidth")
    check("点击后展开", vis)
    check("遮罩显示", pg.eval_on_selector("#navpane-backdrop", "el => el.hidden"), False)
    check("层级数=3", pg.eval_on_selector_all(".nav-level", "els => els.length"), 3)
    check("当前分支高亮数=2", pg.eval_on_selector_all(".nav-level li.on-branch", "els => els.length"), 2)
    cur = pg.eval_on_selector(".nav-level li.on-branch a", "el => el.textContent.trim()")
    check("高亮项含当前分支名", ("VDT10" in cur) or ("阶段报告" in cur), True)
    # 无横向溢出（抽屉打开时）
    sw = pg.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
    check("抽屉打开无横向溢出", sw <= 391, True)
    # 点击导航跳转
    pg.eval_on_selector_all(".nav-level li a", "els => els[0].click()"); pg.wait_for_timeout(800)
    check("跳转后仍在 /browse/", "/browse/" in pg.url, True)
    # ESC 关闭
    pg.go_back(wait_until="networkidle"); pg.click("#navpane-toggle"); pg.wait_for_timeout(300)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    check("ESC 关闭", pg.eval_on_selector("#navpane", "el => el.classList.contains('open')"), False)
    b.close()
print("\n结果:", "全部通过 ✔" if not fails else f"失败 {fails}")
sys.exit(0 if not fails else 1)
