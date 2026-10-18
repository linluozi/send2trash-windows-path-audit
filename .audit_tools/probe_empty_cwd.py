"""Can the buggy code actually delete an EMPTY cwd? Determines if the e2e test bites."""
import os
import subprocess
import sys
import tempfile

PKG = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PY = sys.executable

base = tempfile.mkdtemp(prefix="s2t_emptycwd_")

for label in ("legacy", "modern"):
    victim = os.path.join(base, "empty_" + label)
    os.makedirs(victim)  # deliberately EMPTY: nothing else holds it open
    code = (
        "import os,sys\n"
        f"sys.path.insert(0, {PKG!r})\n"
        f"os.chdir({victim!r})\n"
        f"from send2trash.win.{label} import send2trash as fn\n"
        "try:\n"
        "    fn('')\n"
        "    print('RETURNED OK')\n"
        "except BaseException as e:\n"
        "    print(type(e).__name__, getattr(e, 'strerror', ''), getattr(e, 'errno', ''))\n"
    )
    proc = subprocess.run([PY, "-c", code], capture_output=True, text=True, cwd=base)
    print(f"{label:7s} out={proc.stdout.strip()!r} err={proc.stderr.strip()[:120]!r}")
    print(f"        empty cwd still exists: {os.path.exists(victim)}")
