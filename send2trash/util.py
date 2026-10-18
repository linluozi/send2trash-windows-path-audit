# Copyright 2017 Virgil Dupras
# Copyright 2026 the send2trash contributors
#
# This software is licensed under the "BSD" License as described in the "LICENSE" file,
# which should be included with this package. The terms are also available at
# http://www.hardcoded.net/licenses/bsd_license

import collections.abc
import errno
import os


def preprocess_paths(paths):
    if isinstance(paths, collections.abc.Iterable) and not isinstance(paths, (str, bytes)):
        paths = list(paths)
    else:
        paths = [paths]
    # Convert items such as pathlib paths to strings
    return [os.fspath(path) for path in paths]


#: The Win32 long-path prefix, and the form it takes for UNC paths. Both are
#: accepted from callers and both have to be translated before reaching the
#: shell, which understands neither.
_LONG_PATH_PREFIX = "\\\\?\\"
_LONG_PATH_UNC_PREFIX = "\\\\?\\UNC\\"

#: Directory references that name a location by position instead of by name.
#: ``os.path.abspath`` resolves them to the process working directory (and its
#: parent), so trashing them means trashing whatever the process happens to be
#: sitting in. They are refused rather than resolved.
_POSITIONAL_DIRS = frozenset((".", "..", "./", "../", ".\\", "..\\"))


def normalize_win32_path(path):
    r"""Return *path* in the canonical form the Windows shell APIs accept.

    A single place to turn whatever the caller passed into the one shape both
    Windows backends can hand to the operating system. This matters more than
    it looks: ``send2trash`` deletes, so a path that silently resolves to a
    *different* file is worse than an error.

    The transformations, in order:

    1. ``bytes`` are decoded with :func:`os.fsdecode`, i.e. the filesystem
       encoding, which PEP 529 made UTF-8 on Windows. The backends used the
       ANSI codepage (``mbcs``) instead, which mangles every non-ASCII name
       on a non-UTF-8 ANSI codepage.
    2. An embedded NUL is rejected. The shell stops parsing at the NUL, so
       ``'real.txt\0anything'`` used to trash ``real.txt`` and report
       success -- acting on a prefix of a string that names no file at all.
    3. ``''``, ``'.'`` and ``'..'`` are rejected. ``abspath('')`` is the
       working directory, so ``send2trash('')`` asked the shell to recycle
       the process's own CWD. POSIX raises ``ENOENT`` for the same call.
    4. The path is made absolute and normalised: ``/`` becomes ``\``,
       ``.``/``..`` components are resolved and redundant separators are
       collapsed. Previously ``abspath`` was only called for *relative*
       paths, so an absolute path kept whatever separators and dot
       components the caller supplied, and the shell rejected it
       (``WinError 123`` / ``0x80070057``).
    5. A trailing separator is preserved only for directories. ``'dir/'``
       used to reach the shell verbatim and be refused; stripping it
       unconditionally would be worse, because ``'file.txt/'`` names no
       file and would start deleting ``file.txt``.
    6. A ``\\?\`` prefix is translated when it has an equivalent plain form.
       Dropping the prefix by slicing, as the modern backend did, turns
       ``\\?\UNC\srv\share\f`` into the *relative* path ``UNC\srv\share\f``,
       which resolves against the CWD. ``\\?\UNC\`` therefore becomes
       ``\\``, and ``\\?\X:\`` becomes ``X:\``. Forms with no plain
       equivalent, such as ``\\?\Volume{GUID}\``, keep their prefix.

    Args:
        path: A :class:`str`, :class:`bytes` or :class:`os.PathLike` naming
            the file or directory to trash.

    Returns:
        The absolute, normalised path as a :class:`str`.

    Raises:
        ValueError: *path* contains an embedded NUL.
        OSError: *path* is ``''``, ``'.'`` or ``'..'``, or it ends with a
            separator but names an existing non-directory.
    """
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    else:
        path = os.fspath(path)
        if isinstance(path, bytes):
            path = os.fsdecode(path)

    if "\x00" in path:
        raise ValueError(f"embedded null byte in path: {path!r}")

    if path == "" or path in _POSITIONAL_DIRS:
        # `''` has no meaning of its own and `.`/`..` name a location
        # relative to the working directory. Resolving either would hand the
        # shell a directory the caller never named; POSIX raises ENOENT.
        raise OSError(
            errno.ENOENT,
            f"refusing to trash {path!r}: it does not name a file or directory",
            path,
        )

    # Trailing separators have to be inspected before normalisation eats
    # them: after the fact `file.txt/` is indistinguishable from `file.txt`.
    stripped = path.rstrip("\\/")
    had_trailing_sep = len(stripped) != len(path)

    normalized = os.path.normpath(os.path.abspath(path))

    if had_trailing_sep and os.path.exists(normalized) and not os.path.isdir(normalized):
        # `file.txt/` is not a path to `file.txt`, exactly as on POSIX, where
        # the same argument raises ENOENT because `exists()` is False for it.
        raise OSError(
            errno.ENOENT,
            f"not a directory: {path!r}",
            path,
        )

    return _strip_long_path_prefix(normalized)


def _strip_long_path_prefix(path):
    r"""Translate a ``\\?\`` prefix into its plain equivalent, if it has one.

    ``\\?\UNC\srv\share\f`` -> ``\\srv\share\f``
    ``\\?\C:\dir\f``       -> ``C:\dir\f``
    ``\\?\Volume{GUID}\f`` -> unchanged, the prefix is the only way to name it
    """
    if path.startswith(_LONG_PATH_UNC_PREFIX):
        # `\\?\UNC` plus one backslash, replaced by `\\` alone. Naive
        # `path[4:]` would leave the relative `UNC\...`, which resolves
        # against the working directory.
        return "\\\\" + path[len(_LONG_PATH_UNC_PREFIX):]

    if path.startswith(_LONG_PATH_PREFIX):
        remainder = path[len(_LONG_PATH_PREFIX):]
        # Only a drive-absolute remainder has a plain form.
        if len(remainder) >= 3 and remainder[1] == ":" and remainder[2] in "\\/":
            return remainder
        return path

    return path
