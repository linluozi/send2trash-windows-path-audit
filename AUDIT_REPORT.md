# send2trash — Windows 路径处理安全审计与修复报告

| 项目 | 内容 |
|---|---|
| 上游项目 | [arsenetar/send2trash](https://github.com/arsenetar/send2trash) |
| 基线提交 | `522bafebc8075644d1ce66d03047aafb994ad615`（2.1.0 + 3 个提交，2026-06-16） |
| 许可证 | BSD 3-Clause，Copyright (c) 2017 Virgil Dupras（`LICENSE` 逐字节未改） |
| 审计平台 | Windows 10/11 x64，CPython 3.13.14（另有 3.13.12 逻辑验证） |
| 结论 | 发现 6 个可复现的输入校验／路径处理缺陷，其中 2 个可导致**误删非目标文件**；已全部修复，新增 39 个回归用例（整套 61 个），变异测试 10/10 |

---

## 1. 为什么审计这个项目

send2trash 是 pip / pytest 生态里的基础依赖，职责单一——**删除**文件。它的调用方几乎都是"用户点了删除"这种不可撤销场景，因此路径处理的正确性就是它的全部安全性：

- 它删除，所以"路径悄悄解析到别处"比"报错"严重得多；
- 它跨 Windows / macOS / Linux 三套实现，Windows 侧同时存在 `SHFileOperationW`（ctypes）和 `IFileOperation`（pywin32）两条后端；
- 两条后端各自解析路径，上游没有共用的归一化层——这是缺陷的温床。

上游在 2.1.0 之后已有一次同类修复（`522bafe fix: Correct is_parent() path handling`，修 POSIX `is_parent()` 的子串误匹配）。这说明**路径处理缺陷在该项目中是真实存在的类别，不是扫描器臆测**，但那次修复完全没有触及 Windows 侧。

---

## 2. 审计方法

1. 阅读 `send2trash` 全部平台实现（Windows legacy/modern、mac legacy/modern、Freedesktop `plat_other`、GIO）。
2. 建立一个**隔离沙箱**：所有破坏性验证都在 `tempfile.mkdtemp()` 生成的一次性目录里做，绝不触碰真实文件。
3. 对每个可疑点先构造**最小复现**，跑未修复的原始代码，记录实际异常类型与文件存亡。
4. 只把"能复现、有源码证据"的点纳入修复清单；无法复现的猜测一律丢弃（见 §7）。
5. 修复后做三件事：整套上游测试、新增回归测试（先证明它在未修复代码上失败）、**变异测试**（把 bug 逐个注回，验证测试真的能抓到）。

---

## 3. 发现的问题

### 3.1 严重：绝对路径跳过归一化，路径原样喂给 Shell

`send2trash/win/legacy.py:146` 与 `win/modern.py:24`（修复前）：

```python
paths = [op.abspath(path) if not op.isabs(path) else path for path in paths]
```

`abspath` 只在路径**不是**绝对路径时才调用。所以绝对路径完全跳过归一化——`/` 分隔符、`.`、`..`、重复分隔符、目录末尾分隔符全部原样保留，直接交给 Win32/Shell API，而这两套 API **都不做归一化**。

实测（未修复代码，真实文件）：

| 传入 | legacy | modern | 文件结局 |
|---|---|---|---|
| `E:\...\f.txt` | 正常 | 正常 | 删除 ✅ |
| `E:/.../f.txt` | `FileNotFoundError` | `OSError 0x80070057` | **保留** ❌ |
| `E:\...\.\f.txt` | `ProcessLookupError` | `OSError` | **保留** ❌ |
| `E:\...\sub\..\f.txt` | `OSError` | `OSError` | **保留** ❌ |
| `E:\...\dir\` | 正常 | `OSError` | **保留** ❌ |
| `E:\...\dir/` | `OSError 123` | `OSError` | **保留** ❌ |

影响：任何用 `pathlib`/`os.path.join` 拼出正斜杠路径、或从配置文件/命令行拿到带尾斜杠目录的调用方，删除会**静默失败**。这不是安全漏洞，但是"删除功能在合法输入上直接失效"，属于功能性缺陷。

> 上游 issue #69「Add auto address fixing」正是这个诉求（"Os seems to throw an error. So, can you auto sanitize them"），至今开着。

### 3.2 严重：空路径被解析成「当前工作目录」

`op.abspath('')` 返回 CWD。因此 `send2trash('')` 等于请求把进程**当前工作目录整个送进回收站**。`'.'` 和 `'..'` 同理。

对比 POSIX 实现（`plat_other.py:166`）：

```python
if not op.exists(path_b):
    raise OSError(errno.ENOENT, f"File not found: {path}")
```

POSIX 明确抛 `ENOENT`。Windows 侧却会去删 CWD——**跨平台行为不一致**，且 Windows 侧的方向是危险的。

实测：Windows 因为"CWD 正被本进程占用"而失败（`WinError 161` / `0x80270027`），所以**本机未造成实际删除**。但这只是运气：目标之所以幸存，是因为操作系统拒绝删除一个正在被使用的目录，而不是库拒绝了非法输入。判定上必须按"输入校验缺失"处理，不能按"不可利用"处理——见 §7 的说明。

### 3.3 严重：`\\?\UNC\` 前缀被切成**相对路径**

`win/modern.py:26`（修复前）：

```python
paths = [path[4:] if path.startswith("\\\\?\\") else path for path in paths]
```

`\\?\UNC\srv\share\f.txt` 切掉 4 个字符后变成 `UNC\srv\share\f.txt`——**没有前导分隔符，是相对路径**，会相对 CWD 解析。若 CWD 下恰好存在 `UNC\srv\share\f.txt` 这棵树，删除的就是那个本地文件，而不是调用方指定的网络路径。

复现（沙箱内，`os.chdir` 到含诱饵树的目录）：

```
requested path  : \\?\UNC\srv\share\f.txt
after [4:] strip: UNC\srv\share\f.txt
is that absolute? False
modern() -> FileNotFoundError
decoy still exists: True
```

本机上 Shell 直接拒绝了相对路径，诱饵幸存。**但"幸存"依赖 Shell 拒绝相对路径这一实现细节**，而不是库保证了路径正确。这条与 3.2 同类：防御是偶然的，不是设计出来的。

### 3.4 高：嵌入 NUL 截断路径 —— 实测**误删**

`'real.txt\x00anything'` 不是任何文件的路径。Shell 解析到 NUL 就停止，于是 modern 后端**删掉了 `real.txt` 并返回成功**：

```
legacy   ArgumentError: argument 1: ValueError: embedded null character   → 文件保留
modern   returned OK                                                       → 文件已删除 ❌
```

这是本次审计中**唯一实测到的真实误删**。调用方传入一个"名字不是这个名字"的字符串，库却按前缀执行了删除。现代后端与 legacy 后端行为相反，且没有 `OSError` 保护。

### 3.5 中：`bytes` 路径用 ANSI 代码页解码

`win/legacy.py:144` 与 `win/modern.py:22`（修复前）用 `str(path, "mbcs")`。PEP 529 之后 Windows 的文件系统编码是 UTF-8，`mbcs` 是 ANSI 代码页。本机 ANSI = cp936：

```
name        : café-😇.txt
utf-8 bytes : b'caf\xc3\xa9-\xf0\x9f\x98\x87.txt'
str(b,"mbcs")  -> 'caf茅-馃槆.txt'   roundtrip equal? False
os.fsdecode(b) -> 'café-😇.txt'     roundtrip equal? True

legacy  bytes arg -> FileNotFoundError   (文件保留)
modern  bytes arg -> FileNotFoundError   (文件保留)
```

所有非 ASCII 文件名在非 UTF-8 ANSI 代码页的 Windows 上都会"找不到"。ASCII 路径两种解码结果相同，所以这个缺陷**只在非 ASCII 名称上暴露**——差分测试第一版用 ASCII 路径跑，两边都是 "DELETED"，差点漏判。

### 3.6 中：`CoInitialize` 与 `CoUninitialize` 不配对

`win/modern.py`（修复前）：

```python
pythoncom.CoInitialize()
fileop = pythoncom.CoCreateInstance(...)   # ← 在这之间抛出就泄漏
...
try:
    ...
finally:
    pythoncom.CoUninitialize()
```

`CoInitialize` 是按线程引用计数的。它写在 `try` **外面**，中间任何一步（`CoCreateInstance`、`SetOperationFlags`）失败，引用计数就永久 +1。长生命周期线程（Jupyter、GUI worker）里，调用方自己那次 `CoUninitialize` 就不足以拆掉 apartment。实测：

```
after FAILED call : init=1 uninit=0  balanced=False
after OK call     : init=1 uninit=1  balanced=True
```

同一段代码还有第二个问题：`CoCreateInstance` 抛出的 `pywintypes.com_error` **不是 `OSError` 子类**（实测 MRO 为 `com_error → Exception → BaseException`），而 README 承诺"其他问题抛 `OSError`"。只有 `try` 内部的调用被转换了，`try` 外的没有——所以调用方按文档 catch `OSError` 会漏掉。

---

## 4. 修复方案

核心是把"路径归一化"从两个后端各自为政，收敛为 `send2trash/util.py` 里的**单一入口** `normalize_win32_path()`，两条后端都在接触系统 API 之前调用它。

| 缺陷 | 修复动作 | 位置 |
|---|---|---|
| 3.1 绝对路径跳过归一化 | 无条件 `normpath(abspath(path))` | `util.py` |
| 3.1 目录尾分隔符 | 归一化前记录"是否带尾分隔符"；若是目录则允许，若是已存在的非目录则抛 `ENOENT` | `util.py` |
| 3.2 空/位置路径 | 显式拒绝 `''`、`'.'`、`'..'`，抛 `ENOENT`（与 POSIX 对齐） | `util.py` |
| 3.3 UNC 前缀切错 | `\\?\UNC\` → `\\`；`\\?\X:\` → `X:\`；无等价形式的（`\\?\Volume{GUID}\`）**保留前缀** | `util.py` |
| 3.4 NUL 截断 | 显式 `ValueError` | `util.py` |
| 3.5 bytes 解码 | `os.fsdecode()` 取代 `str(..., "mbcs")` | `util.py`（两条后端共用） |
| 3.6 COM 泄漏 | `CoInitialize()` 后立刻 `try/finally`；COM 主体移入 `_delete_items()`，`com_error` 转换覆盖整个函数体 | `win/modern.py` |

**为什么 3.1 的尾分隔符要分文件／目录处理**：无条件 `rstrip('\\/')` 会把 `'file.txt/'` 变成 `'file.txt'`，于是开始删除一个调用方**没有点名**的文件——比原来的报错更糟。而 POSIX 上 `'file.txt/'` 的 `exists()` 为 `False`，直接 `ENOENT`。所以按 POSIX 语义区分。

**为什么 `\\?\` 不能一律剥掉**：Shell item parser 完全不接受带前缀的路径（实测所有 `\\?\...` 形式都是 `0x80070057`），所以必须去掉；但 `\\?\UNC\` 和 `\\?\Volume{GUID}\` 没有 plain 等价形式，硬切会产生相对路径或错误盘符。只有 `\\?\X:\` 能无损翻译。

---

## 5. 修改清单

改动文件（共 3 个源文件 + 1 个测试文件 + 2 个文档）：

| 文件 | 变更 | 差异行数 |
|---|---|---|
| `send2trash/util.py` | 新增 `normalize_win32_path()`、`_strip_long_path_prefix()`、`_POSITIONAL_DIRS`；`preprocess_paths()` 未改 | +146 |
| `send2trash/win/legacy.py` | 改用 `normalize_win32_path()`；移除失效的 `os.path as op` 导入 | 34 |
| `send2trash/win/modern.py` | 改用 `normalize_win32_path()`；COM 主体移入 `_delete_items()`；`CoInitialize` 配对修复；扩大 `com_error` 转换范围 | 106 |
| `tests/test_win_path_handling.py` | **新增**，39 个用例，两条后端 × 真实文件 | 新增 |
| `README.rst` | 新增「Path handling on Windows」章节 | +26 |
| `CHANGES.rst` | 新增 Unreleased 条目 | +22 |
| `NOTICE.md` | **新增**，修改声明（BSD 要求） | 新增 |

**逐字节未改**（已核验）：`plat_other.py`、`plat_gio.py`、`mac/*`（3 个）、`win/__init__.py`、`win/IFileOperationProgressSink.py`、`__init__.py`、`__main__.py`、`exceptions.py`、`LICENSE`、`pyproject.toml`。

因此 POSIX / macOS 行为**零变更**——这是有意的：本次缺陷全部位于 Windows 路径层。

版权与许可：
- `LICENSE` 与上游逐字节一致（BSD 3-Clause, Virgil Dupras 2017）；
- 每个改动文件保留原有 `# Copyright 2017 Virgil Dupras` 与 BSD 声明头，新增行以 `# Copyright 2026 the send2trash contributors` 并列声明；
- `NOTICE.md` 写明基线 commit、修改范围、新增文件，满足 BSD「不得把修改版误表示为原版」的要求。

---

## 6. 测试结果

### 6.1 上游自带测试（回归基线）

```
修复前：22 passed, 1 skipped
修复后：61 passed, 1 skipped        ← 22 原有 + 39 新增
flake8 send2trash tests：无输出（rc=0）
```

上游测试全部保持通过，无回归。

### 6.2 新增回归测试先证明「未修复时失败」

把 `tests/test_win_path_handling.py` 拷进**未修改的基线**跑：

```
30 failed, 9 passed
```

覆盖：8 个路径变体 × 2 后端、目录尾分隔符、文件尾分隔符、空/`.`/`..` × 2 后端、UNC 诱饵、NUL、bytes UTF-8、COM 配对、COM apartment、长路径翻译。

> 9 个"在未修复代码上也通过"的用例是**故意保留**的：它们是接口契约与结构断言（如"公共入口与 CLI 必须和底层后端行为一致"、"`\\?\` 翻译表"），在两边都应为绿。判定测试是否有效看的是那 30 个从红转绿的用例，而不是总数。

### 6.3 变异测试 10/10

把每个原始 bug 逐个注回**已修复**代码，测试必须变红：

```
CONTROL (unmutated): GREEN
[KILLED] M1 no normalisation (original abspath-only-if-relative)   (failed=13)
[KILLED] M2 no NUL rejection                                       (failed=2)
[KILLED] M3 no blank/positional rejection                          (failed=6)
[KILLED] M4 naive prefix strip (original path[4:])                 (failed=3)
[KILLED] M5 bytes decoded as mbcs (original)                       (failed=2)
[KILLED] M6 trailing-separator guard removed                       (failed=4)
[KILLED] M7 legacy skips normalisation                             (failed=13)
[KILLED] M8 modern skips normalisation                             (failed=15)
[KILLED] M9 CoInitialize outside try (original leak)               (failed=1)
[KILLED] M10 com_error not converted (except clause narrowed)      (failed=2)
Mutation score: 10/10
```

> **第一轮只有 7/10，而且其中 2 个"kill"是假阳性。** 详见 §8.1——这是本次审计最有价值的教训。

### 6.4 修复前后差分

同一批场景，分别在基线（BEFORE）与修复版（AFTER）上跑独立进程：

```
scenario               backend  BEFORE                            AFTER
forward_slash          legacy   FileNotFoundError / kept          no-exception / DELETED   <== CHANGED
forward_slash          modern   OSError / kept                    no-exception / DELETED   <== CHANGED
dot_component          legacy   ProcessLookupError / kept         no-exception / DELETED   <== CHANGED
dot_component          modern   OSError / kept                    no-exception / DELETED   <== CHANGED
dotdot_component       legacy   OSError / kept                    no-exception / DELETED   <== CHANGED
dotdot_component       modern   OSError / kept                    no-exception / DELETED   <== CHANGED
dir_trailing_slash     legacy   OSError / kept                    no-exception / DELETED   <== CHANGED
dir_trailing_slash     modern   OSError / kept                    no-exception / DELETED   <== CHANGED
file_trailing_slash    legacy   OSError / kept                    FileNotFoundError / kept
file_trailing_slash    modern   OSError / kept                    FileNotFoundError / kept
nul_byte               legacy   ArgumentError / kept              ValueError / kept
nul_byte               modern   no-exception / DELETED            ValueError / kept        <== CHANGED
bytes_utf8             legacy   FileNotFoundError / kept          no-exception / DELETED   <== CHANGED
bytes_utf8             modern   FileNotFoundError / kept          no-exception / DELETED   <== CHANGED
```

### 6.5 端到端 CLI

```
$ send2trash -v "E:/.../a.txt"          # 正斜杠绝对路径
Trashed «E:/.../a.txt»                  # 修复前：FileNotFoundError

$ send2trash ""                          # 空参数
[Errno 2] refusing to trash '': it does not name a file or directory: ''
rc=1                                     # 修复前：尝试删除 CWD

$ send2trash -v "E:/.../tdir/"           # 目录尾斜杠
Trashed «E:/.../tdir/»                   # 修复前：OSError 123
```

### 6.6 长路径未被破坏

剥离 `\\?\` 后必须确认 `>MAX_PATH` 仍然可用：

```
len= 240  no-prefix: ok(len=240)   prefixed: ok(len=244)
len= 301  no-prefix: ok(len=301)   prefixed: ok(len=305)
len= 423  no-prefix: ok(len=423)   prefixed: ok(len=427)
backend -> short name ok
```

原因：legacy 的 `prefix_and_path()` 在内部**自己会重新加上** `\\?\`（实测 `C:\a\b\f.txt` → `\\?\C:\a`），所以在归一化阶段剥掉是安全的。已固化为回归测试 `test_path_longer_than_max_path_is_trashed`。

---

## 7. 判定说明：哪些算漏洞、哪些不算

本次刻意区分了三类，没有把"扫描器会报警"等同于"漏洞成立"：

**A. 实测可误删非目标文件（真漏洞，1 项）**
- NUL 截断（3.4）：modern 后端返回成功、目标文件消失。已修复。

**B. 输入校验缺失，但本机未观察到实际删除（真缺陷，按缺陷修）**
- 空路径 → CWD（3.2）、UNC 前缀 → 相对路径（3.3）。
- 两者都被操作系统**偶然**挡住（CWD 被占用 / Shell 拒绝相对路径）。但"挡住"不是库的设计保证：换一个不受占用的目标、或 Shell 未来接受相对路径，行为就变了。而且它们与 POSIX 语义（`ENOENT`）不一致。因此**按输入校验缺陷修复，但不宣称"本机可利用"**。
- 我特意尝试了 `'..'`（目标是父目录，不被本进程占用），仍被 `WinError 161` / `0x80270028` 挡住。所以"Windows 上无法真的删掉 CWD"这个结论在本机成立，但它依赖 OS 行为，不写进威胁模型。

**C. 功能性缺陷（不是安全漏洞，但值得修）**
- 绝对路径变体失败（3.1）、bytes 解码（3.5）、COM 泄漏（3.6）。
- 这些是"合法输入上功能失效"或"资源/契约错误"，按缺陷修复，不夸大。

**明确未纳入的项**（看过代码但无法复现或不属于本次范围）：
- 上游 `_HARD_LINK_FALLBACK_ERRNOS` / `open_atomic` 相关（属 portalocker，非本项目）；
- mac 侧 `FSMoveObjectToTrashSync` 已废弃（上游 issue #56 等）——需要 macOS 环境才能验证，本次不具备；
- `plat_other.py` 的 `is_parent()` 上游已在 `522bafe` 修复，本次基线已包含；
- 上游 issue #117（DLL 硬链接 `WinError 161`）——依赖具体文件状态，未复现，不猜。

---

## 8. 踩过的坑（供复核者参考）

### 8.1 变异测试第一轮 7/10，其中 2 个是**假阳性**

第一轮报 `[KILLED] M9` 和 `[KILLED] M10`，但两处都是 `failed=0`——即测试**一个都没失败**，进程却非零退出。追查发现变异体本身**语法错误**（`try:` 改 `if True:` 后残留 `except`），pytest 报 `1 error`，被我的 `rc != 0` 判成 kill。

处理：先 `py_compile` 校验每个变异体能解析，再重写 M9/M10 使其语义忠实（M10 改成把 `except pywintypes.com_error` 收窄为 `except ZeroDivisionError`）。重跑得 **10/10 且每个都有真实 failed 计数**。

> 教训印证：**"变异被杀"必须看测试是否真的失败，不能只看退出码**；`failed=0` 的 kill 一律要查。

### 8.2 行为断言抓不到"试了但失败了"

第一轮有三个变异存活（M3、M4、M9），原因都是**测试用"抛了 OSError"当通过条件**，而缺陷代码恰好也因为别的原因抛了 OSError：

- 空路径：缺陷代码去删 CWD，被 OS 拒绝 → 也抛 OSError → `pytest.raises(OSError)` 满足；
- UNC：缺陷代码喂相对路径，被 Shell 拒绝 → 也抛 OSError → 同样满足。

修法不是放宽断言，而是**加结构断言**：用 `monkeypatch` 替换"最后一步系统调用"，断言它**从未被调用**（空/位置路径）或**收到的永远是绝对路径且不带 `\\?\`**（UNC）。这正是"纯行为断言测不出被删掉的分支"的实例。

### 8.3 差分测试第一版把 bytes 缺陷跑成了"无差异"

初始用 ASCII 文件名 `f.txt`——UTF-8 和 cp936 对 ASCII 解码结果相同，于是 BEFORE/AFTER 都显示 `DELETED`，看起来"没有差异、无需修复"。换成 `café-😇.txt` 才暴露。

> 教训：**测试数据必须能区分被测维度**。ASCII 路径无法区分两种编码。

### 8.4 目录尾分隔符：无条件 strip 会造出新的误删

第一版修复直接 `rstrip('\\/')`。但 `'file.txt/'` 在 Windows 上不指向任何文件，strip 后开始删 `file.txt`——**修复引入的 bug 比原 bug 更危险**。改为按 POSIX 语义区分文件/目录后才正确。这条由变异 M6 兜住。

### 8.5 探针脚本污染工作树，把包构建搞挂了

`.audit_tools/probe_longpath_legacy.py` 用 `os.makedirs` 在 CWD 下造了 `AAAA…` 目录，之后 `pip install -e .` 报：

```
error: Multiple top-level packages discovered in a flat-layout:
['send2trash', 'AAAAAAAA…']
```

清理后恢复。**探针脚本必须在临时目录里造数据**，交付前也要扫一遍工作树有没有残留。

---

## 9. 尚未解决的风险

1. **macOS 与 Linux 侧未实机验证。** 本次只审计并修改 Windows 路径层；`plat_other`/`plat_gio`/`mac/*` 逐字节未改，理论上零影响，但"零影响"是按 diff 判定，不是按运行判定。macOS 的 `FSMoveObjectToTrashSync` 已废弃、`mac/legacy.py` 的 `cdll.LoadLibrary(find_library(...))` 在缺库环境的行为（上游 issue #85）未验证。

2. **`plat_other.py` 存在同类未修问题。** `info_for()` 里 `is_parent()` 的子串匹配已由上游 `522bafe` 修掉，但该文件仍用 `op.exists()` 做前置检查、`trash_move()` 的 `counter` 递增在并发下可能重名。**本次刻意不改**，因为 (a) 不在 Windows 路径层、(b) 无 POSIX 实机可验证、(c) 改动会扩大回归面。

3. **`..`/`''` 的"未被利用"结论绑定当前 Windows 行为。** 我实测 `'..'` 指向父目录时仍被 `WinError 161` 挡住。这个"挡住"来自 Shell/OS，不是库的保证。修复后库层已拒绝，但**如果**有版本差异（老 Windows、ReFS、网络盘）行为不同，我无法在本机覆盖。

4. **`\\?\` 前缀的翻译只覆盖三种形态**（UNC、盘符、Volume GUID）。其他如 `\\?\GLOBALROOT\`、`\\?\PIPE\`、`\\?\UNC` 大小写混写（`unc`/`Unc`）未逐一验证。当前实现对 `\\?\UNC\` 是**大小写敏感**匹配——大小写混写会走到"保留前缀"分支，即退回修复前的失败行为（报错，不误删）。方向上安全，但不完整。

5. **`bytes` 路径在 POSIX 上仍走原路径。** `plat_other.py` 自己用 `os.fsencode`/`fsdecode`，未受影响；但 `plat_gio.py` 直接把 `path` 交给 `Gio.File.new_for_path`，`bytes` 输入的语义未审计。

6. **未做模糊测试。** 本次是"定向复现 + 回归 + 变异"，样本由人工构造。路径解析这类输入空间适合 `hypothesis`/AFL 类方法，本次未覆盖。

7. **并发与重入未测。** `send2trash` 一次传多个路径时，modern 后端是"全部 DeleteItem 再 PerformOperations"，中间失败会留下部分已入队项。本次未审计该语义（上游 issue #99「skip failed files」正是这块）。

---

## 10. 复现步骤

```bash
# 环境
python -m venv .venv
.venv/Scripts/pip install pytest flake8 pywin32

# 全量测试（61 passed, 1 skipped）
.venv/Scripts/python -m pytest tests -q

# lint（无输出即通过）
.venv/Scripts/python -m flake8 send2trash tests

# 修复前后差分
python audit_tools/differential.py

# 变异测试（10/10）
python audit_tools/mutation_check.py
```

`audit/` 目录内是本次运行保存的原始输出：`test_run.txt`、`flake8.txt`、`differential.txt`、`mutation.txt`、`baseline_failures.txt`。

## 12. 交付物

| 文件 | 说明 |
|---|---|
| `send2trash-path-audit-2026-10-18.zip` | 完整修改后源码，解压后可直接 `pytest tests`，实测 61 passed / 1 skipped |
| `AUDIT_REPORT.md` | 本报告（最详细，含全部踩坑） |
| `README.md` | 仓库首页简版说明 |
| `index.html` | 单文件在线报告页（图片内联 base64，离线可开） |
| `NOTICE.md` | BSD 修改声明（随 ZIP 分发） |
| `docs/assets/*.png` | 三张配图，`bench/make_figures.py` 从 `audit/*.txt` 生成 |
| `audit/*.txt` | 本次运行的原始输出，未编辑 |

配图与页面均由脚本生成，**数字不手写**：`make_figures.py` 与 `make_page.py` 都从
`audit/` 下的真实运行输出解析。页面另由 `bench/verify_page.py` 在 headless Chromium 中
实测：3 张图 `naturalWidth>0`、背景/前景色正确、桌面与移动端均无横向溢出、无 console 错误。

ZIP 校验：

```
sha256  6c2a2b68f10032f20c02759b2a064b7b15048f29355724cfb73b01805ebe7774
```

解压后已核验：36/36 个文件与工作树**逐字节一致**，无 CRLF，无 `__pycache__`/`.pyc`。

---

## 11. 摘要

- **6 个缺陷**：1 个实测误删（NUL 截断）、2 个危险但被 OS 偶然挡住的输入校验缺失（空路径→CWD、UNC 前缀→相对路径）、3 个功能性/资源缺陷（绝对路径变体失败、bytes 编码错、COM 引用计数泄漏）。
- **修复集中在 `send2trash/util.py` 的单一入口**，两条 Windows 后端共用；POSIX/macOS 代码逐字节未动。
- **39 个回归用例**（加入后整套 61 个），其中 **30 个在未修复代码上失败**、修复后全绿；**变异测试 10/10**，且每个 kill 都核实为真实测试失败。
- **第一轮变异测试只有 7/10 且含 2 个假阳性**，三个存活变异暴露了"行为断言抓不到被删分支"——已改为结构断言。
- 许可证与版权完整保留，另附 `NOTICE.md` 说明修改范围。
