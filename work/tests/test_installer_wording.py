"""The installer's player-visible text says "Longevity Vaccine", never "the mod"; never "resident updater";
and uses normal punctuation, never " -- " or a typographic dash (user 2026-11-15, the wording sweep).

Scans every string literal (not docstrings, not comments) of every module the installer can import at
runtime -- the closure of install.py, bootstrap.py and installer_exit.py over their imports of sibling
modules -- so a new module or a new line is covered without listing it here. Lines a player never sees
(check.log, the patch log, the developer transcript, developer-only build errors) are allowlisted by a
piece of their text, below; each says why.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
ENTRY = ("install", "bootstrap", "installer_exit")

PATTERNS = {
    "the mod": re.compile(r"\b[Tt]he mod\b(?!'s files)"),
    "a ' -- ' dash": re.compile(r"(?:^|\s)--(?:\s|$)"),
    "a typographic dash": re.compile("[–—]"),
    "resident updater": re.compile(r"resident updater", re.I),
}

#: (module, a piece of the literal's text) -> why a player never sees it.
ALLOW = {
    ("apply_patches.py", "Nothing to apply -- no confirmed sites"): "developer transcript (v())",
    ("apply_patches.py", "=== Plan (dry run -- nothing will be written) ==="): "developer transcript (v())",
    ("apply_patches.py", "DRY RUN -- all verifications passed"): "developer transcript (v())",
    ("apply_patches.py", "NOTE: backup already exists at"): "developer transcript (v())",
    ("apply_patches.py", ": deferred -- group"): "developer transcript (v())",
    ("apply_patches.py", ": not applied -- "): "developer transcript (v())",
    ("apply_patches.py", "differs from the recorded lock"): "developer transcript (v())",
    ("apply_patches.py", "skippable; not applied (already modified by another mod?)"):
        "developer transcript (v()); a player sees only the skipped sites' names",
    ("apply_patches.py", "skippable site(s) not applied"): "developer transcript (v())",
    ("install.py", " -- re-run the installer (--repair restores them)"): "health line, check.log only",
    ("install.py", "Mod loaded: never -- "): "health line, check.log only",
    ("install.py", "Mod files: cannot compare -- "): "health line, check.log only",
    ("install.py", " -- cinematics OFF: "): "health line, check.log only",
    ("install.py", " -- movie audio: "): "health line, check.log only",
    ("install.py", " -- install patch run "): "patch log header",
    ("install.py", " -- update patch run "): "patch log header",
    ("install.py", "not found -- build it first"): "developer checkout only (src\\uimod\\build.bat)",
    ("install.py", "no portraits found in"): "developer checkout only (build_portraits_hd.py)",
    ("install.py", "  Portrait art by Turovetsky -- "): "third-party credit, user-ruled verbatim",
    ("install.py", "  Cinematics upscaled by Z2k Retro -- "):
        "third-party credit, kept verbatim like the portrait credit (master's line, merged 2026-11-15)",
}


def test_the_portrait_art_credit_is_verbatim():
    """User 2026-11-15 ("Restore the original"): a third-party credit, kept byte for byte; no sweep changes it."""
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import install as inst
    assert inst.PORTRAIT_ART_CREDIT == ("  Portrait art by Turovetsky -- https://www.youtube.com/@Turovetsky -- "
                                        "https://x.com/turovetsky")


def _runtime_modules() -> list:
    have = {p.stem for p in SCRIPTS.glob("*.py")}
    todo, seen = list(ENTRY), set()
    while todo:
        m = todo.pop()
        if m in seen or m not in have:
            continue
        seen.add(m)
        for n in ast.walk(ast.parse((SCRIPTS / f"{m}.py").read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                todo += [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                todo.append(n.module.split(".")[0])
    return sorted(f"{m}.py" for m in seen)


def _literals(path: Path):
    """(line, text) of every string literal that is not a docstring; an f-string as one text with {..}."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = node.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                    and isinstance(b[0].value.value, str):
                skip.add(id(b[0].value))
        if isinstance(node, ast.JoinedStr):
            skip.update(id(v) for v in node.values)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            yield node.lineno, "".join(v.value if isinstance(v, ast.Constant) else "{..}" for v in node.values)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.lineno, node.value


def test_the_scan_covers_the_installer():
    mods = _runtime_modules()
    for m in ("install.py", "bootstrap.py", "installer_exit.py", "thinker_flow.py", "fetch.py", "manifest.py",
              "preflight.py", "transact.py", "patch_helptext.py"):
        assert m in mods


@pytest.mark.parametrize("module", _runtime_modules())
def test_player_visible_installer_text_reads_plainly(module):
    bad = []
    for line, text in _literals(SCRIPTS / module):
        if any(m == module and piece in text for (m, piece) in ALLOW):
            continue
        for name, rx in PATTERNS.items():
            if rx.search(text):
                bad.append(f"{module}:{line}: {name}: {text[:120]!r}")
    assert not bad, "\n".join(bad)


_PREFS_SRC = SCRIPTS.parent.parent / "src" / "uimod" / "src" / "prefs.cpp"


def _prefs_option_names() -> list:
    """Every Longevity Preferences row and button, as the game names it (prefs.cpp's k...Text labels)."""
    return re.findall(r'const char k\w+Text\[\] = "([^"]+)"', _PREFS_SRC.read_text(encoding="utf-8"))


def test_the_preferences_names_are_read_from_the_game():
    names = _prefs_option_names()
    assert "Check for Updates at Startup" in names and "Reset Skipped Updates" in names and len(names) >= 10


@pytest.mark.parametrize("module", _runtime_modules())
def test_a_preferences_option_is_named_in_single_quotes(module):
    """User 2026-11-15 ("Have it switched"): an installer line names a Preferences option the way it names a button,
    'Check for Updates at Startup', never in double quotes."""
    bad = []
    names = _prefs_option_names()
    for line, text in _literals(SCRIPTS / module):
        for n in names:
            if f'"{n}"' in text:
                bad.append(f"{module}:{line}: \"{n}\" in {text[:100]!r}")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("module", _runtime_modules())
def test_no_installer_line_names_the_update_check_option(module):
    """User 2026-11-15 ("Drop it everywhere"): the installer says "Longevity Preferences" and never names
    the 'Check for Updates at Startup' row -- not in the AUTOMATIC UPDATES block, the answer lines, the re-run line or
    the write warning."""
    bad = [f"{module}:{line}: {text[:100]!r}" for line, text in _literals(SCRIPTS / module)
           if "check for updates at startup" in text.lower()]
    assert not bad, "\n".join(bad)


def test_every_allowlist_entry_still_matches_a_line():
    """A stale entry would silently allow a new line that happens to share its text."""
    texts = {m: [t for _l, t in _literals(SCRIPTS / m)] for m in {m for m, _p in ALLOW}}
    stale = [(m, p) for (m, p) in ALLOW if not any(p in t for t in texts[m])]
    assert not stale, stale


@pytest.mark.parametrize("text,name", [
    ("the mod works without it", "the mod"),
    ("already patched -- skipping", "a ' -- ' dash"),
    ("Watch THAT window — nothing changed", "a typographic dash"),
    ("could not install the resident updater", "resident updater"),
])
def test_the_patterns_catch_what_the_sweep_removed(text, name):
    assert PATTERNS[name].search(text)


@pytest.mark.parametrize("text", ["run --uninstall again", "--- repair: Longevity Vaccine's updater ---",
                                  "copying Longevity Vaccine's files", "the Longevity Vaccine mod"])
def test_the_patterns_leave_flags_headers_and_names_alone(text):
    assert not any(rx.search(text) for rx in PATTERNS.values())
