==================================================
Send2Trash -- Send files to trash on all platforms
==================================================

Send2Trash is a small package that sends files to the Trash (or Recycle Bin) *natively* and on
*all platforms*. On OS X, it uses native ``FSMoveObjectToTrashSync`` Cocoa calls or can use pyobjc 
with NSFileManager. On Windows, it uses native ``IFileOperation`` call if on Vista or newer and 
pywin32 is installed or falls back to ``SHFileOperation`` calls. On other platforms, if `PyGObject`_ 
and `GIO`_ are available, it will use this.  Otherwise, it will fallback to its own implementation of 
the `trash specifications from freedesktop.org`_.

``ctypes`` is used to access native libraries, so no compilation is necessary.

Send2Trash supports Python 3 (versions before 2.x support Python 2).

Status: Additional Help Welcome
-------------------------------

Additional help is welcome for supporting this package.  Specifically help with the OSX and Linux 
issues and fixes would be most appreciated.

Installation
------------

You can download it with pip:

    python -m pip install -U send2trash

To install with pywin32 or pyobjc required specify the extra `nativeLib`:

    python -m pip install -U send2trash[nativeLib]

or download the source from https://github.com/arsenetar/send2trash and install it with:

    python -m pip install -e .

On systems where Python enforces PEP 668 (e.g., recent Linux distributions),
installing packages into the system Python may be restricted.
Use a virtual environment:

    python -m venv .venv

    GNU/Linux / macOS:

        source .venv/bin/activate

    Windows:

        .venv\Scripts\activate

Usage
-----

>>> from send2trash import send2trash
>>> send2trash('some_file')
>>> send2trash(['some_file1', 'some_file2'])

On Freedesktop platforms (Linux, BSD, etc.), you may not be able to efficiently
trash some files. In these cases, an exception ``send2trash.TrashPermissionError``
is raised, so that the application can handle this case. This inherits from
``PermissionError``. Specifically, this affects
files on a different device to the user's home directory, where the root of the
device does not have a ``.Trash`` directory, and we don't have permission to
create a ``.Trash-$UID`` directory.

For any other problem, ``OSError`` is raised.

Path handling on Windows
------------------------

The Windows backends canonicalise every path before handing it to the shell,
because the shell accepts only a plain backslash-separated absolute path, and
because ``send2trash`` deletes: a path that silently resolves somewhere else is
worse than an error. Relative paths, ``/`` separators, ``.``/``..`` components,
redundant separators and a trailing separator on a directory are all accepted
and normalised away. ``bytes`` paths are decoded with the filesystem encoding
(UTF-8 since PEP 529), not the ANSI codepage.

Two surfaces are refused rather than resolved:

* ``''``, ``'.'`` and ``'..'``. ``os.path.abspath`` resolves them to the process
  working directory, so accepting them means trashing whatever the process
  happens to be sitting in. On Freedesktop platforms the same call raises
  ``ENOENT``, and the Windows backends now match.
* A path with an embedded NUL (``ValueError``), and a trailing separator on an
  existing non-directory (``OSError``, as on POSIX where ``exists()`` is
  ``False`` for such a path). Both name no file; acting on a prefix of them
  would delete something the caller did not name.

A ``\\?\`` long-path prefix is translated into its plain form when one exists
(``\\?\C:\dir\f`` becomes ``C:\dir\f``, ``\\?\UNC\srv\share\f`` becomes
``\\srv\share\f``) and kept for forms that have none, such as
``\\?\Volume{GUID}\``. Paths longer than ``MAX_PATH`` keep working.

.. _PyGObject: https://wiki.gnome.org/PyGObject
.. _GIO: https://developer.gnome.org/gio/
.. _trash specifications from freedesktop.org: http://freedesktop.org/wiki/Specifications/trash-spec/
