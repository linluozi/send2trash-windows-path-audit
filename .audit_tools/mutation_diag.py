"""Verify that each mutation is syntactically valid and semantically faithful.

A mutation that fails to *parse* is a false kill: it would make the suite look
like it detects the bug even when it does not.
"""
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(os.path.dirname(ROOT), ".venv-s2t", "Scripts", "python.exe")

MODERN = os.path.join("send2trash", "win", "modern.py")

MUTATIONS = {
    "M9-original-leak": (
        MODERN,
        "    pythoncom.CoInitialize()\n    try:\n        _delete_items(paths)\n    finally:",
        "    pythoncom.CoInitialize()\n    _delete_items(paths)\n    try:\n        pass\n    finally:",
    ),
    "M10-no-comerror-conversion": (
        MODERN,
        "    try:\n        # create instance of file operation object",
        "    if True:\n        # create instance of file operation object",
    ),
}

base = tempfile.mkdtemp(prefix="mutdiag_")
for label, (relpath, old, new) in MUTATIONS.items():
    work = os.path.join(base, label)
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".audit_tools"))
    target = os.path.join(work, relpath)
    with open(target, encoding="utf-8") as fh:
        src = fh.read()
    if old not in src:
        print(f"[{label}] ANCHOR NOT FOUND")
        continue
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src.replace(old, new, 1))

    try:
        py_compile.compile(target, doraise=True)
        syntax = "PARSES"
    except py_compile.PyCompileError as exc:
        syntax = f"SYNTAX ERROR: {exc.msg.splitlines()[-1][:90]}"

    proc = subprocess.run(
        [PY, "-m", "pytest", os.path.join("tests", "test_win_path_handling.py"), "-q", "--no-header"],
        cwd=work, capture_output=True, text=True,
    )
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln][-1:] or ["<no summary>"]
    print(f"[{label}] {syntax} | rc={proc.returncode} | {tail[0][:100]}")
    if proc.returncode != 0 and "failed" not in proc.stdout:
        print("    !! non-test failure, first stderr line:")
        print("   ", (proc.stderr.strip().splitlines() or [""])[0][:160])

shutil.rmtree(base, ignore_errors=True)
