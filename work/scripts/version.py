"""Single source of truth for the Longevity Vaccine product version (Python side).

Kept in lockstep with src\\uimod\\src\\version.h -- work\\tests\\test_version_sync.py fails if the
two disagree, so bump BOTH in the same commit.

Nothing here touches the filesystem, the network, or the game: it is pure string/tuple arithmetic
so it can be swept exhaustively by the test suite, the same way scaling_laws.py is. Imports are
stdlib-only and present in the CPython *embeddable* distribution, which is what ships.

Version scheme: MAJOR.MINOR.PATCH, ASCII decimal, no leading zeros, no pre-release or build
metadata. Two rules earn their keep:

  * Comparison is NUMERIC, never lexical -- "1.0.10" is newer than "1.0.9", which a string
    compare gets backwards.
  * The DIGITS are canonical: `01.2.3` is rejected rather than silently equal to `1.2.3`, because
    consumers store the raw string (the receipt, the [Longevity] ini keys, a signed manifest's
    bytes) and later compare with `==`. If two spellings parsed equal while comparing unequal as
    text, a re-patch loop or a false "tampered" verdict would follow.

    The raw TEXT is still not canonical, because `parse` tolerates surrounding ASCII whitespace --
    values genuinely arrive from files with a trailing CRLF. So "1.0.0" and "1.0.0\\r\\n" compare
    equal but differ under `==`. **Consumers must store `normalise(v)`, not the raw field.**
"""

from __future__ import annotations

import re
from typing import Tuple

VERSION = "1.0.1"

#: The oldest installed version that may update itself automatically; anything older is told to
#: reinstall by hand (manifest `min_upgradable_from`, decide() step "too_old"). release.py used to
#: set this to the release being cut, which stranded EVERY existing install on every release.
#: Raise it only when an old client genuinely cannot be brought forward.
MIN_UPGRADABLE_FROM = "0.1.0"

#: The Thinker Mod build this release is measured against: every detour into thinker.dll (the AI perception
#: filter's Thinker half, its text placement, the compatibility chains) is pinned to this exact binary by its PE
#: TimeDateStamp and SizeOfImage. Any other build makes the game show the "built for Thinker Mod X" warning at
#: start (uimod thinkerversion.cpp) and the installer print the same warning. Mirrored in version.h
#: (UIMOD_THINKER_SUPPORTED_*); test_version_sync pins the two. Bump all three together when a new Thinker is measured.
THINKER_SUPPORTED_VERSION = "5.5"
THINKER_SUPPORTED_STAMP = 0x6A821052
THINKER_SUPPORTED_IMAGE_SIZE = 0x19F000
#: Where a player gets that build: its tag on Thinker's GitHub releases. THINKER_DEV_PAGE is empty for a GitHub
#: release; when the pin is one of the author's development builds it holds that ONE build's own page and is used
#: instead (user 2026-11-14). Mirrored in version.h (UIMOD_THINKER_SUPPORTED_TAG / UIMOD_THINKER_DEV_PAGE).
THINKER_SUPPORTED_TAG = "v5.5"
THINKER_DEV_PAGE = ""

#: The optional content packs, each versioned INDEPENDENTLY of the product. Bumping a pack here
#: is what makes a pack-only release: release.py names the archive for it and the manifest
#: carries it, and an installed copy compares ITS version against this one -- never `VERSION`.
#: `base` is the product itself and is never listed here.
MODULE_VERSIONS = {
    "movies-hd": "2.0.0",       # user 2026-11-12: Z2k Retro's 30 fps upscales replace the Real-ESRGAN pack
    "portraits-hd": "1.0.0",    # user 2026-11-06: first release, with the artist's licence confirmed
}


#: sha256 of each pack's pack-manifest.json at the version above (dist\<pack>\pack-manifest.json, which release.py puts
#: in that version's archive). A setup run ADOPTS a pack left in the game folder without a receipt entry only when its
#: pack-manifest.json is byte-identical to this one and every file it lists is there at its size (audit-n 2026-11-17).
#: Update it with MODULE_VERSIONS: test_audit_n pins it to dist\<pack>\pack-manifest.json.
PACK_MANIFEST_SHA256 = {
    "movies-hd": "69658c800346d5394c8c3d4ce45f7c0ca3c1f45428e9b7779d1c798b248791dc",
    "portraits-hd": "1b3c59713a88f1d8f3cc2fc60cd2fd018a9477ea0d46524673deb493c6e4c43d",
}
#: sha256 of each pack's PROVENANCE.txt (its credit and licence) at the version above (dist\<pack>\PROVENANCE.txt).
#: Adoption needs it too, and a kept pack of that version is repaired when its copy differs (audit-o 2026-11-17): a
#: PROVENANCE-only version bump keeps an identical pack-manifest.json. release.py refuses an archive whose two files
#: are not these; test_audit_o pins them to dist. Update with MODULE_VERSIONS.
PACK_PROVENANCE_SHA256 = {
    "movies-hd": "dacc855891bbf7d4303cf8932b96a0be6dbbad8f42ebd1c61f11300eb898fb49",
    "portraits-hd": "b667f13fd3b79355aa99f3becef4f7d24f7f02b9f6e5b4b006ee938d2bfaa28b",
}


def module_version(name: str) -> str:
    """The current release version of a module; `base` is the product version."""
    if name == "base":
        return VERSION
    try:
        return MODULE_VERSIONS[name]
    except KeyError:
        raise KeyError(f"unknown module {name!r}; known: base, "
                       + ", ".join(sorted(MODULE_VERSIONS))) from None

#: What an installed copy reports when it predates version identity entirely (no version keys in
#: the ini, no receipt). Treated as older than every real release.
#: NOTE: the [Longevity] ini section that will hold these keys does not exist yet -- every current
#: key lives under [UIMod]. The installer creates it (plan Phase 0 / Phase 4); until then nothing
#: reads or writes it.
UNKNOWN = "0.0.0"

#: One ASCII component: 0, or a non-zero digit followed by digits. Deliberately NOT `str.isdigit()`
#: -- that accepts non-ASCII decimal digits (Arabic-Indic, fullwidth, Bengali, ...), so
#: "١.٠.١" would parse as (1, 0, 1), compare as newer than 1.0.0, and then be
#: written verbatim into an ANSI ini via WritePrivateProfileStringA, which cannot encode it.
_COMPONENT_RE = re.compile(r"0|[1-9][0-9]*")

#: Only ASCII whitespace is tolerated around a version (real values arrive from files with trailing
#: CRLF). str.strip() with no argument would also eat NBSP and vertical tab.
_ASCII_WS = " \t\r\n"

#: uimod.rc feeds MAJOR/MINOR/PATCH into 16-bit FILEVERSION words, where a larger value truncates
#: silently. Bounding here also stops a garbled or hostile manifest version -- e.g. a 4000-digit
#: component -- from comparing "newer" than every real release and forcing a re-patch loop.
MAX_COMPONENT = 65535


def parse(v: str) -> Tuple[int, int, int]:
    """'1.2.3' -> (1, 2, 3). Raises ValueError on anything else, including non-str input.

    Strict on purpose: a malformed version in a manifest or a receipt is a bug or a tampered
    input, and coercing it to (0, 0, 0) would make an install look older than it is and trigger a
    pointless re-patch.
    """
    if not isinstance(v, str):
        raise ValueError(f"version must be a str, got {type(v).__name__}")
    parts = v.strip(_ASCII_WS).split(".")
    if len(parts) != 3:
        raise ValueError(f"version must be MAJOR.MINOR.PATCH, got {v!r}")
    out = []
    for p in parts:
        if not _COMPONENT_RE.fullmatch(p):
            raise ValueError(
                f"version component must be an ASCII integer with no leading zeros, "
                f"got {p!r} in {v!r}"
            )
        n = int(p)
        if n > MAX_COMPONENT:
            raise ValueError(
                f"version component {n} exceeds {MAX_COMPONENT} (the 16-bit FILEVERSION limit) "
                f"in {v!r}")
        out.append(n)
    return out[0], out[1], out[2]


def normalise(v: str) -> str:
    """The CANONICAL text for a version -- what every consumer must store.

    `parse` tolerates surrounding ASCII whitespace because real values arrive from files with a
    trailing CRLF. That makes the raw text non-canonical: "1.0.0" and "1.0.0\\r\\n" compare EQUAL
    via compare() but differ under `==`. A consumer that stores the raw string and later does
    `stored == VERSION` would see a mismatch where compare() sees equality -- a re-patch loop, or
    a false "tampered" verdict. Store normalise(v), never the raw field.
    """
    return "%d.%d.%d" % parse(v)


def is_valid(v: object) -> bool:
    """True if `v` parses. Never raises -- this is the gate for untrusted input, so it must not
    be the thing that throws. Anything at all may be passed, including bytes, None, and objects
    whose own __str__/strip misbehave."""
    try:
        parse(v)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - deliberately total: see the docstring
        return False
    return True


def compare(a: str, b: str) -> int:
    """-1 if a < b, 0 if equal, 1 if a > b. Numeric, not lexical. Raises ValueError on bad input."""
    pa, pb = parse(a), parse(b)
    return (pa > pb) - (pa < pb)


def is_newer(candidate: str, installed: str) -> bool:
    """True if `candidate` is a version worth offering over `installed`."""
    return compare(candidate, installed) > 0


def at_least(v: str, minimum: str) -> bool:
    """True if `v` >= `minimum`. Used for the manifest's min_upgradable_from gate."""
    return compare(v, minimum) >= 0


if __name__ == "__main__":  # pragma: no cover - convenience for release scripting
    print(VERSION)
