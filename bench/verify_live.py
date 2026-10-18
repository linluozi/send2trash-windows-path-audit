"""Verify the published GitHub Pages site actually renders.

Checks the live URL, not the local file: the page must load, its three inlined
images must decode, the palette must apply, and there must be no overflow.
Saves a screenshot for visual review.
"""
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

URL = "https://linluozi.github.io/send2trash-windows-path-audit/"
SHOT = os.path.join(tempfile.gettempdir(), "s2t_live_page.png")

checks = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    errors, failed = [], []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("requestfailed", lambda r: failed.append(r.url))

    resp = page.goto(URL, wait_until="networkidle", timeout=60000)
    checks.append(("HTTP status", resp.status, resp.status == 200))

    checks.append(("title", page.title(), "send2trash" in page.title()))

    imgs = page.eval_on_selector_all(
        "figure img",
        "els => els.map(e => ({w: e.naturalWidth, h: e.naturalHeight, c: e.complete}))",
    )
    checks.append(("figure count", len(imgs), len(imgs) == 3))
    for i, info in enumerate(imgs):
        checks.append((f"img{i} decoded", f"{info['w']}x{info['h']}", info["w"] > 500 and info["c"]))

    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    checks.append(("paper background", bg, bg == "rgb(250, 246, 240)"))

    colour = page.evaluate("getComputedStyle(document.body).color")
    checks.append(("ink colour", colour, colour == "rgb(43, 33, 25)"))

    checks.append(("h1", page.inner_text("h1"), "deleting the wrong file" in page.inner_text("h1")))
    n = page.eval_on_selector_all(".finding", "els => els.length")
    checks.append(("finding cards", n, n == 6))
    rows = page.eval_on_selector_all("table tbody tr", "els => els.length")
    checks.append(("table rows", rows, rows >= 18))

    over = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    checks.append(("horizontal overflow px", over, over <= 0))
    checks.append(("console errors", errors, not errors))
    checks.append(("failed requests", failed, not failed))

    page.screenshot(path=SHOT, full_page=True)
    browser.close()

ok = True
for name, value, passed in checks:
    if not passed:
        ok = False
    print(f"[{'PASS' if passed else 'FAIL'}] {name:22s} {value}")

print()
print("shot:", SHOT, os.path.getsize(SHOT), "bytes")
print("RESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
