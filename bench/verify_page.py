"""Open index.html in a real browser and verify it actually renders.

Number probes are not enough: check that the images decoded (naturalWidth > 0),
that the palette applied, that nothing overflows horizontally, and capture a
screenshot for visual review.
"""
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "index.html")
SHOT = os.path.join(tempfile.gettempdir(), "s2t_page_review.png")

checks = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 1000}, device_scale_factor=2)
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto("file:///" + PAGE.replace("\\", "/"))
    page.wait_for_load_state("networkidle")

    title = page.title()
    checks.append(("title", title, "send2trash" in title))

    # Images must have actually decoded, not just be present in the DOM.
    imgs = page.eval_on_selector_all(
        "figure img",
        "els => els.map(e => ({w: e.naturalWidth, h: e.naturalHeight, c: e.complete}))",
    )
    checks.append(("figure count", len(imgs), len(imgs) == 3))
    for i, info in enumerate(imgs):
        checks.append((f"img{i} decoded", f"{info['w']}x{info['h']} complete={info['c']}",
                       info["w"] > 500 and info["c"]))

    body_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    checks.append(("paper background", body_bg, body_bg == "rgb(250, 246, 240)"))

    ink = page.evaluate("getComputedStyle(document.body).color")
    checks.append(("ink text colour", ink, ink == "rgb(43, 33, 25)"))

    # Content present.
    h1 = page.inner_text("h1")
    checks.append(("h1", h1, "deleting the wrong file" in h1))

    n_findings = page.eval_on_selector_all(".finding", "els => els.length")
    checks.append(("finding cards", n_findings, n_findings == 6))

    n_badges = page.eval_on_selector_all(".badge", "els => els.length")
    checks.append(("badges", n_badges, n_badges >= 40))

    rows = page.eval_on_selector_all("table tbody tr", "els => els.length")
    checks.append(("table rows", rows, rows >= 18))

    # No horizontal overflow at desktop width.
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    checks.append(("horizontal overflow px", overflow, overflow <= 0))

    # Colour-class check: legend badges must not be transparent/black default.
    badge_bg = page.eval_on_selector(".badge", "e => getComputedStyle(e).backgroundColor")
    checks.append(("badge background", badge_bg, badge_bg != "rgba(0, 0, 0, 0)"))

    page.screenshot(path=SHOT, full_page=True)

    # Mobile width sanity.
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    m_overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    checks.append(("mobile overflow px", m_overflow, m_overflow <= 1))

    checks.append(("console errors", errors, not errors))
    browser.close()

ok = True
for name, value, passed in checks:
    mark = "PASS" if passed else "FAIL"
    if not passed:
        ok = False
    print(f"[{mark}] {name:24s} {value}")

print()
print("screenshot:", SHOT, os.path.getsize(SHOT), "bytes")
print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
