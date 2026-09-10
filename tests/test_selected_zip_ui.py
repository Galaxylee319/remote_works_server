"""多选打包下载 · UI 回归测试（Playwright 真实浏览器 + 真实下载）。

覆盖：勾选框渲染、悬浮操作条、列表/网格勾选同步、真实 ZIP 下载与内容校验、清除。
另见 tests/test_selected_zip_api.sh 覆盖路径穿越/空选/目录打包/去重等后端边界。

用法：
    RWS_CONFIG=/tmp/rws_zip.yaml ./venv/bin/python3 run.py &   # 免认证实例
    ./venv/bin/python3 tests/test_selected_zip_ui.py [base_url]
"""
import sys, zipfile, os
from playwright.sync_api import sync_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
fails = []
def check(n, got, want=True):
    ok = (got == want); print(f"  {'✔' if ok else '✘'} {n}: {got}"); 
    if not ok: fails.append(n)

with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 420, "height": 900}, accept_downloads=True)
    page.goto(f"{BASE}/browse/论文插图/", wait_until="networkidle")

    n_boxes = page.eval_on_selector_all(".pick-box", "els => els.length")
    check("勾选框数量 > 0", n_boxes > 0)
    check("操作条默认隐藏", page.eval_on_selector("#select-bar", "el => el.hidden"), True)

    # 勾两项（列表视图）
    page.eval_on_selector_all("#file-list .pick-box", "els => { els[0].click(); els[1].click(); }")
    page.wait_for_timeout(300)
    check("操作条出现", page.eval_on_selector("#select-bar", "el => el.hidden"), False)
    check("计数文案", page.inner_text("#select-count"), "已选 2 项")

    # 切到网格：勾选状态应同步过来
    page.click("#view-toggle"); page.wait_for_timeout(400)
    checked_grid = page.eval_on_selector_all("#grid-view .pick-box", "els => els.filter(e=>e.checked).length")
    check("网格视图同步勾选数", checked_grid, 2)

    # 再次勾一项（网格视图）
    page.eval_on_selector_all("#grid-view .pick-box", "els => els[2].click()")
    page.wait_for_timeout(300)
    check("计数更新为 3", page.inner_text("#select-count"), "已选 3 项")

    # 触发下载
    with page.expect_download(timeout=60000) as dl_info:
        page.click("#zip-submit")
    dl = dl_info.value
    out = "/tmp/rws_selected.zip"
    dl.save_as(out)
    size = os.path.getsize(out)
    check("下载文件名以 .zip 结尾", dl.suggested_filename.endswith(".zip"))
    check("ZIP 体积 > 0", size > 0)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        bad = zf.testzip()
    check("ZIP 完整性（无损坏项）", bad is None)
    check("ZIP 条目数 == 3", len(names), 3)
    print("    条目:", names)

    # 清除
    page.click("#select-clear"); page.wait_for_timeout(300)
    check("清除后操作条隐藏", page.eval_on_selector("#select-bar", "el => el.hidden"), True)
    b.close()

print("\n结果:", "全部通过 ✔" if not fails else f"失败 {fails}")
sys.exit(0 if not fails else 1)
