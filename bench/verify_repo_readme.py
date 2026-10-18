"""Confirm the README images actually render on the GitHub repo page.

`naturalWidth > 0` is the only proof they decoded in a real browser; the file
being present in the repo is not enough.
"""
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

URL = "https://github.com/linluozi/send2trash-windows-path-audit"
SHOT = os.path.join(tempfile.gettempdir(), "s2t_repo_page.png")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 1100})
    page.goto(URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5000)

    # GitHub lazy-loads README images; scroll them into view first.
    imgs = page.query_selector_all("article.markdown-body img")
    print("README img elements:", len(imgs))
    for el in imgs:
        el.scroll_into_view_if_needed()
    page.wait_for_timeout(4000)

    info = page.eval_on_selector_all(
        "article.markdown-body img",
        "els => els.map(e => ({src: e.currentSrc || e.src, w: e.naturalWidth, h: e.naturalHeight}))",
    )
    ok = True
    for i, item in enumerate(info):
        good = item["w"] > 100
        ok = ok and good
        print(f"[{'PASS' if good else 'FAIL'}] img{i} {item['w']}x{item['h']}  {item['src'].split('/')[-1][:44]}")

    title = page.title()
    print(f"[{'PASS' if 'send2trash' in title else 'FAIL'}] title: {title}")

    page.screenshot(path=SHOT, full_page=False)
    print("shot:", SHOT, os.path.getsize(SHOT), "bytes")
    browser.close()

print("RESULT:", "ALL PASS" if ok and len(info) == 3 else "PROBLEM")
sys.exit(0 if ok and len(info) == 3 else 1)
