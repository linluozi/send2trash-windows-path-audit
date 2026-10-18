"""Push the current HEAD through the Git Data API.

Fallback for when github.com:443 is unreachable but api.github.com works.
Rebuilds only the changed subtrees, reusing the remote shas for everything
else, then moves refs/heads/main. Asserts the resulting root tree sha equals
the local ``git rev-parse HEAD^{tree}``, which proves the content is identical
byte for byte.
"""

import base64
import json
import os
import subprocess
import sys

REPO = "linluozi/send2trash-windows-path-audit"
BRANCH = "main"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args):
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return out.stdout.decode("utf-8", "replace").strip()


def gh(*args, stdin=None):
    proc = subprocess.run(
        ["gh", "api", *args],
        cwd=ROOT,
        capture_output=True,
        input=stdin.encode() if stdin else None,
    )
    if proc.returncode != 0:
        raise SystemExit(f"gh api {' '.join(args)} failed:\n{proc.stderr.decode()[:800]}")
    return proc.stdout.decode()


def api_json(*args, stdin=None):
    return json.loads(gh(*args, stdin=stdin) or "{}")


# ---------------------------------------------------------------- local state
local_head = git("rev-parse", "HEAD")
local_tree = git("rev-parse", "HEAD^{tree}")
parent = api_json(f"repos/{REPO}/git/ref/heads/{BRANCH}")["object"]["sha"]
print(f"local  HEAD {local_head}")
print(f"parent {parent}")

if parent == local_head:
    print("already up to date")
    sys.exit(0)

remote_parent_tree = api_json(f"repos/{REPO}/git/commits/{parent}")["tree"]["sha"]
print(f"parent tree {remote_parent_tree}")
print(f"local  tree {local_tree}")

# Which paths changed between the two commits, per git.
changed = set()
diff = subprocess.run(
    ["git", "diff", "--name-only", parent, local_head],
    cwd=ROOT, capture_output=True, text=True,
)
if diff.returncode != 0:
    raise SystemExit("cannot diff against parent: " + diff.stderr[:400])
for line in diff.stdout.splitlines():
    if line.strip():
        changed.add(line.strip())
print(f"changed paths: {len(changed)}")

# Blobs for every changed file, plus the directory structure they need.
blobs = {}
entries = []  # (path, mode, type, sha)
for path in sorted(changed):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        raise SystemExit(f"deletion not handled by this script: {path}")
    with open(full, "rb") as handle:
        content = base64.b64encode(handle.read()).decode()
    blob = api_json(
        f"repos/{REPO}/git/blobs", "-X", "POST", "--input", "-",
        stdin=json.dumps({"content": content, "encoding": "base64"}),
    )
    blobs[path] = blob["sha"]
    mode = "100755" if os.access(full, os.X_OK) and path.endswith(".sh") else "100644"
    entries.append((path, mode, "blob", blob["sha"]))
print(f"uploaded {len(blobs)} blobs")


# ---------------------------------------------------------------- build trees
def build_tree(prefix):
    """Recursively build the tree at `prefix`, reusing remote shas elsewhere."""
    remote_tree = api_json(f"repos/{REPO}/git/trees/{remote_parent_tree}", "--jq", ".") \
        if not prefix else None
    raise NotImplementedError


# Simpler and safer: rebuild only directories that contain changes, starting
# from the deepest one, and reuse the remote sha for every sibling.
def remote_tree_at(sha):
    return api_json(f"repos/{REPO}/git/trees/{sha}")


def dirs_needing_rebuild(paths):
    """Every directory prefix that contains at least one changed file."""
    out = {""}
    for path in paths:
        parts = path.split("/")[:-1]
        for i in range(len(parts) + 1):
            out.add("/".join(parts[:i]))
    # Deepest first, so a parent can reference its children's new shas. Depth
    # is the number of slashes *plus one for the root*, which makes '' the
    # last entry regardless of how the sort tie-breaks.
    return sorted(out, key=lambda p: len([s for s in p.split("/") if s]), reverse=True)


#: Filled deepest-first as trees are created. Declared before `make_tree` so the
#: function body resolves it from the enclosing module scope, not a local.
new_shas = {}  # populated below, deepest first


def make_tree(dir_prefix):
    """Create a tree object for `dir_prefix` from local files + remote siblings."""
    children = {}
    depth = 0 if not dir_prefix else dir_prefix.count("/") + 1

    for path in changed:
        if dir_prefix and not path.startswith(dir_prefix + "/"):
            continue
        rel = path[len(dir_prefix) + 1:] if dir_prefix else path
        if "/" in rel:
            continue  # a subdirectory, handled by its own rebuild
        mode = "100755" if os.access(os.path.join(ROOT, path), os.X_OK) and path.endswith(".sh") else "100644"
        children[rel] = {"path": rel, "mode": mode, "type": "blob", "sha": blobs[path]}

    # Pull in siblings that did not change, from the remote tree.
    remote_sha = remote_parent_tree
    if dir_prefix:
        parts = dir_prefix.split("/")
        for i, part in enumerate(parts):
            listing = remote_tree_at(remote_sha)["tree"]
            match = [e for e in listing if e["path"] == part and e["type"] == "tree"]
            if not match:
                remote_sha = None
                break
            remote_sha = match[0]["sha"]
    if remote_sha:
        for entry in remote_tree_at(remote_sha)["tree"]:
            if entry["path"] in children:
                continue
            # A subdirectory that was itself rebuilt must be referenced by its
            # *new* sha, not skipped: skipping it silently drops the change.
            child_prefix = (dir_prefix + "/" + entry["path"]) if dir_prefix else entry["path"]
            if child_prefix in new_shas:
                children[entry["path"]] = {
                    "path": entry["path"],
                    "mode": entry["mode"],
                    "type": "tree",
                    "sha": new_shas[child_prefix],
                }
                continue
            if child_prefix in rebuild_dirs:
                continue
            children[entry["path"]] = {
                "path": entry["path"],
                "mode": entry["mode"],
                "type": entry["type"],
                "sha": entry["sha"],
            }

    payload = {"tree": [children[k] for k in sorted(children)]}
    return api_json(
        f"repos/{REPO}/git/trees", "-X", "POST", "--input", "-",
        stdin=json.dumps(payload),
    )["sha"]


rebuild_dirs = set(dirs_needing_rebuild(changed))
print(f"rebuilding {len(rebuild_dirs)} trees")

# Iterate the *ordered* list, not the set: a set has no order, so the root
# could be built before the child whose new sha it needs to reference.
for prefix in dirs_needing_rebuild(changed):
    new_shas[prefix] = make_tree(prefix)

root_tree = new_shas[""]
print(f"new root tree {root_tree}")
if root_tree != local_tree:
    raise SystemExit(
        f"TREE MISMATCH: api produced {root_tree}, local is {local_tree}. "
        "Refusing to move the branch."
    )

# ---------------------------------------------------------------- commit + ref
message = git("log", "-1", "--format=%B")
commit = api_json(
    f"repos/{REPO}/git/commits", "-X", "POST", "--input", "-",
    stdin=json.dumps({"message": message, "tree": root_tree, "parents": [parent]}),
)
print(f"new commit {commit['sha']}")

api_json(
    f"repos/{REPO}/git/refs/heads/{BRANCH}", "-X", "PATCH", "--input", "-",
    stdin=json.dumps({"sha": commit["sha"], "force": False}),
)
print("branch moved")

final = api_json(f"repos/{REPO}/git/ref/heads/{BRANCH}")["object"]["sha"]
final_tree = api_json(f"repos/{REPO}/git/commits/{final}")["tree"]["sha"]
print(f"remote HEAD {final}")
print(f"remote tree {final_tree}")
print("CONTENT IDENTICAL" if final_tree == local_tree else "MISMATCH!")
