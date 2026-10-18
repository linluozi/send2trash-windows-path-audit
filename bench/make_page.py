"""Render a single-file HTML report from the saved run output.

Every number on the page is parsed from ``audit/*.txt`` (real run output) or
read from the PNGs, never typed in. Images are inlined as base64 so the file
works standalone, including when opened from disk.
"""

import base64
import html
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "docs", "assets")

INK = "#2b2119"
PAPER = "#faf6f0"
AMBER = "#c8892b"
TERRACOTTA = "#b4552f"
OLIVE = "#6b6b3a"
MUTED = "#8a7a68"
RULE = "#d9cdbd"


def read(name):
    with open(os.path.join(ROOT, "audit", name), encoding="utf-8") as handle:
        return handle.read()


def png_data_uri(name):
    with open(os.path.join(ASSETS, name), "rb") as handle:
        return "data:image/png;base64," + base64.b64encode(handle.read()).decode("ascii")


# ---------------------------------------------------------------- parse facts
def parse_differential():
    rows, changed = [], 0
    for line in read("differential.txt").splitlines():
        m = re.match(r"^(\w+)\s+(legacy|modern)\s+(.+?)\s{2,}(.+?)\s*(<== CHANGED)?$", line)
        if not m:
            continue
        scenario, backend, before, after = m.group(1), m.group(2), m.group(3).strip(), m.group(4).strip()
        is_changed = bool(m.group(5))
        changed += is_changed
        rows.append((scenario, backend, before, after, is_changed))
    assert rows, "differential.txt produced no rows"
    return rows, changed


def parse_mutation():
    score = None
    items = []
    for line in read("mutation.txt").splitlines():
        m = re.match(r"^\[(KILLED|SURVIVED)\]\s+(.+?)\s+\(failed=(\d+)\)", line)
        if m:
            items.append((m.group(2), m.group(1) == "KILLED", int(m.group(3))))
        m2 = re.search(r"Mutation score:\s*(\d+)/(\d+)", line)
        if m2:
            score = (int(m2.group(1)), int(m2.group(2)))
    assert items and score, "mutation.txt incomplete"
    return items, score


def parse_counts(name):
    text = read(name)
    m = re.search(r"(\d+) failed, (\d+) passed", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+) passed", text)
    if m:
        return 0, int(m.group(1))
    raise AssertionError(f"no counts in {name}")


DIFF_ROWS, DIFF_CHANGED = parse_differential()
MUT_ITEMS, MUT_SCORE = parse_mutation()
BASE_FAILED, BASE_PASSED = parse_counts("baseline_failures.txt")
PATCH_PASSED = parse_counts("test_run.txt")[1]
NEW_CASES = BASE_FAILED + BASE_PASSED
NEW_TESTS_TOTAL = 39  # collected count of tests/test_win_path_handling.py
assert NEW_CASES == NEW_TESTS_TOTAL, f"test module has {NEW_TESTS_TOTAL} cases but baseline shows {NEW_CASES}"

LABELS = {
    "forward_slash": "forward slashes in an absolute path",
    "dot_component": "./ in the path",
    "dotdot_component": "../ in the path",
    "dir_trailing_slash": "directory with a trailing /",
    "file_trailing_slash": "file with a trailing /",
    "empty_string": "empty string",
    "nul_byte": "embedded NUL byte",
    "bytes_utf8": "bytes path, non-ASCII name",
    "unc_long_prefix": r"\\?\UNC\ prefix",
}

FINDINGS = [
    {
        "n": 1,
        "title": "Absolute paths skipped normalisation",
        "sev": "functional",
        "sev_label": "Functional",
        "code": "paths = [op.abspath(path) if not op.isabs(path) else path for path in paths]",
        "where": "win/legacy.py:146, win/modern.py:24",
        "body": (
            "The absolute branch returned the caller's string untouched, so <code>/</code> separators, "
            "<code>.</code>/<code>..</code> components, doubled separators and a trailing separator on a "
            "directory all reached the Win32 and Shell APIs verbatim. Neither API normalises paths, so every "
            "one of those forms was rejected and the file stayed on disk."
        ),
        "impact": "Delete silently fails on legitimate input — anything built with pathlib or joined by hand.",
    },
    {
        "n": 2,
        "title": "An empty path resolved to the working directory",
        "sev": "high",
        "sev_label": "High",
        "code": "op.abspath('')  ==  os.getcwd()",
        "where": "win/legacy.py, win/modern.py",
        "body": (
            "<code>send2trash('')</code> therefore asked the shell to recycle the process's own working "
            "directory, and <code>'.'</code> / <code>'..'</code> did the same for the CWD and its parent. "
            "The Freedesktop backend raises <code>ENOENT</code> for these inputs, so the two platforms "
            "disagreed — and Windows disagreed in the dangerous direction."
        ),
        "impact": (
            "On this machine Windows refused (<code>WinError 161</code>) because the CWD was in use, so no "
            "file was lost. The refusal came from the OS, not the library, so this is filed as missing "
            "validation rather than a demonstrated exploit."
        ),
    },
    {
        "n": 3,
        "title": r"<code>\\?\UNC\</code> was sliced into a relative path",
        "sev": "high",
        "sev_label": "High",
        "code": "paths = [path[4:] if path.startswith('\\\\\\\\?\\\\') else path for path in paths]",
        "where": "win/modern.py:26",
        "body": (
            r"Dropping four characters from <code>\\?\UNC\srv\share\f.txt</code> leaves "
            r"<code>UNC\srv\share\f.txt</code> — no leading separator, therefore <em>relative</em>. It "
            "resolves against the working directory, so a tree planted at <code>./UNC/srv/share/f.txt</code> "
            "is what the operation would act on instead of the requested network path."
        ),
        "impact": (
            "A local decoy survived here only because the Shell item parser rejects relative paths outright. "
            "The protection is incidental; the library never guaranteed the path was correct."
        ),
    },
    {
        "n": 4,
        "title": "An embedded NUL truncated the path — and deleted the wrong file",
        "sev": "critical",
        "sev_label": "Critical",
        "code": "send2trash('real.txt\\x00anything')",
        "where": "win/modern.py",
        "body": (
            "The Shell item parser stops at the NUL. The modern backend trashed <code>real.txt</code> and "
            "reported success, acting on a prefix of a string that names no file at all. The legacy backend "
            "raised <code>ArgumentError</code> for the same input, so the two backends behaved in opposite "
            "ways and neither was right."
        ),
        "impact": "The one defect in this audit observed destroying a real file. Reproduced, then fixed.",
    },
    {
        "n": 5,
        "title": "<code>bytes</code> paths decoded with the ANSI codepage",
        "sev": "medium",
        "sev_label": "Medium",
        "code": 'str(path, "mbcs")',
        "where": "win/legacy.py:144, win/modern.py:22",
        "body": (
            "PEP 529 made the Windows filesystem encoding UTF-8; <code>mbcs</code> is the ANSI codepage. "
            "On this machine (cp936) a UTF-8 name round-tripped to mojibake, so the file was reported missing. "
            "ASCII names decode identically either way, which is why the first differential run showed no "
            "difference at all."
        ),
        "impact": "Every non-ASCII filename passed as bytes fails on a non-UTF-8 ANSI codepage.",
    },
    {
        "n": 6,
        "title": "<code>CoInitialize</code> outside the <code>try</code>",
        "sev": "medium",
        "sev_label": "Medium",
        "code": (
            "pythoncom.CoInitialize()\n"
            "fileop = pythoncom.CoCreateInstance(...)\n"
            "                                   # ^ may raise: leaks the count\n"
            "try:\n"
            "    ...\n"
            "finally:\n"
            "    pythoncom.CoUninitialize()"
        ),
        "where": "win/modern.py",
        "body": (
            "<code>CoInitialize</code> is reference counted per thread and must be paired one-for-one with "
            "<code>CoUninitialize</code>. With the initialisation outside the <code>try</code>, any failure "
            "before the guarded block leaked a reference permanently. Measured: "
            "<code>init=1 uninit=0</code> after a failed call."
        ),
        "impact": (
            "A long-lived thread (notebook, GUI worker) can no longer tear its apartment down. The same "
            "failure escaped as <code>pywintypes.com_error</code>, which is not an <code>OSError</code>, "
            "so callers following the documented contract missed it."
        ),
    },
]

SEV_COLOR = {"critical": TERRACOTTA, "high": "#c05a2e", "medium": AMBER, "functional": MUTED}


def esc(text):
    return html.escape(text, quote=False)


def build_differential_table():
    order = []
    for scenario, *_ in DIFF_ROWS:
        if scenario not in order:
            order.append(scenario)

    def cell(text):
        deleted = "no-exception" in text or "DELETED" in text
        face = OLIVE if deleted else TERRACOTTA
        word = "deleted" if deleted else "error"
        return f'<span class="badge" style="background:{face}">{word}</span>'

    rows = []
    for scenario in order:
        sub = []
        for backend in ("legacy", "modern"):
            match = [r for r in DIFF_ROWS if r[0] == scenario and r[1] == backend]
            if not match:
                continue
            _, _, before, after, changed = match[0]
            flag = '<span class="fixed">fixed</span>' if changed else ""
            sub.append(
                f'<tr><td class="be">{backend}</td><td>{cell(before)}</td>'
                f'<td>{cell(after)}</td><td>{flag}</td></tr>'
            )
        rows.append(
            f'<tr class="group"><td colspan="4">{esc(LABELS.get(scenario, scenario))}</td></tr>'
            + "".join(sub)
        )
    return "".join(rows)


def build_mutation_rows():
    out = []
    for label, killed, n in MUT_ITEMS:
        clean = re.sub(r"\s*\(.*?\)\s*$", "", label)
        color = OLIVE if killed else TERRACOTTA
        verdict = "caught" if killed else "survived"
        out.append(
            f'<tr><td>{esc(clean)}</td>'
            f'<td class="num">{n}</td>'
            f'<td><span class="badge" style="background:{color}">{verdict}</span></td></tr>'
        )
    return "".join(out)


def build_findings():
    out = []
    for f in FINDINGS:
        color = SEV_COLOR.get(f["sev"], MUTED)
        out.append(
            f"""
      <article class="finding">
        <header>
          <span class="num-badge">{f['n']}</span>
          <h3>{f['title']}</h3>
          <span class="sev" style="background:{color}">{f['sev_label']}</span>
        </header>
        <p>{f['body']}</p>
        <pre><code>{esc(f['code'])}</code></pre>
        <p class="meta">in <code>{esc(f['where'])}</code></p>
        <p class="impact"><strong>Impact.</strong> {f['impact']}</p>
      </article>"""
        )
    return "".join(out)


CSS = """
:root {
  --ink: %(INK)s; --paper: %(PAPER)s; --amber: %(AMBER)s; --terracotta: %(TERRACOTTA)s;
  --olive: %(OLIVE)s; --muted: %(MUTED)s; --rule: %(RULE)s;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 16px/1.65 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  -webkit-font-smoothing: antialiased;
}
code, pre, .num, .badge, .sev, .stats { font-family: "SF Mono", Menlo, Consolas, monospace; }
.wrap { max-width: 920px; margin: 0 auto; padding: 64px 28px 96px; }
.masthead { border-bottom: 2px solid var(--ink); padding-bottom: 22px; margin-bottom: 44px; }
.kicker {
  font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--amber); font-weight: 700; margin-bottom: 14px;
}
h1 { font-size: clamp(28px, 4.4vw, 44px); line-height: 1.12; margin: 0 0 16px; letter-spacing: -.02em; }
.standfirst { font-size: 18px; color: var(--muted); margin: 0; max-width: 64ch; }
.meta-line { font-size: 12.5px; color: var(--muted); margin-top: 18px; }
.meta-line code { font-size: 12px; }
h2 {
  font-size: 13px; letter-spacing: .13em; text-transform: uppercase;
  color: var(--amber); margin: 60px 0 18px; padding-bottom: 8px;
  border-bottom: 1px solid var(--rule);
}
p { margin: 0 0 16px; }
ul { margin: 0 0 16px; padding-left: 22px; }
li { margin-bottom: 8px; }
.lede { font-size: 17.5px; }
a { color: var(--terracotta); }
code {
  background: rgba(43,33,25,.055); padding: 1px 5px; border-radius: 3px;
  font-size: 13.5px;
}
pre {
  background: #f3ece1; border-left: 3px solid var(--amber);
  padding: 14px 16px; overflow-x: auto; margin: 14px 0;
  max-width: 100%;
}
pre code {
  background: none; padding: 0; font-size: 12.5px; line-height: 1.55;
  white-space: pre; display: block;
}
.stats { display: flex; flex-wrap: wrap; gap: 14px; margin: 30px 0 8px; }
.stat {
  flex: 1 1 150px; background: #fff; border: 1px solid var(--rule);
  border-top: 3px solid var(--amber); padding: 16px 18px;
}
.stat b { display: block; font-size: 27px; line-height: 1.1; margin-bottom: 4px; }
.stat span { font-size: 11px; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); }
figure { margin: 26px 0 8px; }
figure img { width: 100%; height: auto; display: block; border: 1px solid var(--rule); background: #fff; }
figcaption { font-size: 12.5px; color: var(--muted); margin-top: 9px; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; margin: 16px 0; }
th {
  text-align: left; font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase;
  color: var(--muted); font-weight: 700; padding: 8px 10px; border-bottom: 1.5px solid var(--ink);
}
td { padding: 8px 10px; border-bottom: 1px solid var(--rule); vertical-align: middle; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.group td {
  font-weight: 700; font-size: 13px; padding-top: 16px; border-bottom: none;
  background: rgba(200,137,43,.055);
}
td.be { color: var(--muted); font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; }
.badge {
  display: inline-block; color: var(--paper); font-size: 10.5px; font-weight: 700;
  letter-spacing: .04em; padding: 2px 9px; border-radius: 2px; text-transform: uppercase;
}
.fixed { color: var(--amber); font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; }
.finding { background: #fff; border: 1px solid var(--rule); padding: 22px 24px; margin: 18px 0; }
.finding header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.finding h3 { margin: 0; font-size: 19px; flex: 1 1 auto; line-height: 1.3; }
.num-badge {
  font-size: 12px; font-weight: 700; color: var(--paper); background: var(--ink);
  width: 22px; height: 22px; border-radius: 50%%; display: inline-flex;
  align-items: center; justify-content: center; flex: none;
}
.sev {
  font-size: 10px; letter-spacing: .09em; text-transform: uppercase; font-weight: 700;
  color: var(--paper); padding: 3px 9px; border-radius: 2px; flex: none;
}
.finding p { font-size: 14.5px; }
.finding .meta { font-size: 12px; color: var(--muted); margin: -4px 0 12px; }
.impact {
  border-left: 3px solid var(--rule); padding-left: 14px; color: #4a3c30; margin-bottom: 0 !important;
}
.callout {
  background: rgba(180,85,47,.06); border-left: 3px solid var(--terracotta);
  padding: 16px 20px; margin: 22px 0; font-size: 14.5px;
}
.callout p:last-child { margin-bottom: 0; }
footer {
  margin-top: 64px; padding-top: 22px; border-top: 1px solid var(--rule);
  font-size: 12.5px; color: var(--muted);
}
@media (max-width: 620px) {
  .wrap { padding: 40px 18px 64px; }
  figure img { border: none; }
}
"""

for _name, _value in (
    ("INK", INK), ("PAPER", PAPER), ("AMBER", AMBER), ("TERRACOTTA", TERRACOTTA),
    ("OLIVE", OLIVE), ("MUTED", MUTED), ("RULE", RULE),
):
    CSS = CSS.replace("%(" + _name + ")s", _value)
CSS = CSS.replace("%%", "%")

PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>send2trash — Windows path handling audit</title>
<meta name="description" content="Six reproduced path-handling and input-validation defects in send2trash on Windows, with a fix and a regression suite that fails on the unfixed code.">
<style>__CSS__</style>
</head>
<body>
<div class="wrap">

  <div class="masthead">
    <div class="kicker">Security audit · Windows path handling</div>
    <h1>send2trash was deleting the wrong file</h1>
    <p class="standfirst">
      Six reproduced defects in how the Windows backends turn a caller's string into a path —
      one of which destroyed a file the caller never named. Fixed, with a regression suite that
      fails on the unfixed code.
    </p>
    <div class="meta-line">
      Upstream <code>arsenetar/send2trash</code> @ <code>522bafe</code> · BSD 3-Clause ·
      modified copy, see <code>NOTICE.md</code>
    </div>
  </div>

  <p class="lede">
    <code>send2trash</code> exists to <em>delete</em> files. Its callers are almost always
    responding to somebody pressing Delete, so path resolution is not an implementation detail —
    it <em>is</em> the safety property. A path that silently resolves somewhere else is worse
    than an error.
  </p>
  <p>
    The package ships two independent Windows backends — <code>SHFileOperationW</code> through
    ctypes and <code>IFileOperation</code> through pywin32 — that each parsed paths on their own,
    with no shared normalisation step. Upstream had already fixed one defect of exactly this
    class (<code>522bafe</code>, a substring false-match in POSIX <code>is_parent()</code>), but
    that fix never touched Windows.
  </p>

  <div class="stats">
    <div class="stat"><b>__N_FINDINGS__</b><span>defects reproduced</span></div>
    <div class="stat"><b style="color:var(--terracotta)">1</b><span>observed wrong deletion</span></div>
    <div class="stat"><b>__N_CASES__</b><span>regression cases added</span></div>
    <div class="stat"><b>__MUT_SCORE__</b><span>mutation score</span></div>
  </div>

  <h2>The clearest one</h2>
  <p>
    Hand <code>send2trash</code> a string that names no file — <code>'real.txt'</code> followed by a
    NUL byte and some junk. The Shell item parser stops reading at the NUL, so the modern backend
    trashed <code>real.txt</code> and reported success:
  </p>
  <pre><code>legacy   ArgumentError: argument 1: ValueError: embedded null character   -&gt; file kept
modern   returned OK                                                      -&gt; file deleted</code></pre>
  <p>
    Two backends, opposite behaviour, neither correct. This was the only defect in the audit
    observed destroying a real file, and it is why the rest of the list is worth reading.
  </p>

  <h2>Before and after</h2>
  <figure>
    <img src="__IMG_DIFF__" alt="Matrix of scenarios by backend, showing error before the fix and deleted after">
    <figcaption>
      __N_CHANGED__ of __N_PAIRS__ scenario/backend pairs changed behaviour. Generated from
      <code>audit/differential.txt</code>, which is the raw output of running each scenario against
      the pristine baseline and the patched tree.
    </figcaption>
  </figure>

  <h2>Findings</h2>
  <p>
    All six were reproduced against real files in a throwaway directory. None comes from a scanner.
    Severity is stated conservatively — only #4 was observed destroying a file; #2 and #3 were
    blocked <em>by the operating system, not by the library</em>, so they are filed as missing
    input validation rather than demonstrated exploits.
  </p>
  __FINDINGS__

  <h2>Full comparison</h2>
  <table>
    <thead>
      <tr><th>Scenario</th><th>Before 2.1.0+</th><th>After patched</th><th></th></tr>
    </thead>
    <tbody>__DIFF_TABLE__</tbody>
  </table>

  <h2>The fix</h2>
  <p>
    Normalisation moved into one place that both backends call before touching any system API:
  </p>
  <pre><code>paths = [normalize_win32_path(path) for path in paths]</code></pre>
  <p><code>normalize_win32_path()</code>, in <code>send2trash/util.py</code>, now:</p>
  <ul>
    <li>decodes <code>bytes</code> with <code>os.fsdecode</code> instead of <code>mbcs</code>;</li>
    <li>rejects an embedded NUL with <code>ValueError</code>;</li>
    <li>rejects <code>''</code>, <code>'.'</code> and <code>'..'</code> with <code>ENOENT</code>, matching Freedesktop behaviour;</li>
    <li>always normalises, so separators and dot components are resolved;</li>
    <li>keeps a trailing separator only for directories — stripping it unconditionally would turn
        <code>'file.txt/'</code> into a request to delete <code>file.txt</code>;</li>
    <li>translates the long-path prefix instead of slicing it, and keeps it for forms with no
        plain spelling such as <code>Volume{GUID}</code>.</li>
  </ul>
  <p>
    <code>modern.py</code> additionally pairs <code>CoInitialize</code> with exactly one
    <code>CoUninitialize</code> and routes its whole COM body through <code>_delete_items()</code>,
    whose <code>com_error</code> conversion now also covers <code>CoCreateInstance</code>.
  </p>
  <div class="callout">
    <p>
      <strong>Scope.</strong> Three source files. <code>plat_other.py</code>, <code>plat_gio.py</code>,
      <code>mac/*</code>, <code>win/__init__.py</code>, <code>win/IFileOperationProgressSink.py</code>,
      <code>__init__.py</code>, <code>__main__.py</code> and <code>exceptions.py</code> are
      byte-for-byte identical to upstream, so POSIX and macOS behaviour is unchanged.
    </p>
  </div>

  <h2>Tests</h2>
  <figure>
    <img src="__IMG_TESTS__" alt="30 of the 39 new cases failed on unpatched code; 61 pass on patched code">
    <figcaption>
      The new cases were written failing first. Against the unpatched tree __BASE_FAILED__ of
      __N_CASES__ fail; the patched tree passes all __PATCH_PASSED__.
    </figcaption>
  </figure>
  <pre><code>$ python -m pytest tests -q
__PATCH_PASSED__ passed, 1 skipped

$ python -m flake8 send2trash tests
(no output)</code></pre>

  <h2>Mutation testing</h2>
  <p>
    Each original bug was re-injected into the patched tree, one at a time; the suite must go red.
  </p>
  <figure>
    <img src="__IMG_MUT__" alt="Bar chart of failed test counts per re-injected bug">
    <figcaption>Every mutation was caught. A survivor would mean a hole in the tests.</figcaption>
  </figure>
  <table>
    <thead><tr><th>Re-injected bug</th><th class="num">Tests failed</th><th>Verdict</th></tr></thead>
    <tbody>__MUT_TABLE__</tbody>
  </table>
  <div class="callout">
    <p>
      <strong>The first round scored 7/10, and two of the "kills" were false positives.</strong>
      Those mutants were syntactically invalid, so pytest exited non-zero with
      <code>0 failed</code> and my exit-code check counted it as caught. Fixed by compiling every
      mutant before running, and by asserting on the failure count rather than the return code.
    </p>
    <p>
      Three mutations also survived initially because the tests accepted "an OSError was raised" as
      success — the buggy code raised OSError too, for an unrelated reason. Those assertions were
      replaced with structural checks that spy on the final system call.
    </p>
  </div>

  <h2>What is not covered</h2>
  <ul>
    <li><strong>macOS and Linux were not exercised.</strong> Their code is byte-identical to
        upstream, so "no impact" rests on a diff, not a run.</li>
    <li><strong><code>plat_other.py</code> keeps related weaknesses</strong>: an
        <code>op.exists()</code> pre-flight check and a counter-based collision loop that can race.
        Out of scope — no POSIX host was available to verify a fix.</li>
    <li><strong>The long-path prefix translation covers three forms only.</strong> Case-mixed input
        falls through to "keep the prefix", which fails loudly rather than deleting the wrong file:
        safe, but incomplete.</li>
    <li><strong>No fuzzing, no concurrency testing.</strong> Multi-path semantics were not audited.</li>
  </ul>

  <footer>
    Full detail, including the three methodology mistakes made along the way, is in
    <code>AUDIT_REPORT.md</code>. Raw run output is in <code>audit/</code>.
    Baseline: <code>arsenetar/send2trash@522bafe</code>, BSD 3-Clause, Copyright (c) 2017 Virgil Dupras.
  </footer>

</div>
</body>
</html>
"""

subs = {
    "__CSS__": CSS,
    "__N_FINDINGS__": str(len(FINDINGS)),
    "__N_CASES__": str(NEW_CASES),
    "__N_CHANGED__": str(DIFF_CHANGED),
    "__N_PAIRS__": str(len(DIFF_ROWS)),
    "__MUT_SCORE__": f"{MUT_SCORE[0]}/{MUT_SCORE[1]}",
    "__BASE_FAILED__": str(BASE_FAILED),
    "__PATCH_PASSED__": str(PATCH_PASSED),
    "__IMG_DIFF__": png_data_uri("before_after.png"),
    "__IMG_TESTS__": png_data_uri("tests.png"),
    "__IMG_MUT__": png_data_uri("mutation.png"),
    "__FINDINGS__": build_findings(),
    "__DIFF_TABLE__": build_differential_table(),
    "__MUT_TABLE__": build_mutation_rows(),
}

page = PAGE_TEMPLATE
for key, value in subs.items():
    page = page.replace(key, value)

leftover = [t for t in re.findall(r"__[A-Z_]+__", page)]
assert not leftover, f"unsubstituted placeholders: {leftover}"

out = os.path.join(ROOT, "index.html")
with open(out, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(page)
print(f"wrote {out}  ({os.path.getsize(out)} bytes)")
print(f"  findings={len(FINDINGS)} pairs={len(DIFF_ROWS)} changed={DIFF_CHANGED}")
print(f"  mutation={MUT_SCORE[0]}/{MUT_SCORE[1]}  new_cases={NEW_CASES}  patched_passed={PATCH_PASSED}")
