"""Do the new tests fail on the ORIGINAL code? Required evidence for the report.

Runs the new test module against the pristine upstream tree by copying the
tests in. Along the way, verify the tests fail for the *right* reason.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASELINE = os.path.join(os.path.dirname(ROOT), ".baseline-s2t", "src")
PY = os.path.join(os.path.dirname(ROOT), ".venv-s2t", "Scripts", "python.exe")

work = tempfile.mkdtemp(prefix="baseline_tests_")
target = os.path.join(work, "src")
shutil.copytree(BASELINE, target, ignore=shutil.ignore_patterns(".git", "__pycache__"))
shutil.copy2(
    os.path.join(ROOT, "tests", "test_win_path_handling.py"),
    os.path.join(target, "tests", "test_win_path_handling.py"),
)

print("baseline commit:", subprocess.run(
    ["git", "-C", BASELINE, "rev-parse", "--short", "HEAD"],
    capture_output=True, text=True).stdout.strip())
print("patched util.py sha1 vs baseline util.py differ:",
      open(os.path.join(ROOT, "send2trash", "util.py"), "rb").read()
      != open(os.path.join(target, "send2trash", "util.py"), "rb").read())
print()

proc = subprocess.run(
    [PY, "-m", "pytest", os.path.join("tests", "test_win_path_handling.py"),
     "-q", "--no-header", "-p", "no:cacheprovider", "--tb=no"],
    cwd=target, capture_output=True, text=True,
)
lines = proc.stdout.strip().splitlines()
print("\n".join(lines[-4:]))

failed = [ln for ln in lines if ln.startswith("FAILED")]
print(f"\n{len(failed)} failed on unpatched source:")
for ln in failed:
    print("  ", ln.replace("tests/test_win_path_handling.py::", "").split(" - ")[0])

shutil.rmtree(work, ignore_errors=True)
