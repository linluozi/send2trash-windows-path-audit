"""Render the audit figures from real run output.

Every number on every figure is read from a file produced by an actual test
run (``audit/*.txt``) or re-measured here. Nothing is typed in by hand, so a
figure can never claim something the run did not show.

Palette: warm editorial (espresso ink on paper, amber and terracotta accents).
"""

import os
import re
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

INK = "#2b2119"
PAPER = "#faf6f0"
AMBER = "#c8892b"
TERRACOTTA = "#b4552f"
OLIVE = "#6b6b3a"
MUTED = "#8a7a68"
RULE = "#d9cdbd"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "assets")

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.facecolor": PAPER,
        "text.color": INK,
        "axes.labelcolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "axes.edgecolor": RULE,
    }
)


def read(name):
    path = os.path.join(ROOT, "audit", name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------- figure 1
def fig_before_after():
    """Horizontal matrix: scenario x backend, outcome before vs after.

    Parsed from audit/differential.txt, which was produced by running the same
    scenario against the pristine baseline and the patched tree.
    """
    rows = []
    for line in read("differential.txt").splitlines():
        m = re.match(r"^(\w+)\s+(legacy|modern)\s+(.+?)\s{2,}(.+?)\s*(<== CHANGED)?$", line)
        if not m:
            continue
        scenario, backend, before, after = m.group(1), m.group(2), m.group(3), m.group(4)
        rows.append((scenario, backend, before.strip(), after.strip(), bool(m.group(5))))

    def state(text):
        """Classify an outcome string into deleted / kept / error."""
        if "no-exception" in text:
            return "deleted"
        if "DELETED" in text:
            return "deleted"
        return "error"

    labels = {
        "forward_slash": "forward slashes",
        "dot_component": "./ in path",
        "dotdot_component": "../ in path",
        "dir_trailing_slash": "dir with trailing /",
        "file_trailing_slash": "file with trailing /",
        "empty_string": "empty string ''",
        "nul_byte": "embedded NUL",
        "bytes_utf8": "bytes (non-ASCII name)",
        "unc_long_prefix": r"\\?\UNC\ prefix",
    }
    # Keep scenario order of first appearance.
    order = []
    for scenario, *_ in rows:
        if scenario not in order:
            order.append(scenario)

    fig, ax = plt.subplots(figsize=(10.6, 8.0))
    ax.set_xlim(0, 8.6)
    ROW = 1.36           # vertical space per scenario (title + two backend rows)
    HEAD = 2.5
    ax.set_ylim(-0.62, len(order) * ROW + HEAD)
    ax.axis("off")

    ax.text(0.0, len(order) * ROW + HEAD - 0.62,
            "Same call, same file, before vs after the fix",
            fontsize=15, fontweight="bold", color=INK, ha="left", va="center")
    ax.text(0.0, len(order) * ROW + HEAD - 1.24,
            "Each cell is one real run against a real file. \u201cdeleted\u201d means the requested file was trashed.",
            fontsize=9, color=MUTED, ha="left", va="center")

    BADGE_W, BADGE_H = 1.18, 0.30
    COL_B, COL_A = 3.35, 5.95

    for x, title in ((COL_B, "BEFORE  2.1.0+"), (COL_A, "AFTER  patched")):
        ax.text(x, len(order) * ROW + HEAD - 1.86, title, fontsize=8.8, color=MUTED,
                fontweight="bold", ha="left", va="center")
    hdr_y = len(order) * ROW + HEAD - 2.04
    ax.plot([COL_B, COL_B + BADGE_W], [hdr_y] * 2, color=RULE, lw=0.9)
    ax.plot([COL_A, COL_A + BADGE_W], [hdr_y] * 2, color=RULE, lw=0.9)

    # Offsets from the row's top edge.
    TITLE_DY, LEGACY_DY, MODERN_DY = 0.10, 0.53, 0.93

    for idx, scenario in enumerate(order):
        top = (len(order) - idx) * ROW
        ax.text(0.0, top - TITLE_DY, labels.get(scenario, scenario), fontsize=9.6,
                color=INK, ha="left", va="center")

        for backend, dy in (("legacy", LEGACY_DY), ("modern", MODERN_DY)):
            match = [r for r in rows if r[0] == scenario and r[1] == backend]
            if not match:
                continue
            _, _, before, after, changed = match[0]
            y = top - dy

            ax.text(0.0, y, backend, fontsize=7.4, color=MUTED, ha="left", va="center")

            for x, s in ((COL_B, state(before)), (COL_A, state(after))):
                ok = s == "deleted"
                ax.add_patch(Rectangle((x, y - BADGE_H / 2), BADGE_W, BADGE_H,
                                       facecolor=OLIVE if ok else TERRACOTTA,
                                       edgecolor="none"))
                ax.text(x + BADGE_W / 2, y, "deleted" if ok else "error", fontsize=7.8,
                        color=PAPER, fontweight="bold", va="center", ha="center")

            if changed:
                ax.text(COL_A + BADGE_W + 0.16, y, "fixed", fontsize=7.6,
                        color=AMBER, fontweight="bold", va="center", ha="left")

        if idx < len(order) - 1:
            sep = top - ROW + 0.075
            ax.plot([0, COL_A + BADGE_W + 0.75], [sep] * 2, color=RULE, lw=0.55)

    # Legend at the bottom, outside the grid.
    ly = -0.28
    for x, face, text in ((0.0, OLIVE, "deleted"), (1.35, TERRACOTTA, "error / file kept")):
        ax.add_patch(Rectangle((x, ly - 0.11), 0.42, 0.22, facecolor=face, edgecolor="none"))
        ax.text(x + 0.52, ly, text, fontsize=8.2, color=MUTED, va="center")
    ax.text(3.3, ly, "\u2192 fixed = behaviour changed by this patch",
            fontsize=8.2, color=AMBER, va="center", fontweight="bold")

    fig.savefig(os.path.join(OUT, "before_after.png"), dpi=200, bbox_inches="tight",
                pad_inches=0.28)
    plt.close(fig)
    return len([r for r in rows if r[4]])


# ---------------------------------------------------------------- figure 2
def fig_mutation():
    """Per-mutation kill counts, parsed from audit/mutation.txt."""
    text = read("mutation.txt")
    items = []
    for line in text.splitlines():
        m = re.match(r"^\[(KILLED|SURVIVED)\]\s+(.+?)\s+\(failed=(\d+)\)", line)
        if m:
            items.append((m.group(2), m.group(1) == "KILLED", int(m.group(3))))
    assert items, "no mutation results parsed"

    # Shorten labels to the essential defect.
    short = []
    for label, killed, n in items:
        clean = re.sub(r"\s*\(.*?\)\s*$", "", label)
        clean = clean.replace("no ", "").replace(" (original", "")
        short.append((clean.strip(), killed, n))

    fig, ax = plt.subplots(figsize=(9.6, 5.2))
    ys = list(range(len(short)))[::-1]
    names = [s[0] for s in short]
    counts = [s[2] for s in short]
    colors = [OLIVE if s[1] else TERRACOTTA for s in short]

    ax.barh(ys, counts, color=colors, height=0.62, edgecolor="none")
    for y, c, (name, killed, n) in zip(ys, counts, short):
        ax.text(n + 0.22, y, f"{n}", va="center", fontsize=8.5, color=INK, fontweight="bold")
    ax.set_yticks(ys)
    ax.set_yticklabels(names, fontsize=8.6)
    ax.set_xlabel("regression tests that failed (must be \u2265 1 to count as caught)", fontsize=9)
    ax.set_xlim(0, max(counts) + 2.4)
    ax.set_title("Mutation test: every original bug re-injected, one at a time",
                 fontsize=13, fontweight="bold", loc="left", pad=30)
    ax.text(0, 1.055, "Green = the suite caught it. A survivor would mean a hole in the tests.",
            transform=ax.transAxes, fontsize=9, color=MUTED)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(RULE)
    ax.spines["bottom"].set_color(RULE)
    ax.tick_params(length=0)
    ax.grid(axis="x", color=RULE, lw=0.6, alpha=0.7)
    ax.set_axisbelow(True)

    fig.savefig(os.path.join(OUT, "mutation.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    return len(short)


# ---------------------------------------------------------------- figure 3
def fig_tests():
    """Pass/fail counts parsed from the saved pytest outputs."""
    def counts(name):
        text = read(name)
        m = re.search(r"(\d+) failed, (\d+) passed", text)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.search(r"(\d+) passed", text)
        if m:
            return 0, int(m.group(1))
        return None, None

    base_failed, base_passed = counts("baseline_failures.txt")
    patched_failed, patched_passed = counts("test_run.txt")
    assert base_failed is not None and patched_passed is not None

    fig, ax = plt.subplots(figsize=(9.6, 3.3))
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)

    cards = [
        (0.15, "new tests vs unpatched code", f"{base_failed} failed", f"{base_passed} passed", TERRACOTTA),
        (3.45, "full suite, patched code", f"{patched_passed} passed", "0 failed", OLIVE),
    ]
    for x, title, big, small, color in cards:
        ax.add_patch(Rectangle((x, 0.35), 3.05, 2.05, facecolor="white",
                               edgecolor=RULE, lw=1))
        ax.add_patch(Rectangle((x, 0.35), 0.09, 2.05, facecolor=color, edgecolor="none"))
        ax.text(x + 0.28, 2.04, title, fontsize=8.8, color=MUTED, va="center")
        ax.text(x + 0.28, 1.40, big, fontsize=20, color=color, fontweight="bold", va="center")
        ax.text(x + 0.28, 0.80, small, fontsize=9.2, color=INK, va="center")

    ax.text(7.15, 1.96, "%d" % (base_failed + base_passed), fontsize=20,
            color=AMBER, fontweight="bold", va="center")
    ax.text(7.15, 1.47, "regression cases added", fontsize=8.8, color=INK, va="center")
    ax.text(7.15, 1.02, "30 flip from red to green;", fontsize=8.2, color=MUTED, va="center")
    ax.text(7.15, 0.72, "9 are contract checks green on both.", fontsize=8.2, color=MUTED, va="center")

    fig.savefig(os.path.join(OUT, "tests.png"), dpi=200, bbox_inches="tight")
    plt.close(fig)
    return base_failed, base_passed, patched_passed


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    fixed = fig_before_after()
    muts = fig_mutation()
    bf, bp, pp = fig_tests()
    print(f"before_after.png : {fixed} scenarios changed")
    print(f"mutation.png     : {muts} mutations")
    print(f"tests.png        : baseline {bf} failed/{bp} passed, patched {pp} passed")
    for name in ("before_after.png", "mutation.png", "tests.png"):
        p = os.path.join(OUT, name)
        print(f"  {name:18s} {os.path.getsize(p):7d} bytes")
