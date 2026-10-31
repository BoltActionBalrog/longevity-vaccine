"""keystone 0.9.2 hex-misread guard (scripts/ks_guard.py).

keystone sometimes opens an X86 engine that reads every unprefixed number as hex for its whole life
(`mov eax, 10` -> b8 10 00 00 00; 1 in ~255 engines opened in an xdist worker). ks_guard patches
keystone.Ks.__init__ to check every new X86 engine and reopen a bad one. It only protects a process
that imports it, so every production script that imports keystone must import ks_guard too: an
assembler run outside pytest (a bake, a release build) has no conftest to protect it, and a misread
immediate there goes silently into patches.yaml.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

KEYSTONE_IMPORT = re.compile(r"^([ \t]*)(?:from keystone import |import keystone\b)[^\n]*\n", re.M)


def test_every_keystone_import_is_followed_by_the_guard():
    """Defect prevented: a new or edited script opens an unguarded engine outside pytest. The guard goes on the
    very next line at the same indent, so a lazy (in-function) keystone import stays lazy and is still guarded."""
    unguarded = [f"{p.name}: {m.group(0).strip()}"
                 for p in sorted(SCRIPTS.glob("*.py"))
                 if p.name != "ks_guard.py" and not p.name.startswith("_")   # _*.py = gitignored local scratch
                 for src in [p.read_text(encoding="utf-8")]
                 for m in KEYSTONE_IMPORT.finditer(src)
                 if not src.startswith(m.group(1) + "import ks_guard", m.end())]
    assert not unguarded, "add `import ks_guard` on the line after:\n" + "\n".join(unguarded)


def test_tests_run_guarded():
    """conftest imports ks_guard, so engines the tests open themselves are checked too."""
    keystone = pytest.importorskip("keystone")
    assert getattr(keystone.Ks.__init__, "ks_guard", False)


def test_real_engine_reads_numbers_right():
    keystone = pytest.importorskip("keystone")
    import ks_guard
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    assert ks_guard.reads_numbers_right(ks)
    assert bytes(ks.asm("mov eax, 10")[0]) == bytes.fromhex("b80a000000")


class _FakeKs:
    """Stands in for keystone.Ks: engine #n of the run misreads immediates when n is in `bad`."""

    def __init__(self, bad):
        self.bad, self.opened = bad, 0

    def init(self, eng, arch, mode):
        self.opened += 1
        eng.hex_reader = self.opened in self.bad

    @staticmethod
    def asm(eng, text):
        imm = text.split(",")[1].strip()
        n = int(imm, 16) if eng.hex_reader or imm.startswith("0x") else int(imm)
        return list(b"\xb8" + n.to_bytes(4, "little")), 1


@pytest.mark.parametrize("bad, opens", [(set(), 1), ({1}, 2), ({1, 2, 3}, 4)])
def test_bad_engine_is_reopened(bad, opens, capsys):
    keystone = pytest.importorskip("keystone")
    import ks_guard
    fake = _FakeKs(bad)
    eng = type("E", (), {"asm": lambda self, t: fake.asm(self, t)})()
    ks_guard.checked_init(fake.init)(eng, keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    assert fake.opened == opens and not eng.hex_reader
    assert capsys.readouterr().err.count("reopening") == len(bad)


def test_gives_up_after_max_opens():
    keystone = pytest.importorskip("keystone")
    import ks_guard
    fake = _FakeKs(set(range(1, ks_guard.MAX_OPENS + 1)))
    eng = type("E", (), {"asm": lambda self, t: fake.asm(self, t)})()
    with pytest.raises(RuntimeError, match="misread immediates"):
        ks_guard.checked_init(fake.init)(eng, keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    assert fake.opened == ks_guard.MAX_OPENS


def test_other_architectures_are_not_probed():
    keystone = pytest.importorskip("keystone")
    import ks_guard
    fake = _FakeKs({1})
    eng = type("E", (), {"asm": lambda self, t: pytest.fail("non-X86 engine probed")})()
    ks_guard.checked_init(fake.init)(eng, keystone.KS_ARCH_ARM, keystone.KS_MODE_ARM)
    assert fake.opened == 1


def test_installs_once():
    keystone = pytest.importorskip("keystone")
    import importlib

    import ks_guard
    before = keystone.Ks.__init__
    importlib.reload(ks_guard)
    assert keystone.Ks.__init__ is before
