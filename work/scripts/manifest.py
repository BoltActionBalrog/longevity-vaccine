"""Load, verify and interpret the update manifest.

Two responsibilities, both security-relevant:

1. **Verification.** `load_verified()` checks the detached Ed25519 signature over the manifest's
   EXACT bytes and only then parses it. Parsing first and verifying later would mean acting on
   attacker-controlled structure before knowing it is authentic.

2. **The decision.** `decide()` implements the precedence order that both the installer and (in a
   simpler form) the in-game checker must apply:

       1. `protocol` not understood            -> MANUAL INSTALL
       2. `manual_install_required`             -> MANUAL INSTALL   (global kill switch)
       3. our version in `unsupported_versions`
          or our target in `unsupported_targets`-> MANUAL INSTALL   (surgical kill switch)
       4. `latest` in `yanked`                  -> NOTHING (stay quiet)
       5. `latest` newer than installed         -> UPDATE (base, plus any stale module)
       6. an INSTALLED module newer in manifest -> UPDATE (that module only; base is current)
       7. otherwise                             -> NOTHING

   Step 6 is what makes a module's release independent of the product's: `Decision.modules`
   names the installed modules to fetch, and a module the player does not have is never fetched
   implicitly -- it is announced (install.offer_optional_modules) and added on request.

   Steps 1-3 are the escape hatches for a defect already in the wild: `protocol` covers a client
   too old to understand the manifest, and the kill-switch fields cover a client we must strand
   deliberately -- the case `protocol` cannot reach, because a broken bootstrap may still parse
   the manifest perfectly. They are flat scalars and arrays of strings on purpose: the OLDEST
   client in the wild has to be able to read them, so they must never become nested objects.

**No URL or user-visible text is ever taken from the manifest.** `DOWNLOAD_URL` and the reason
strings are compiled in here. The in-game checker does not verify signatures (that would put
Ed25519 in C++ for no benefit -- it only reads a version to decide whether to prompt), so a
tampered response could otherwise make the mod display an attacker's download link. The manifest
selects WHICH message appears, never the message itself.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import ed25519_verify as ed  # noqa: E402
import version as ver        # noqa: E402

#: The protocol revision this client understands. Bump only when the manifest's MEANING changes in
#: a way an older client would misread; adding fields does not require it.
SUPPORTED_PROTOCOL = 1

#: Release signing public key (hex). Set from `sign_manifest.py --keygen` output.
#: Empty = no key provisioned yet, and `load_verified` then refuses everything.
PUBLIC_KEY_HEX = "f429f9684395252e268fc04ca5f2a7e016558cca78ec9d7acaad9adf7205ca9b"

#: Compiled-in, never read from the manifest. See the module docstring.
DOWNLOAD_URL = "https://longevitymods.com/vaccine/download"

#: Where the manifest and its detached signature live. Short TTL at the CDN; the versioned
#: package paths it points at are immutable, so no invalidation is ever needed.
MANIFEST_URL = "https://longevitymods.com/vaccine/manifest.json"
SIGNATURE_URL = MANIFEST_URL + ".sig"

MANUAL = "manual-install"
UPDATE = "update"
NOTHING = "nothing"

#: Reason enum -> the message WE show. The manifest may only pick a key.
REASONS = {
    "protocol": "This version of the mod is too old to understand the update service.",
    "bootstrap_defect": "This version of the mod cannot update itself.",
    "base_unsupported": "Your version is unsupported.",
    "too_old": "This version is too old to update automatically.",
    None: "Your version is unsupported.",
}


class ManifestError(Exception):
    """The manifest could not be trusted or could not be parsed."""


def _safe(value, limit: int = 120) -> str:
    """Render a manifest-derived value for a DIAGNOSTIC line: no control characters, bounded.

    `detail` exists for logs and developers. It must never be interpolated into a player-facing
    sentence -- a manifest that set `latest` to "Go to http://evil.example and run setup.exe"
    otherwise appeared inside our own "see the official link" message. Callers that show something
    to the user must use `message` and `url`, which are compiled in.
    """
    s = str(value)
    s = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in s)
    return s[:limit] + ("..." if len(s) > limit else "")


class Decision:
    __slots__ = ("action", "reason", "message", "url", "version", "detail", "modules")

    def __init__(self, action, reason=None, version=None, detail=None, modules=None):
        self.action = action
        #: Installed content modules to fetch (stale ones). Empty unless action == UPDATE.
        self.modules = list(modules or [])
        # An unhashable reason (a list, a dict) must not turn a refusal into a TypeError.
        try:
            hash(reason)
        except TypeError:
            reason = None
        self.reason = reason
        self.version = version
        self.detail = detail
        self.message = REASONS.get(reason, REASONS[None]) if action == MANUAL else None
        self.url = DOWNLOAD_URL if action == MANUAL else None

    def __repr__(self):  # pragma: no cover - diagnostics
        return f"<Decision {self.action} reason={self.reason} version={self.version}>"


def trust_anchor(allow_env: bool = False) -> str:
    """The public key this build trusts.

    `LONGEVITY_TRUST_KEY` is honoured in exactly two situations, and never in the one that
    matters:

      * while `PUBLIC_KEY_HEX` is empty -- with no key compiled in, nothing is trusted at all, so
        an override subverts nothing and is what makes the update path testable before a release
        key exists;
      * when the caller passes `allow_env=True`, which it may only do for a manifest read from a
        LOCAL FILE (`--manifest <path>`, a dev/test affordance).

    A production run fetches the manifest from the compiled-in https URL, so `allow_env` is False
    and the environment cannot influence which key is trusted. That is the property worth having:
    the override is reachable only by someone who can already both set this process's environment
    AND place a file on disk for it to read.
    """
    if PUBLIC_KEY_HEX and not allow_env:
        return PUBLIC_KEY_HEX
    return os.environ.get("LONGEVITY_TRUST_KEY", "") or PUBLIC_KEY_HEX


def load_verified(raw: bytes, signature_hex: str, public_key_hex: str = None,
                  allow_env: bool = False) -> dict:
    """Verify the detached signature over `raw`, THEN parse. Raises ManifestError otherwise."""
    pk = trust_anchor(allow_env) if public_key_hex is None else public_key_hex
    if not pk:
        raise ManifestError(
            "no release signing key is provisioned in this build, so no manifest can be trusted")
    if not isinstance(raw, (bytes, bytearray)):
        raise ManifestError("manifest must be verified as raw bytes, not text")
    if not ed.verify_detached(pk, signature_hex or "", bytes(raw)):
        raise ManifestError("manifest signature does not verify -- refusing to use it")
    try:
        doc = json.loads(bytes(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ManifestError(f"manifest is not valid UTF-8 JSON: {e}")
    if not isinstance(doc, dict):
        raise ManifestError("manifest must be a JSON object")
    return doc


def load_verified_files(manifest_path, signature_path=None, public_key_hex: str = None) -> dict:
    manifest_path = Path(manifest_path)
    sig_path = Path(signature_path) if signature_path else \
        manifest_path.with_suffix(manifest_path.suffix + ".sig")
    try:
        raw = manifest_path.read_bytes()
        sig = sig_path.read_text(encoding="ascii")
    except OSError as e:
        raise ManifestError(f"could not read the manifest or its signature: {e}")
    return load_verified(raw, sig, public_key_hex)


def _str_list(doc: dict, key: str):
    """Read a flat list-of-strings kill-switch field. Returns (values, readable).

    `readable=False` means the field is PRESENT but in a shape we do not understand. That must
    fail CLOSED: these fields exist solely to stop a client in the wild, so a hand-edited manifest
    with a JSON typo (`unsupported_versions: {"1.0.0": "why"}`) previously did nothing at all and
    said nothing -- the worst possible outcome for a safety valve. A MISSING field is still just
    "not set", so an old client does not choke on a newer manifest.
    """
    if key not in doc or doc[key] is None:
        return [], True
    v = doc[key]
    if isinstance(v, str):
        return [v], True
    if isinstance(v, (list, tuple)):
        if all(isinstance(x, str) for x in v):
            return list(v), True
        return [x for x in v if isinstance(x, str)], False
    return [], False


def _flag(doc: dict, key: str):
    """Read a boolean kill-switch field. Returns True / False / None (present but unreadable).

    `is True` alone was too strict: `manual_install_required: 1` or `"true"` -- both natural in a
    hand-edited manifest -- were silently ignored and the client updated anyway.
    """
    if key not in doc or doc[key] is None:
        return False
    v = doc[key]
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "1", "on"):
            return True
        if s in ("false", "no", "0", "off", ""):
            return False
    return None


#: The largest archive size a manifest may declare (1 PiB). Above it -- or a bool, a float, a
#: negative -- the value is treated as "no size": a 320-digit int raised OverflowError in the
#: extras notice, AFTER a completed install, and a bool printed "(0 MB)".
MAX_SIZE = 1 << 50


def size_ok(s) -> bool:
    """A manifest `size` field that may be printed or summed: a plain non-negative int only."""
    return type(s) is int and 0 <= s <= MAX_SIZE


def stale_modules(doc: dict, installed_modules: dict) -> list:
    """The installed content modules whose manifest version is newer than the receipt's.

    `installed_modules` is name -> receipt version. `base` is skipped if present: the base is
    compared as `installed_version` in decide(), and counting it twice would make a base bump look
    like a module update as well. A module entry that is missing, not a dict or carries an
    unusable version is simply "not offered" -- quiet, not closed, because a broken OPTIONAL entry
    must never block the core update the kill switches already vetted.
    """
    mods = doc.get("modules")
    if not isinstance(mods, dict) or not isinstance(installed_modules, dict):
        return []
    out = []
    for name, have in installed_modules.items():
        if name == "base" or not isinstance(name, str):
            continue
        info = mods.get(name)
        offered = info.get("version") if isinstance(info, dict) else None
        if not isinstance(offered, str) or not ver.is_valid(offered):
            continue
        # An unreadable receipt version means we do not know what is there: offer the update
        # rather than silently treat it as current (the same rule as the base at step 5).
        if not isinstance(have, str) or not ver.is_valid(have) \
                or ver.is_newer(offered, have):
            out.append(name)
    return sorted(out)


def decide(doc: dict, installed_version: str, target_id: str = None,
           supported_protocol: int = SUPPORTED_PROTOCOL,
           installed_modules: dict = None) -> Decision:
    """Apply the precedence order. `doc` need not be well-formed beyond being a dict.

    `installed_modules` (name -> receipt version) makes a module's update independent of the
    product's: a stale INSTALLED module is an UPDATE even when `latest` equals the installed base,
    and `Decision.modules` names exactly the modules to fetch. An absent module is never in it --
    absent modules are announced, not fetched.
    """
    if not isinstance(doc, dict):
        return Decision(MANUAL, "protocol", detail="manifest is not an object")

    # 1. protocol
    proto = doc.get("protocol")
    if not isinstance(proto, int) or isinstance(proto, bool) or proto > supported_protocol:
        return Decision(MANUAL, "protocol", detail=f"manifest protocol {_safe(proto)}")

    # 2. global kill switch
    flag = _flag(doc, "manual_install_required")
    if flag is None:
        return Decision(MANUAL, None, detail="manual_install_required is unreadable -- "
                                             "treating it as set")
    if flag:
        reason = doc.get("manual_install_reason")
        if not isinstance(reason, str) or reason not in REASONS:
            reason = None
        return Decision(MANUAL, reason, detail="manual_install_required")

    # 3. surgical kill switch
    bad_versions, ok_v = _str_list(doc, "unsupported_versions")
    bad_targets, ok_t = _str_list(doc, "unsupported_targets")
    if not ok_v or not ok_t:
        return Decision(MANUAL, None,
                        detail="an unsupported_* kill-switch field is unreadable -- "
                               "treating it as set")
    # Compare NORMALISED: the receipt value is canonical, a hand-edited manifest entry like
    # "0.1.0 " is not, and a kill switch that fails to match fails OPEN.
    bad_versions = [ver.normalise(v) if ver.is_valid(v) else v for v in bad_versions]
    if installed_version in bad_versions or (
            ver.is_valid(installed_version) and ver.normalise(installed_version) in bad_versions):
        return Decision(MANUAL, "base_unsupported",
                        detail=f"version {_safe(installed_version)} is listed unsupported")
    if target_id and target_id in bad_targets:
        return Decision(MANUAL, "base_unsupported",
                        detail=f"target {_safe(target_id)} is listed unsupported")

    latest = doc.get("latest")
    if not isinstance(latest, str) or not ver.is_valid(latest):
        return Decision(MANUAL, "protocol", detail=f"unusable `latest` {_safe(latest)}")
    # Canonicalise: `parse` tolerates surrounding ASCII whitespace, so a signed manifest could
    # otherwise put "1.1.0\n" into Decision.version and from there into a path or a URL.
    latest = ver.normalise(latest)

    # 4. yanked
    yanked, ok_y = _str_list(doc, "yanked")
    if not ok_y:
        return Decision(MANUAL, None, detail="the yanked list is unreadable")
    yanked = [ver.normalise(v) if ver.is_valid(v) else v for v in yanked]
    if latest in yanked:
        return Decision(NOTHING, detail=f"{_safe(latest)} is yanked")

    # 5/6. version comparison. Stale modules are worked out FIRST so that an unreadable base
    # (below) still carries them: gen 2 decides again from the receipt after the self-update,
    # and dropping the packs there meant a corrupt BaseVersion silently skipped every pack.
    stale = stale_modules(doc, installed_modules or {})
    if not ver.is_valid(installed_version) \
            or ver.normalise(installed_version) == ver.UNKNOWN:
        # An unreadable installed version must not silently mean "up to date" -- and it must
        # not mean "too old" either: receipt.module_version maps garbage to UNKNOWN ("0.0.0"),
        # which is a VALID string, so a corrupt receipt used to fall through to the
        # min_upgradable_from gate and tell the player to reinstall by hand.
        return Decision(UPDATE, version=latest, modules=stale,
                        detail="installed version unreadable")
    min_from = doc.get("min_upgradable_from")
    if isinstance(min_from, str) and ver.is_valid(min_from) \
            and not ver.at_least(installed_version, min_from):
        return Decision(MANUAL, "too_old",
                        detail=f"{installed_version} predates min_upgradable_from {min_from}")
    if ver.is_newer(latest, installed_version):
        return Decision(UPDATE, version=latest, modules=stale)
    if stale:
        return Decision(UPDATE, version=latest, modules=stale,
                        detail="module update: " + ", ".join(_safe(m, 40) for m in stale))
    return Decision(NOTHING, detail="already current")
