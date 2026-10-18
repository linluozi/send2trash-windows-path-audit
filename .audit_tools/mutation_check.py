"""Mutation test: does the regression suite actually detect each defect?

Each mutation re-introduces one original bug into the *patched* tree and the
suite must go red. A mutation that stays green is a hole in the tests.

Runs each mutation in a throwaway copy so the working tree is never touched.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(os.path.dirname(ROOT), ".venv-s2t", "Scripts", "python.exe")

UTIL = os.path.join("send2trash", "util.py")
LEGACY = os.path.join("send2trash", "win", "legacy.py")
MODERN = os.path.join("send2trash", "win", "modern.py")
TESTFILE = os.path.join("tests", "test_win_path_handling.py")

# (label, file, old, new)
MUTATIONS = [
    (
        "M1 no normalisation (original abspath-only-if-relative)",
        UTIL,
        "    normalized = os.path.normpath(os.path.abspath(path))",
        "    normalized = os.path.abspath(path) if not os.path.isabs(path) else path",
    ),
    (
        "M2 no NUL rejection",
        UTIL,
        '    if "\\x00" in path:',
        '    if False:  # mutation',
    ),
    (
        "M3 no blank/positional rejection",
        UTIL,
        '    if path == "" or path in _POSITIONAL_DIRS:',
        '    if False:  # mutation',
    ),
    (
        "M4 naive prefix strip (original path[4:])",
        UTIL,
        '    if path.startswith(_LONG_PATH_UNC_PREFIX):',
        '    if False:  # mutation',
    ),
    (
        "M5 bytes decoded as mbcs (original)",
        UTIL,
        "    if isinstance(path, bytes):\n        path = os.fsdecode(path)",
        "    if isinstance(path, bytes):\n        path = path.decode('mbcs')",
    ),
    (
        "M6 trailing-separator guard removed",
        UTIL,
        "    if had_trailing_sep and os.path.exists(normalized) and not os.path.isdir(normalized):",
        "    if False:  # mutation",
    ),
    (
        "M7 legacy skips normalisation",
        LEGACY,
        "    paths = [normalize_win32_path(path) for path in paths]",
        "    paths = [str(path, 'mbcs') if not isinstance(path, str) else path for path in paths]",
    ),
    (
        "M8 modern skips normalisation",
        MODERN,
        "    paths = [normalize_win32_path(path) for path in paths]",
        "    paths = [str(path, 'mbcs') if not isinstance(path, str) else path for path in paths]",
    ),
    (
        "M9 CoInitialize outside try (original leak)",
        MODERN,
        "    pythoncom.CoInitialize()\n    try:\n        _delete_items(paths)\n    finally:",
        "    pythoncom.CoInitialize()\n    _delete_items(paths)\n    try:\n        pass\n    finally:",
    ),
    (
        "M10 com_error not converted (except clause narrowed)",
        MODERN,
        "    except pywintypes.com_error as error:",
        "    except ZeroDivisionError as error:",
    ),
]


def run_suite(root):
    proc = subprocess.run(
        [PY, "-m", "pytest", TESTFILE, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main():
    base = tempfile.mkdtemp(prefix="s2t_mut_")
    results = []

    # Control: the unmutated patched tree must be green, otherwise every
    # "killed" verdict below would be meaningless.
    control = os.path.join(base, "control")
    shutil.copytree(ROOT, control, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".audit_tools"))
    rc, out = run_suite(control)
    control_ok = rc == 0
    print(f"CONTROL (unmutated): {'GREEN' if control_ok else 'RED -- abort'}")
    if not control_ok:
        print(out[-3000:])
        return 1

    for idx, (label, relpath, old, new) in enumerate(MUTATIONS, 1):
        work = os.path.join(base, f"m{idx}")
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".audit_tools"))
        target = os.path.join(work, relpath)
        with open(target, encoding="utf-8") as handle:
            source = handle.read()
        if old not in source:
            print(f"[SKIP] {label}: anchor not found")
            results.append((label, "ANCHOR-MISSING"))
            continue
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(source.replace(old, new, 1))

        rc, out = run_suite(work)
        killed = rc != 0
        # Count failures rather than trusting the return code alone.
        match = re.search(r"(\d+) failed", out)
        n_failed = int(match.group(1)) if match else 0
        verdict = "KILLED" if killed else "SURVIVED"
        print(f"[{verdict}] {label}  (failed={n_failed})")
        results.append((label, verdict))
        shutil.rmtree(work, ignore_errors=True)

    killed = sum(1 for _, v in results if v == "KILLED")
    total = len(results)
    print(f"\nMutation score: {killed}/{total}")
    survivors = [label for label, v in results if v != "KILLED"]
    if survivors:
        print("Survivors / problems:")
        for label in survivors:
            print("  -", label)
    shutil.rmtree(base, ignore_errors=True)
    return 0 if killed == total else 2


if __name__ == "__main__":
    sys.exit(main())
