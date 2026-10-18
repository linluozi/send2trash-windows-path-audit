"""Diagnose why three mutations survived: do they really change behaviour?"""
import os
import sys
import tempfile

sys.path.insert(0, os.environ["PKG"])

from send2trash.util import normalize_win32_path

BS = "\\"

cases = [
    "",
    ".",
    "..",
    "E:/a/b.txt",
    "E:/a/./b/../c",
    BS * 2 + "?" + BS + "UNC" + BS + "srv" + BS + "share" + BS + "f.txt",
    "E:" + BS + "a" + BS + "b.txt" + BS,
    "E:" + BS + "a" + BS + "b.txt" + "/",
]

for c in cases:
    try:
        print(f"{c!r:44s} -> {normalize_win32_path(c)!r}")
    except Exception as e:
        print(f"{c!r:44s} -> {type(e).__name__}: {e}")
