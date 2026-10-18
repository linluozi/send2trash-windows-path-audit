# Copyright 2017 Virgil Dupras
# Copyright 2026 the send2trash contributors
#
# This software is licensed under the "BSD" License as described in the "LICENSE" file,
# which should be included with this package. The terms are also available at
# http://www.hardcoded.net/licenses/bsd_license

"""Regression tests for Windows path handling.

Every test here corresponds to a defect that was reproduced against the
unpatched 2.1.0+ source: the path the caller passes is not the path that
reaches the Win32/Shell API. ``send2trash`` deletes, so a path that silently
resolves somewhere else can destroy the wrong file.

The tests drive the real backends against real files in a temporary
directory, so they fail for the same reason a user would: the file is still
there, the wrong file is gone, or an exception escaped.
"""

import errno
import os
import os.path as op
import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Skipping windows-only tests", allow_module_level=True)

from send2trash.win.legacy import send2trash as s2t_legacy
from send2trash.win.modern import send2trash as s2t_modern

BACKENDS = [
    pytest.param(s2t_legacy, id="legacy"),
    pytest.param(s2t_modern, id="modern"),
]

BS = "\\"


@pytest.fixture(name="sandbox")
def fixture_sandbox(tmp_path):
    """A private tree to trash things from, removed afterwards."""
    yield str(tmp_path)


def _make_file(directory, name="target.txt"):
    """Create `name` inside `directory` and return its path."""
    path = op.join(directory, name)
    with open(path, "w", encoding="utf-8") as writer:
        writer.write("send2trash regression fixture")
    return path


def _make_dir(directory, name="targetdir"):
    """Create `name` inside `directory` with one file and return its path."""
    path = op.join(directory, name)
    os.makedirs(path)
    _make_file(path, "inner.txt")
    return path


# --------------------------------------------------------------------------
# 1. A path that is absolute but not normalised used to skip normalisation.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(lambda p: p.replace(BS, "/"), id="forward-slashes"),
        pytest.param(
            lambda p: op.dirname(p) + BS + "." + BS + op.basename(p),
            id="dot-component",
        ),
        pytest.param(
            lambda p: op.dirname(p) + BS + ".." + BS + op.basename(op.dirname(p)) + BS + op.basename(p),
            id="dotdot-component",
        ),
        pytest.param(
            lambda p: op.dirname(p).replace(BS, "/") + "/./" + op.basename(p),
            id="forward-slashes-and-dot",
        ),
        pytest.param(
            lambda p: op.dirname(p) + BS + BS + op.basename(p),
            id="doubled-separator",
        ),
    ],
)
def test_absolute_path_variants_are_trashed(backend, sandbox, mangle):
    """Absolute paths with separators or dot components must still resolve.

    ``abspath`` was only called for relative paths, so any absolute path kept
    whatever separators and ``.``/``..`` components the caller supplied. The
    Win32 and Shell APIs do not normalise those, and the file survived while
    an exception escaped.
    """
    target = _make_file(sandbox)
    backend(mangle(target))
    assert op.exists(target) is False


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("suffix", [BS, "/", BS + BS])
def test_directory_with_trailing_separator_is_trashed(backend, sandbox, suffix):
    """A trailing separator on a directory must not turn into an error.

    ``'dir/'`` reached the API verbatim, which rejects it: legacy raised
    ``WinError 123``, modern ``WinError -2147024809``, and the directory
    stayed on disk.
    """
    target = _make_dir(sandbox)
    backend(target + suffix)
    assert op.exists(target) is False


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("suffix", [BS, "/"])
def test_file_with_trailing_separator_is_rejected_not_ignored(backend, sandbox, suffix):
    """``'file.txt/'`` names nothing on Windows, so it must not delete the file.

    Accepting it silently would be worse than refusing it: the caller believes
    a *directory* was trashed while a file disappeared.
    """
    target = _make_file(sandbox)
    with pytest.raises(OSError):
        backend(target + suffix)
    assert op.exists(target) is True


# --------------------------------------------------------------------------
# 2. An empty path was resolved to the current working directory.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("blank", ["", ".", ".."])
def test_blank_path_is_rejected(backend, sandbox, blank, monkeypatch):
    """``''``, ``'.'`` and ``'..'`` are not files and must be refused.

    ``op.abspath('')`` returns the CWD, so ``send2trash('')`` asked the shell
    to recycle the process's working directory. Windows happens to refuse that
    for its own reasons (the CWD is in use), so asserting "an OSError was
    raised" is not enough: it would also pass on the buggy code. The real
    requirement is that the backend never reaches the shell at all, which is
    what this test checks by counting the calls.

    On POSIX the same call raises ``ENOENT`` before any filesystem work, so
    refusing early is also the cross-platform-consistent behaviour.
    """
    victim = _make_dir(sandbox, "cwd_victim")
    inner = op.join(victim, "inner.txt")

    reached = []

    if backend is s2t_legacy:
        # The last thing legacy does before calling SHFileOperationW.
        def spy(path):
            reached.append(path)
            raise AssertionError(f"shell reached with {path!r}")

        monkeypatch.setattr("send2trash.win.legacy.get_short_path_name", spy)
    else:

        def spy(*args, **kwargs):
            reached.append(args[0] if args else None)
            raise AssertionError(f"shell reached with {args!r}")

        monkeypatch.setattr("send2trash.win.modern.shell.SHCreateItemFromParsingName", spy)

    previous = os.getcwd()
    os.chdir(victim)
    try:
        with pytest.raises(OSError):
            backend(blank)
    finally:
        os.chdir(previous)

    assert reached == [], f"backend must refuse {blank!r} before touching the shell, got {reached}"
    assert op.isdir(victim) is True, "the working directory must survive"
    assert op.exists(inner) is True


# --------------------------------------------------------------------------
# 3. ``\\?\UNC\...`` was stripped to a *relative* path.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
def test_unc_long_path_prefix_is_not_stripped_into_a_relative_path(backend, sandbox, monkeypatch):
    r"""Stripping ``\\?\`` from ``\\?\UNC\srv\share\f`` leaves ``UNC\srv\share\f``.

    That is a relative path, so it resolves against the CWD. A file planted at
    ``./UNC/srv/share/f`` is exactly what a caller would never authorise, and
    the operation then either fails with a confusing ``FileNotFoundError`` or,
    once such a tree exists, removes the local file.

    The decoy must survive *and* the shell must never be asked about a path
    derived from the CWD, which is what the call spy enforces: on the buggy
    code the decoy happened to be kept only because the shell rejected the
    relative path outright.
    """
    decoy_dir = op.join(sandbox, "UNC", "srv", "share")
    os.makedirs(decoy_dir)
    decoy = _make_file(decoy_dir, "f.txt")

    seen = []
    if backend is s2t_legacy:

        def spy(path):
            seen.append(path)
            raise OSError(errno.ENOENT, "stop after observing the path", path)

        monkeypatch.setattr("send2trash.win.legacy.get_short_path_name", spy)
    else:

        def spy(path, *args, **kwargs):
            seen.append(path)
            raise OSError(errno.ENOENT, "stop after observing the path", path)

        monkeypatch.setattr("send2trash.win.modern.shell.SHCreateItemFromParsingName", spy)

    previous = os.getcwd()
    os.chdir(sandbox)
    try:
        with pytest.raises(OSError):
            backend(BS * 2 + "?" + BS + "UNC" + BS + "srv" + BS + "share" + BS + "f.txt")
    finally:
        os.chdir(previous)

    assert op.exists(decoy) is True, "the local decoy must never be touched"
    assert seen, "the call should have been attempted"
    for path in seen:
        assert op.isabs(path), f"only absolute paths may reach the shell, got {path!r}"
        assert not path.lower().startswith(BS + BS + "?"), (
            f"the shell does not accept a long-path prefix, got {path!r}"
        )
        assert "UNC" + BS not in path.upper() or path.upper().startswith(BS * 2), (
            f"a stripped UNC prefix resolves against the CWD, got {path!r}"
        )


# --------------------------------------------------------------------------
# 4. An embedded NUL silently truncated the path.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
def test_embedded_nul_is_rejected(backend, sandbox):
    """``'target.txt\\x00suffix'`` is not a path; it must not delete target.txt.

    The Shell item parser stops at the NUL, so the modern backend trashed the
    file named by the prefix and reported success. Accepting a string that
    names no file and acting on a prefix of it is the worst failure mode
    available here.
    """
    target = _make_file(sandbox)
    with pytest.raises((OSError, ValueError)):
        backend(target + "\x00injected.txt")
    assert op.exists(target) is True


# --------------------------------------------------------------------------
# 5. Bytes paths were decoded with the ANSI codepage.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
def test_bytes_path_uses_the_filesystem_encoding(backend, sandbox):
    """PEP 529 made the Windows FS encoding UTF-8; ``mbcs`` is the ANSI page.

    A UTF-8 bytes path was decoded as ``mbcs``, which mangles every non-ASCII
    name on a non-UTF-8 ANSI codepage (cp936 here), so the file was reported
    missing.
    """
    name = "caf\u00e9-\U0001f607.txt"
    target = _make_file(sandbox, name)
    backend(os.fsencode(target))
    assert op.exists(target) is False


# --------------------------------------------------------------------------
# 6. A COM apartment failure leaked the CoInitialize reference count.
# --------------------------------------------------------------------------


def test_modern_com_initialisation_is_balanced_on_failure(sandbox, monkeypatch):
    """Every ``CoInitialize`` must be paired with one ``CoUninitialize``.

    ``modern.send2trash`` initialised COM before entering the ``try`` that
    guarded the cleanup, so a failure in between left the apartment count
    raised forever. In a long-lived thread (notebook, GUI worker) the caller's
    own ``CoUninitialize`` then no longer tears the apartment down.

    A failure at ``CoCreateInstance`` also used to escape as
    ``pywintypes.com_error``, which is **not** an ``OSError`` subclass, so
    callers documented to catch ``OSError`` missed it entirely. Both are
    asserted here.
    """
    import pythoncom
    import pywintypes

    counts = {"init": 0, "uninit": 0}
    real_init = pythoncom.CoInitialize
    real_uninit = pythoncom.CoUninitialize

    def counting_init(*args, **kwargs):
        counts["init"] += 1
        return real_init(*args, **kwargs)

    def counting_uninit(*args, **kwargs):
        counts["uninit"] += 1
        return real_uninit(*args, **kwargs)

    def failing_create(*args, **kwargs):
        raise pywintypes.com_error(-2147221164, "class not registered", None, None)

    target = _make_file(sandbox)

    monkeypatch.setattr(pythoncom, "CoInitialize", counting_init)
    monkeypatch.setattr(pythoncom, "CoUninitialize", counting_uninit)
    monkeypatch.setattr(pythoncom, "CoCreateInstance", failing_create)

    # OSError is the documented contract; a bare com_error would slip past it.
    with pytest.raises(OSError):
        s2t_modern(target)

    assert counts["init"] == 1, "the failed call should have initialised once"
    assert counts["uninit"] == 1, "the failed call leaked a COM reference"
    assert op.exists(target) is True, "a failed operation must not remove the file"

    # A successful call must stay balanced too.
    counts["init"] = counts["uninit"] = 0
    monkeypatch.undo()
    monkeypatch.setattr(pythoncom, "CoInitialize", counting_init)
    monkeypatch.setattr(pythoncom, "CoUninitialize", counting_uninit)
    s2t_modern(target)
    assert counts == {"init": 1, "uninit": 1}, "successful call leaked a COM reference"
    assert op.exists(target) is False, "the file should have been trashed"


def test_modern_failure_does_not_leave_the_apartment_uninitialised(sandbox):
    """A caller's own apartment must survive a failed ``send2trash`` call.

    Runs in a subprocess so the reference count started here cannot leak into
    the test session.
    """
    import subprocess
    import textwrap

    script = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, %r)
        import pythoncom
        import pywintypes
        from send2trash.win.modern import send2trash

        pythoncom.CoInitialize()          # the caller's own apartment
        real = pythoncom.CoCreateInstance

        def boom(*a, **k):
            raise pywintypes.com_error(-2147221164, "boom", None, None)

        pythoncom.CoCreateInstance = boom
        try:
            send2trash(%r)
        except OSError:
            pass
        pythoncom.CoCreateInstance = real

        # One CoUninitialize must still be enough: if send2trash leaked a
        # reference, this leaves the apartment up and CoCreateInstance works.
        pythoncom.CoUninitialize()
        try:
            real(__import__("win32com.shell.shell", fromlist=["x"]).CLSID_FileOperation,
                 None, pythoncom.CLSCTX_ALL,
                 __import__("win32com.shell.shell", fromlist=["x"]).IID_IFileOperation)
            print("APARTMENT-LEAKED")
        except Exception:
            print("APARTMENT-CLEAN")
        """
    ) % (os.path.dirname(os.path.dirname(os.path.abspath(__file__))), _make_file(sandbox, "sub.txt"))

    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert "APARTMENT-CLEAN" in proc.stdout, (
        f"a failed call left the caller's COM apartment alive\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )


# --------------------------------------------------------------------------
# 7. The long-path prefix must be translated without losing long-path support.
# --------------------------------------------------------------------------


def test_long_path_prefix_translates_to_a_plain_absolute_path(sandbox):
    r"""``\\?\`` has to be translated, not sliced, and only when lossless.

    Two requirements pull in opposite directions:

    * the shell item parser rejects ``\\?\`` outright, so the prefix cannot be
      forwarded;
    * ``\\?\UNC\`` and ``\\?\Volume{GUID}\`` have no plain spelling, and
      slicing four characters off turns the first into a *relative* path.

    A drive-letter form has an exact plain equivalent and is translated.
    """
    from send2trash.util import normalize_win32_path

    drive = op.splitdrive(sandbox)[0] + BS
    assert normalize_win32_path(BS * 2 + "?" + BS + drive + "temp" + BS + "f.txt") == \
        drive + "temp" + BS + "f.txt"

    # UNC keeps the `\\` server prefix instead of becoming `UNC\...`.
    assert normalize_win32_path(BS * 2 + "?" + BS + "UNC" + BS + "srv" + BS + "share" + BS + "f") == \
        BS * 2 + "srv" + BS + "share" + BS + "f"

    # Volume GUIDs have no plain form, so the prefix must survive.
    volume = BS * 2 + "?" + BS + "Volume{1234-5678}" + BS + "f.txt"
    assert normalize_win32_path(volume) == volume


@pytest.mark.parametrize("backend", BACKENDS)
def test_path_longer_than_max_path_is_trashed(backend, sandbox):
    r"""Stripping the prefix must not break ``>MAX_PATH`` support.

    The legacy backend calls ``GetShortPathNameW``, which needs either an 8.3
    alias or the prefix to accept a long path; it re-adds the prefix itself in
    ``prefix_and_path``. This pins that behaviour so a future change to the
    normalisation cannot silently cap paths at ``MAX_PATH``.
    """
    seg = "A" * 60
    deep = sandbox
    while len(deep) < 300:
        deep = op.join(deep, seg)
    long_deep = BS * 2 + "?" + BS + deep
    os.makedirs(long_deep, exist_ok=True)
    target = op.join(deep, "f.txt")
    long_target = BS * 2 + "?" + BS + target
    assert len(target) > 260

    with open(long_target, "w", encoding="utf-8") as writer:
        writer.write("x")
    assert op.exists(long_target) is True

    backend(long_target)
    assert op.exists(long_target) is False


# --------------------------------------------------------------------------
# 8. The public entry point and the CLI must agree with the backends.
# --------------------------------------------------------------------------


def test_public_api_rejects_blank_path(sandbox):
    """The platform dispatch in ``send2trash/__init__.py`` must refuse ``''``."""
    from send2trash import send2trash

    victim = _make_dir(sandbox, "cwd_victim")
    previous = os.getcwd()
    os.chdir(victim)
    try:
        with pytest.raises(OSError):
            send2trash("")
    finally:
        os.chdir(previous)
    assert op.isdir(victim) is True


def test_cli_rejects_blank_path(sandbox, capsys):
    """``python -m send2trash ''`` must fail instead of trashing the CWD."""
    from send2trash.__main__ import main

    victim = _make_dir(sandbox, "cwd_victim")
    previous = os.getcwd()
    os.chdir(victim)
    try:
        with pytest.raises(SystemExit) as excinfo:
            main([""])
    finally:
        os.chdir(previous)

    assert excinfo.value.code == 1
    assert op.isdir(victim) is True
    assert "Trashed" not in capsys.readouterr().out
