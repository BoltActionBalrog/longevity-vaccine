"""--fix-thinker's LONGEVITY VACCINE UPDATE block (journey R, Q-L), user-approved wording 2026-11-17 (during Part 5 of
the walkthrough): the "If you choose 'Keep Longevity Vaccine ...', ..." sentence is dropped in every variant, and
"After this, the installer offers the Thinker Mod version that goes with your choice." reads "This installer will
offer to update Thinker for you.". Written to fail first."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import installer_exit as ix         # noqa: E402
import thinker_flow as tf           # noqa: E402
from test_thinker_flow import World  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

OFFER = "This installer will offer to update Thinker for you."     # the user's text, verbatim


def _notes(tmp_path, monkeypatch, variant: str) -> list:
    w = World(tmp_path, monkeypatch, label=None if variant == "no-thinker" else b"Thinker Mod v5.4", latest="9.9.9",
              answers=["n", "n", "n"])
    if variant == "keep-offers-a-change":
        # Thinker already matches the newer release, so keeping Longevity Vaccine is what offers a Thinker change
        sha = hashlib.sha256((w.g / "thinker.dll").read_bytes()).hexdigest()
        w.doc["thinker"]["pins"]["5.7.0"]["dll"] = sha
    try:
        w.run()
    except ix.InstallerError:
        pass
    options, notes = w.asked[0]
    assert options[0] == "Update Longevity Vaccine to 9.9.9"
    return notes


@pytest.mark.parametrize("variant", ["thinker-to-match", "keep-offers-a-change", "no-thinker"])
def test_no_if_you_choose_sentence_in_any_variant(tmp_path, monkeypatch, variant):
    notes = _notes(tmp_path, monkeypatch, variant)
    assert not any("If you choose" in n for n in notes), notes


@pytest.mark.parametrize("variant", ["thinker-to-match", "keep-offers-a-change"])
def test_the_thinker_line_is_the_users_text(tmp_path, monkeypatch, variant):
    notes = _notes(tmp_path, monkeypatch, variant)
    assert notes[1:] == [OFFER], notes
    assert not any("goes with your choice" in n for n in notes)


def test_without_thinker_only_the_first_line(tmp_path, monkeypatch):
    notes = _notes(tmp_path, monkeypatch, "no-thinker")
    assert len(notes) == 1 and notes[0].startswith("Longevity Vaccine 9.9.9 is available."), notes
