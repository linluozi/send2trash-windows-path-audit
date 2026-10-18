"""Is the wrong-target bug destructive? Test `'..'`, whose target the process
does NOT hold open as its own cwd.
"""
import os
import subprocess
import sys
import tempfile

PY = sys.executable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(os.path.dirname(ROOT), ".baseline-s2t", "src")

for label, pkg in (("BASELINE", BASELINE), ("PATCHED", ROOT)):
    for backend in ("legacy", "modern"):
        base = tempfile.mkdtemp(prefix="dd_")
        # parent/child; the child is cwd, so `..` is the parent, unheld by us.
        parent = os.path.join(base, "parent")
        child = os.path.join(parent, "child")
        os.makedirs(child)
        victim = os.path.join(parent, "precious.txt")
        with open(victim, "w") as fh:
            fh.write("irreplaceable")

        code = (
            "import os,sys\n"
            f"sys.path.insert(0, {pkg!r})\n"
            f"os.chdir({child!r})\n"
            f"from send2trash.win.{backend} import send2trash as fn\n"
            "try:\n"
            "    fn('..')\n"
            "    print('NO EXCEPTION')\n"
            "except BaseException as e:\n"
            "    print(type(e).__name__, str(e)[:70])\n"
        )
        proc = subprocess.run([PY, "-c", code], capture_output=True, text=True, cwd=base)
        print(f"{label:9s} {backend:7s} {proc.stdout.strip()[:78]:80s} "
              f"parent_exists={os.path.exists(parent)} precious_exists={os.path.exists(victim)}")
