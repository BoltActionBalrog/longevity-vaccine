"""No git worktree of this repository may LINK (junction or symlink) a folder to the main checkout's.

`git worktree remove` deletes THROUGH a junction (measured 2026-11-14): removing a worktree whose
src\\uimod\\third_party was a junction emptied the main checkout's ffmpeg folder, twice. The folders a worktree
needs (the bundled interpreter, the staged runtimes, ffmpeg) are COPIED in instead. This catches a link the moment
any test run sees it, before anyone removes that worktree. Cheap: a few stat calls per worktree."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

#: The gitignored inputs a worktree is tempted to link rather than copy (feedback-worktree-installer-test-inputs).
WATCHED = ("tools", "tools/python", "tools/python38", "work/build", "work/build/runtime", "work/build/runtime38",
           "src/uimod/third_party", "src/uimod/third_party/ffmpeg", "src/uimod/tools", "src/uimod/build", "dist")


def _is_link(p: Path) -> bool:
    isj = getattr(os.path, "isjunction", None)
    return p.is_symlink() or bool(isj and isj(p))


def _worktrees() -> list:
    git = shutil.which("git")
    if not git:
        pytest.skip("git not on PATH")
    r = subprocess.run([git, "worktree", "list", "--porcelain"], cwd=_REPO, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("not a git checkout")
    return [Path(l[len("worktree "):]) for l in r.stdout.splitlines() if l.startswith("worktree ")]


def test_no_worktree_links_a_folder_into_another_checkout():
    bad = [str(w / rel) for w in _worktrees() if w.is_dir() for rel in WATCHED if _is_link(w / rel)]
    assert not bad, ("these worktree folders are links; `git worktree remove` would delete the TARGET's contents. "
                     "Replace each with a copy (`cmd /c rmdir <link>` removes only the link): " + ", ".join(bad))
