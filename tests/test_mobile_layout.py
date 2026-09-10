"""移动端布局回归测试（Playwright，390x844 手机视口）。

检查每个主要页面是否存在：横向溢出（撑破视口）、JS 报错、静态资源加载失败。
历史 bug：
  - 导航栏 .nav-links 撑破视口 10px（header 未换行 + 移动端间距过大）
  - Markdown 长「行内」公式溢出 50px（inline 元素无法用 max-width 约束）

用法：
    RWS_CONFIG=/tmp/rws_test.yaml ./venv/bin/python3 run.py &
    ./venv/bin/python3 tests/test_mobile_layout.py [base_url]
"""
from playwright.sync_api import sync_playwright
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
PAGES = [
    ("首页目录", "/browse/"),
    ("深目录", "/browse/阶段报告/VDT10-fair-budget-information-selection/"),
    ("图片目录", "/browse/figures_TypeI/"),
    ("搜索结果(正文)", "/search?q=%E9%80%80%E5%8C%96&mode=content"),
    ("搜索(文件名)", "/search?q=README&mode=name"),
    ("最近更新", "/recent"),
    ("Markdown 报告", "/view/阶段报告/VDT10-fair-budget-information-selection/Phase_VDT10_Fair_Budget_Information_Selection.md"),
    ("图片查看", "/view/figures_paper/fig3_corridor3_paired.png"),
    ("文本/日志", "/view/CHANGELOG.md"),
    ("PDF 查看", "/view/阶段报告/VDT10-fair-budget-information-selection/Phase_VDT10_Fair_Budget_Information_Selection.pdf"),
    ("登录页", "/login"),
    ("RSS", "/feed.xml"),
]
issues = []
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")
    page = ctx.new_page()
    console_errors, failed = [], []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))

    for name, path in PAGES:
        console_errors.clear(); failed.clear()
        try:
            page.goto(BASE + path, wait_until="networkidle", timeout=30000)
        except Exception as e:
            issues.append(f"{name}: 加载失败 {e}"); continue
        page.wait_for_timeout(800)
        sw = page.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
        ow = page.evaluate("window.innerWidth")
        over = sw - ow
        tag = []
        if over > 2: tag.append(f"横向溢出 {over}px")
        if console_errors: tag.append(f"JS错误 {len(console_errors)}: {console_errors[0][:60]}")
        if failed: tag.append(f"资源失败 {len(failed)}: {failed[0][:60]}")
        print(f"  {'✘' if tag else '✔'} {name:<16} {' | '.join(tag) if tag else 'OK'}")
        if tag: issues.append(f"{name}: {' | '.join(tag)}")
    b.close()

print("\n发现的问题:", len(issues))
for i in issues: print("  -", i)
sys.exit(1 if issues else 0)
