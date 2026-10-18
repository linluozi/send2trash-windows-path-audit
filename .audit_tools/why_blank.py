"""Why does the blank-path e2e test pass even with the guard removed?

Hypothesis: the destructive call fails for an unrelated reason (the CWD is in
use), so `pytest.raises(OSError)` is satisfied by the wrong exception.
"""
import os
import subprocess
import sys
import tempfile

PY = sys.executable


def run(pkg_label, pkg, execute_mutation):
    base = tempfile.mkdtemp(prefix="why_")
    cwd_dir = os.path.join(base, "empty_cwd")
    os.makedirs(cwd_dir)
    code = (
        "import os,sys,errno\n"
        f"sys.path.insert(0, {pkg!r})\n"
        f"os.chdir({cwd_dir!r})\n"
        "from send2trash.win.legacy import send2trash as fn\n"
        "try:\n"
        "    fn('')\n"
        "    print('NO EXCEPTION - cwd was trashed')\n"
        "except BaseException as e:\n"
        "    print('ERRNO', getattr(e, 'errno', None), '| type', type(e).__name__)\n"
        "    print('MSG', str(e)[:90])\n"
    )
    proc = subprocess.run([PY, "-c", code], capture_output=True, text=True, cwd=base)
    print(f"--- {pkg_label} ---")
    print(proc.stdout.strip() or proc.stderr.strip()[:200])
    print("empty cwd survived:", os.path.exists(cwd_dir))


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(os.path.dirname(ROOT), ".baseline-s2t", "src")
run("BASELINE (guard absent)", BASELINE, False)
run("PATCHED (guard present)", ROOT, True)
