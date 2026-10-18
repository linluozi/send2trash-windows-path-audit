r"""Does stripping `\\?\` from legacy break paths beyond MAX_PATH?

Legacy calls GetShortPathNameW, which needs either an 8.3 alias or the
`\\?\` prefix to accept a path longer than MAX_PATH. The old code kept the
prefix for absolute input; the new code strips it. Prove whether that matters.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctypes import GetLastError, FormatError, create_unicode_buffer, windll

GetShortPathNameW = windll.kernel32.GetShortPathNameW

import send2trash.win.legacy as legacy_mod

for total in (200, 260, 280, 320, 400):
    seg = "A" * 60
    base = os.path.abspath(".")
    parts = []
    cur = base
    while len(cur) < total - 20:
        cur = os.path.join(cur, seg)
        parts.append(cur)
    deep = parts[-1]
    target = os.path.join(deep, "f.txt")

    try:
        os.makedirs("\\\\?\\" + deep)
    except FileExistsError:
        pass
    with open("\\\\?\\" + target, "w", encoding="utf-8") as fh:
        fh.write("x")

    plain = target
    prefixed = "\\\\?\\" + target

    def gspn(p):
        n = GetShortPathNameW(p, None, 0)
        if not n:
            return f"FAIL(GetLastError={GetLastError()})"
        buf = create_unicode_buffer(n)
        GetShortPathNameW(p, buf, n)
        return f"ok(len={len(buf.value)})"

    print(f"len={len(target):4d}  no-prefix: {gspn(plain):28s} prefixed: {gspn(prefixed)}")

    # And what the backend actually does now.
    try:
        normalized = legacy_mod.normalize_win32_path(prefixed)
        short = legacy_mod.get_short_path_name(normalized)
        print(f"          backend -> short name ok, len={len(short)}")
    except BaseException as exc:
        print(f"          backend -> {type(exc).__name__}: {str(exc)[:90]}")
