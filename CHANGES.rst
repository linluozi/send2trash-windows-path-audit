Changes
=======
Unreleased
----------
* Windows: canonicalise every path before it reaches the shell. Absolute paths
  used to skip normalisation, so ``/`` separators, ``.``/``..`` components,
  redundant separators and a trailing separator on a directory were forwarded
  verbatim and rejected by ``SHFileOperationW`` / ``IFileOperation``.
* Windows: refuse ``''``, ``'.'`` and ``'..'`` instead of resolving them to the
  process working directory, matching the ``ENOENT`` that Freedesktop platforms
  already raise. Refuse an embedded NUL and a trailing separator on an existing
  non-directory: both name no file, and the shell used to act on the prefix.
* Windows: decode ``bytes`` paths with the filesystem encoding (UTF-8 since
  PEP 529) instead of the ANSI codepage (``mbcs``), which mangled every
  non-ASCII name on a non-UTF-8 ANSI codepage.
* Windows: translate a ``\\?\`` prefix instead of slicing it. ``path[4:]``
  turned ``\\?\UNC\srv\share\f`` into the *relative* ``UNC\srv\share\f``, which
  resolved against the working directory. Paths beyond ``MAX_PATH`` still work.
* Windows: pair the modern backend's ``CoInitialize`` with exactly one
  ``CoUninitialize``. Initialising before the ``try`` leaked the apartment
  reference count whenever the step in between failed, and a failure there
  escaped as ``pywintypes.com_error``, which is not an ``OSError``.
* Add ``tests/test_win_path_handling.py`` covering all of the above against
  real files and both Windows backends.

Version 2.1.0 -- 2026/01/14
---------------------------
* Add `conftest.py` to source distribution by @mgorny in https://github.com/arsenetar/send2trash/pull/106
* Replacing elif, which is always True, with else by @PalmtopTiger in https://github.com/arsenetar/send2trash/pull/104
* Migrate to pyproject.toml from setup.cfg

Version 2.0.0 -- 2025/12/30
---------------------------
* Drop suport for Python 2
* Fix `test_trash_topdir` failing on macOS by @denini08 in https://github.com/arsenetar/send2trash/pull/100
* Update source installation instructions by @gunSlaveUnit in https://github.com/arsenetar/send2trash/pull/102
* Update gio implemenation, should fix #5 by no longer using deprecated GObject.GError

Version 1.8.3 -- 2024/04/06
---------------------------
* Add support for any iterable type as input by @PalmtopTiger in https://github.com/arsenetar/send2trash/pull/88
* fix: Use os.fsdecode() for arguments to shutil.move() by @yogeshiitm in https://github.com/arsenetar/send2trash/pull/90

Version 1.8.2 -- 2023/04/27
---------------------------
* win/legacy: tiny logic simplification by @BoboTiG in https://github.com/arsenetar/send2trash/pull/77
* TravisCI is not used anymore by @sobolevn in https://github.com/arsenetar/send2trash/pull/73
* fix(ci): Update to latest actions, fix python versions by @arsenetar in https://github.com/arsenetar/send2trash/pull/78

Version 1.8.1b0 -- 2021/09/20
-----------------------------
* Add fallback to HOMETRASH when cross device errors happen in plat_other (#26, #41, #63)

Version 1.8.0 -- 2021/08/08
---------------------------

* Add compatibility with pathlib paths (#49)
* Fix thread compatibility of modern windows implementation (#59)
* Fix handling of UNC names in legacy windows implementation  (#57)

Version 1.7.1 -- 2021/06/21
---------------------------

* Release stable version with changes from last 3 releases
* Fix handling of UNC names (#57)

Version 1.7.0a1 -- 2021/05/14
-----------------------------

* Changed conditional for when to try to use pyobjc version (#51)

Version 1.7.0a0 -- 2021/04/20
-----------------------------

* Add console_script entry point (#50)
* Increased python CI versions (#52, #54)
* Fix minor issue in setup.py (#53)
* Fix issue with windows tests importing modules on non-windows (#55)
* Unit test cleanups, rewrites, and flake8 cleanups
* Windows: Fix legacy windows platform for multi-byte unicode and add tests
* macOS: Add alternative pyobjc version to potentially improve compatibility (#51)

Version 1.6.0b1 -- 2020/06/18
-----------------------------

* Add main method which allows calling via ``python -m send2trash somefile``
* Windows: Add support for using IFileOperation when pywin32 is present on Vista and newer
* Add support for passing multiple files at once in a list
* Windows: Batch multi-file calls to improve performance (#42)
* Windows: Fix issue with SHFileOperation failing silently when path is not found (#33)

Version 1.5.0 -- 2018/02/16
---------------------------

* More specific error when failing to create XDG fallback trash directory (#20)
* Windows: Workaround for long paths (#23)

Version 1.4.2 -- 2017/11/17
---------------------------

* Fix incompatibility with Python 3.6 on Windows. (#18)

Version 1.4.1 -- 2017/08/07
---------------------------

* Fix crash on Windows introduced in v1.4.0. Oops... (#14)

Version 1.4.0 -- 2017/08/07
---------------------------

* Use ``bytes`` instead of ``str`` for internal path handling in ``plat_other``. (#13)

Version 1.3.1 -- 2017/07/31
---------------------------

* Throw ``WindowsError`` instead of ``OSError`` in ``plat_win``. (#7)
* Fix ``TypeError`` on python 2 in ``plat_other``. (#12)

Version 1.3.0 -- 2013/07/19
---------------------------

* Added support for Gnome's GIO.
* Merged Python 3 and Python 2 versions in a single codebase.

Version 1.2.0 -- 2011/03/16
---------------------------

* Improved ``plat_other`` to follow freedesktop.org trash specification.

Version 1.1.0 -- 2010/10/18
---------------------------

* Converted compiled modules to ctypes so that cross-platform compilation isn't necessary anymore.

Version 1.0.2 -- 2010/07/10
---------------------------

* Fixed bugs with external volumes in plat_other.

Version 1.0.1 -- 2010/04/19
---------------------------

* Fixed memory leak in OS X module.

Version 1.0.0 -- 2010/04/07
---------------------------

* Initial Release
