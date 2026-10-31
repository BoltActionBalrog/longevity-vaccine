"""The production YAML loader (libyaml's CSafeLoader, `apply_patches._yaml_load`) reads our patch specs exactly as
the pure-Python reference loader does.

The rest of the suite parses through `ap._yaml_load` (memoized in conftest), so a test that compares production
against "an independent parse" no longer has one. This is that independent parse, done once, unmemoized: a
libyaml/pyyaml divergence on these files fails here instead of passing invisibly on both sides of every check.
Types compare exactly -- a hex literal read as str by one loader and int by the other is the failure that matters.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PATCHES = Path(__file__).resolve().parent.parent / "patches"
SPECS = ("patches.yaml", "patches_prax.yaml")


def _same(a, b, where="$"):
    assert type(a) is type(b), f"{where}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        assert list(a) == list(b), f"{where}: keys differ"
        for k in a:
            _same(a[k], b[k], f"{where}.{k}")
    elif isinstance(a, list):
        assert len(a) == len(b), f"{where}: length {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            _same(x, y, f"{where}[{i}]")
    else:
        assert a == b, f"{where}: {a!r} vs {b!r}"


@pytest.mark.parametrize("name", SPECS)
def test_c_loader_reads_the_spec_as_the_reference_loader_does(name):
    if not getattr(yaml, "__with_libyaml__", False):
        pytest.skip("pyyaml built without libyaml: production falls back to SafeLoader itself")
    text = (PATCHES / name).read_text(encoding="utf-8")
    _same(yaml.load(text, Loader=yaml.CSafeLoader), yaml.load(text, Loader=yaml.SafeLoader))
