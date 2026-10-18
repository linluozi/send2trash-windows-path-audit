r"""End-to-end: does a real `\\?\UNC\` path now reach the shell in a usable form,
and do long paths (>MAX_PATH) still work after prefix translation?
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from send2trash.util import normalize_win32_path

BS = "\\"

print("=== translation table ===")
cases = [
    BS * 2 + "?" + BS + BS + "localhost" + BS + "C$" + BS + "temp" + BS + "f.txt",
    BS * 2 + "?" + BS + "C:" + BS + "temp" + BS + "f.txt",
    BS * 2 + "?" + BS + "Volume{1234}" + BS + "f.txt",
    BS * 2 + BS + "localhost" + BS + "C$" + BS + "temp" + BS + "f.txt",
    "C:" + BS + "temp" + BS + "f.txt",
]
for c in cases:
    n = normalize_win32_path(c)
    print(f"{c!r:52s} -> {n!r:40s} isabs={os.path.isabs(n)}")

print()
print("=== long path (>MAX_PATH) keeps working ===")
base = tempfile.mkdtemp(prefix="s2t_long_")
deep = os.path.join(base, "A" * 90, "B" * 90, "C" * 90)
long_file = os.path.join(deep, "D" * 90 + ".txt")
print("path length:", len(long_file), "exceeds MAX_PATH:", len(long_file) > 260)

os.makedirs("\\\\?\\" + deep)
with open("\\\\?\\" + long_file, "w", encoding="utf-8") as fh:
    fh.write("x")
print("created:", os.path.exists("\\\\?\\" + long_file))

normalized = normalize_win32_path("\\\\?\\" + long_file)
print("normalized len:", len(normalized), "| prefix stripped:", not normalized.startswith(BS * 2 + "?"))
print("still names the same file:", os.path.exists(normalized))

from send2trash.win.legacy import send2trash as legacy
from send2trash.win.modern import send2trash as modern

for label, fn in (("legacy", legacy), ("modern", modern)):
    target = "\\\\?\\" + long_file.replace(os.path.basename(long_file), label + ".txt")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("x")
    try:
        fn(target)
        verdict = "trashed"
    except BaseException as e:
        verdict = f"{type(e).__name__}: {str(e)[:70]}"
    print(f"{label:7s} long path -> {verdict}; still exists: {os.path.exists(target)}")
