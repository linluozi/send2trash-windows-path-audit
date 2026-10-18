"""Differential harness: run the same scenarios against baseline and patched.

Prints a side-by-side verdict per scenario so the report can quote observed
behaviour rather than reasoning.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(os.path.dirname(ROOT), ".baseline-s2t", "src")
PATCHED = ROOT
PY = os.path.join(os.path.dirname(ROOT), ".venv-s2t", "Scripts", "python.exe")

BS = "\\"

# Each scenario runs in its own process so a COM/apartment change cannot leak.
SCENARIO = r'''
import os, sys, traceback
pkg, backend_name, kind = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, pkg)
base = os.environ["SANDBOX"]
if backend_name == "public":
    from send2trash import send2trash as fn
else:
    mod = __import__("send2trash.win." + backend_name, fromlist=["send2trash"])
    fn = mod.send2trash

d = os.path.join(base, "case")
os.makedirs(d, exist_ok=True)
target = os.path.join(d, "f.txt")
with open(target, "w", encoding="utf-8") as fh:
    fh.write("x")
# Non-ASCII name: an ASCII path decodes identically under both mbcs and UTF-8,
# so only this variant can expose the ANSI-codepage bug.
accented = os.path.join(d, "caf\u00e9-\U0001f607.txt")
with open(accented, "w", encoding="utf-8") as fh:
    fh.write("x")
tdir = os.path.join(d, "sub")
os.makedirs(tdir, exist_ok=True)
with open(os.path.join(tdir, "inner.txt"), "w") as fh:
    fh.write("x")

victim_cwd = os.path.join(base, "cwd")
os.makedirs(victim_cwd, exist_ok=True)
open(os.path.join(victim_cwd, "marker.txt"), "w").close()

def case(kind):
    if kind == "forward_slash":
        return target.replace("\\", "/"), target
    if kind == "dot_component":
        return os.path.join(d, ".", "f.txt"), target
    if kind == "dotdot_component":
        return os.path.join(d, "sub", "..", "f.txt"), target
    if kind == "dir_trailing_slash":
        return tdir + "/", tdir
    if kind == "file_trailing_slash":
        return target + "/", target
    if kind == "empty_string":
        os.chdir(victim_cwd)
        return "", victim_cwd
    if kind == "nul_byte":
        return target + "\x00junk", target
    if kind == "bytes_utf8":
        return os.fsencode(accented), accented
    if kind == "unc_long_prefix":
        # The harm needs a UNC tree that resolves relative to the CWD. Plant
        # one and check the *decoy* rather than the (nonexistent) share.
        decoy_dir = os.path.join(base, "UNC", "srv", "share")
        os.makedirs(decoy_dir, exist_ok=True)
        decoy = os.path.join(decoy_dir, "f.txt")
        open(decoy, "w").close()
        os.chdir(base)
        return "\\\\?\\UNC\\srv\\share\\f.txt", decoy
    raise SystemExit("unknown kind " + kind)

arg, expect_gone = case(kind)
try:
    fn(arg)
    outcome = "no-exception"
except BaseException as e:
    outcome = type(e).__name__
print(outcome)
print("gone=%s" % (not os.path.exists(expect_gone)))
'''


def run(pkg, backend, kind, sandbox):
    env = dict(os.environ, SANDBOX=sandbox)
    proc = subprocess.run(
        [PY, "-c", SCENARIO, pkg, backend, kind],
        capture_output=True, text=True, env=env, timeout=120,
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln]
    if len(lines) < 2:
        return "CRASH", f"stderr={proc.stderr.strip()[:80]}"
    return lines[0], lines[1]


KINDS = [
    "forward_slash",
    "dot_component",
    "dotdot_component",
    "dir_trailing_slash",
    "file_trailing_slash",
    "empty_string",
    "nul_byte",
    "bytes_utf8",
    "unc_long_prefix",
]

print(f"{'scenario':22s} {'backend':8s} {'BEFORE (2.1.0+)':46s} {'AFTER':46s}")
print("-" * 124)
for kind in KINDS:
    for backend in ("legacy", "modern"):
        b_sandbox = tempfile.mkdtemp(prefix="b_")
        a_sandbox = tempfile.mkdtemp(prefix="a_")
        before, b_state = run(BASELINE, backend, kind, b_sandbox)
        after, a_state = run(PATCHED, backend, kind, a_sandbox)
        b = f"{before} / {'DELETED' if b_state == 'gone=True' else 'kept'}"
        a = f"{after} / {'DELETED' if a_state == 'gone=True' else 'kept'}"
        mark = "" if (b_state == "gone=True") == (a_state == "gone=True") else "  <== CHANGED"
        print(f"{kind:22s} {backend:8s} {b:46s} {a:46s}{mark}")
