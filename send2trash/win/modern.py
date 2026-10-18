# Copyright 2017 Virgil Dupras

# This software is licensed under the "BSD" License as described in the "LICENSE" file,
# which should be included with this package. The terms are also available at
# http://www.hardcoded.net/licenses/bsd_license

from platform import version
import pythoncom
import pywintypes
from win32com.shell import shell, shellcon
from send2trash.util import normalize_win32_path, preprocess_paths
from send2trash.win.IFileOperationProgressSink import create_sink


def send2trash(paths):
    paths = preprocess_paths(paths)
    if not paths:
        return
    # Canonicalise for the shell item parser, which accepts only a plain
    # backslash-separated absolute path. The old code dropped a `\\?\` prefix
    # by slicing, which turned `\\?\UNC\srv\share\f` into the *relative*
    # `UNC\srv\share\f` and let it resolve against the working directory.
    paths = [normalize_win32_path(path) for path in paths]
    # Need to initialize the com before using
    pythoncom.CoInitialize()
    try:
        _delete_items(paths)
    finally:
        # One CoUninitialize per CoInitialize, and only after the matching
        # call succeeded. Initialising outside the try leaked the apartment
        # reference count whenever the step in between failed.
        pythoncom.CoUninitialize()


def _delete_items(paths):
    """Run the delete operation for already-normalised `paths`.

    The whole body is guarded, not just the loop: `CoCreateInstance` and
    `SetOperationFlags` can fail too, and they raise `pywintypes.com_error`,
    which is not an `OSError` subclass. Callers are documented to catch
    `OSError`, so an unwrapped failure from either would escape them.
    """
    try:
        # create instance of file operation object
        fileop = pythoncom.CoCreateInstance(
            shell.CLSID_FileOperation,
            None,
            pythoncom.CLSCTX_ALL,
            shell.IID_IFileOperation,
        )
        # default flags to use
        flags = shellcon.FOF_NOCONFIRMATION | shellcon.FOF_NOERRORUI | shellcon.FOF_SILENT
        flags |= shellcon.FOFX_EARLYFAILURE
        # determine rest of the flags based on OS version
        # use newer recommended flags if available
        if int(version().split(".", 1)[0]) >= 8:
            flags |= 0x20000000 | 0x00080000  # FOFX_ADDUNDORECORD win 8+  # FOFX_RECYCLEONDELETE win 8+
        else:
            flags |= shellcon.FOF_ALLOWUNDO
        # set the flags
        fileop.SetOperationFlags(flags)
        # actually try to perform the operation, this section may throw a
        # pywintypes.com_error which does not seem to create as nice of an
        # error as OSError so wrapping with try to convert
        sink = create_sink()
        for path in paths:
            item = shell.SHCreateItemFromParsingName(path, None, shell.IID_IShellItem)
            fileop.DeleteItem(item, sink)
        result = fileop.PerformOperations()
        aborted = fileop.GetAnyOperationsAborted()
        # if non-zero result or aborted throw an exception
        if result or aborted:
            raise OSError(None, None, paths, result)
    except pywintypes.com_error as error:
        # convert to standard OS error, allows other code to get a
        # normal errno
        raise OSError(None, error.strerror, paths, error.hresult) from error
