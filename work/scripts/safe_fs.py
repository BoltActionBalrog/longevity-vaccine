"""Deleting under the game folder without ever acting through a link.

A junction or symlink planted anywhere between the game folder and a path the installer removes (LongevityMods\\,
LongevityMods\\staging, ...) turns that removal into one OUTSIDE the game folder: shutil.rmtree refuses a junction
handed to it directly, but happily empties a child path reached THROUGH one, and rmdir on a junction removes the
link (verification of f076f34, 2026-11-15: a junctioned LongevityMods\\staging deleted the player's folder elsewhere).
Every removal here first checks each component from the game folder (exclusive) down to the target (inclusive) and
does nothing when any of them is a reparse point. Nested junctions INSIDE a removed tree are not followed:
shutil.rmtree has not descended into them since Python 3.8 (both runtimes this ships with).
"""
from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path


#: The reparse points that redirect a path elsewhere: a junction (mount point) and a symlink. Others -- a OneDrive
#: placeholder, a deduplicated file, a WIM/WOF-compressed file -- are ordinary files and folders in place
#: (audit-g LOW-9: treating every reparse point as a link refused them).
_LINK_TAGS = (getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003), getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C))


def is_link(p: Path) -> bool:
    """A symlink or a junction. Never raises; a missing path is not a link."""
    try:
        s = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(s.st_mode):
        return True
    if not getattr(s, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        return False
    return getattr(s, "st_reparse_tag", _LINK_TAGS[0]) in _LINK_TAGS     # no tag known: treated as a link


def first_link(root: Path, target: Path):
    """The first component from `root` (exclusive) down to `target` (inclusive) that is a link, else None."""
    root, target = Path(root), Path(target)
    try:
        rel = target.relative_to(root)
    except ValueError:
        return None
    try:
        real_root = root.resolve()
    except OSError:
        real_root = None
    cur = root
    for part in rel.parts:
        cur = cur / part
        if is_link(cur) or _leaves(cur, real_root):
            return cur
    return None


def _leaves(p: Path, real_root) -> bool:
    """Does an existing `p` resolve to somewhere outside the folder (any other redirecting reparse point)?"""
    if real_root is None or not os.path.lexists(p):
        return False
    try:
        Path(p).resolve().relative_to(real_root)
        return False
    except (OSError, ValueError):
        return True


def link_on_path(root: Path, target: Path) -> bool:
    """Is any component from `root` (exclusive) down to `target` (inclusive) a link -- or is `target` not under
    `root` at all? Either way, nothing is removed there."""
    try:
        Path(target).relative_to(Path(root))
    except ValueError:
        return True
    return first_link(root, target) is not None


def rmtree(root: Path, target: Path) -> bool:
    """shutil.rmtree(target), unless a link is on the way (or target is one). True when it ran. A read-only file in a
    tree the caller decided to delete (a backup set that kept a file's attributes, audit-l M2) goes too; anything that
    still cannot be removed is left, as before."""
    if link_on_path(root, target):
        return False

    def again(func, path, _exc):
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=again)
    else:
        shutil.rmtree(target, onerror=again)
    return True


#: The attributes a file keeps across a swap, a backup and a rollback (audit-l M2 / L1): read-only, hidden, system,
#: archive. Others (compressed, not-indexed ...) are the file system's own.
KEPT_ATTRS = 0x1 | 0x2 | 0x4 | 0x20


def file_attrs(p: Path):
    """The file's KEPT_ATTRS, or None (no such file, or no Windows attributes)."""
    try:
        return os.stat(p).st_file_attributes & KEPT_ATTRS
    except (OSError, AttributeError):
        return None


def set_file_attrs(p: Path, attrs) -> bool:
    """Give `p` these attributes (KEPT_ATTRS bits). True when set; a no-op for None or outside Windows."""
    if attrs is None or os.name != "nt":
        return False
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    return bool(k32.SetFileAttributesW(str(p), (attrs & KEPT_ATTRS) or 0x80))     # 0x80: FILE_ATTRIBUTE_NORMAL


def clear_read_only(p: Path):
    """Before a write or rename onto a file the caller may change: read-only goes. Returns the attributes it had (to
    put back afterwards), or None."""
    a = file_attrs(p)
    if a is not None and a & 0x1:
        set_file_attrs(p, a & ~0x1)
    return a


def write_entitled(p: Path, data: bytes) -> None:
    """Write over a file the caller may change (its own rules decided that), read-only or not; the file keeps its
    attributes. Raises OSError as Path.write_bytes."""
    p = Path(p)
    a = clear_read_only(p) if p.exists() else None
    try:
        p.write_bytes(data)
    finally:
        if a:
            set_file_attrs(p, a)


def rmdir(root: Path, target: Path) -> bool:
    """Remove an EMPTY directory -- never a link to one (that removes the link), never through one."""
    if link_on_path(root, target):
        return False
    try:
        Path(target).rmdir()
        return True
    except OSError:
        return False


def unlink_entitled(target: Path) -> None:
    """Delete a file the caller has ALREADY decided is ours to delete (its own rules: the path, the hash, no link on the
    way), read-only or not (audit-j MEDIUM-3: a read-only Thinker or pack file made every uninstall end "run --uninstall
    again", for ever). The read-only attribute is cleared only here, just before the delete, and only when the delete
    itself was refused: nothing that is not deleted ever has its attributes changed. Raises OSError as Path.unlink."""
    import stat
    target = Path(target)
    try:
        target.unlink()
        return
    except PermissionError:
        try:
            mode = os.lstat(target).st_mode
        except OSError:
            raise
        if mode & stat.S_IWRITE or stat.S_ISLNK(mode):
            raise                                     # not read-only: locked or denied -- left as it is
    os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    try:
        target.unlink()
    except OSError:
        try:
            os.chmod(target, stat.S_IREAD)            # the delete failed after all: the file keeps its attribute
        except OSError:
            pass
        raise


def unlink(root: Path, target: Path) -> bool:
    """Remove a file reached through no link (the file itself may be a symlink: unlink removes only the link).
    Raises OSError like Path.unlink for a file that cannot be removed; False when a link is on the way."""
    target = Path(target)
    if link_on_path(root, target.parent):
        return False
    target.unlink(missing_ok=True)
    return True
