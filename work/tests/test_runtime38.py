"""The Windows 7 / 8 interpreter (CPython 3.8.10, tools\\python38 -> work\\build\\runtime38).

CPython 3.12 does not start below Windows 8.1, so the payload carries 3.8.10 beside it and three
places pick it there (run-install.bat, bootstrap.py, the DLL's update check). The scripts are the
SAME files, so every one of them must stay 3.8-clean for as long as Windows 7 is supported: this
module compiles them all with the real 3.8 interpreter and runs the verifier's own known answer
under it. build_runtime.py --verify runs the whole installer flow under 3.8 as well; that is the
heavy proof and belongs to the release pipeline, not to every test run.

Skipped when fetch_python38.py / build_runtime.py have not been run (no interpreter to test with).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import release as rel  # noqa: E402

_STAGED = _REPO / "work" / "build" / "runtime38" / "python.exe"
_SRC = _REPO / "tools" / "python38" / "python.exe"
PY38 = _STAGED if _STAGED.is_file() else _SRC
pytestmark = pytest.mark.skipif(not PY38.is_file(), reason="no Windows 7 interpreter (run fetch_python38.py)")


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = {"SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", r"C:\Windows"),
           "PATH": __import__("os").environ.get("PATH", ""),
           "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(_TESTS / "does-not-exist")}      # must be ignored (._pth)
    return subprocess.run([str(PY38), *args], capture_output=True, text=True, timeout=300, env=env, cwd=cwd)


def test_it_is_cpython_38_isolated_by_its_pth():
    p = _run("-c", "import sys; print(sys.version_info[:2]); print(sys.path); print(sys.flags.no_site)")
    assert p.returncode == 0, p.stderr
    assert "(3, 8)" in p.stdout
    assert "does-not-exist" not in p.stdout, "PYTHONPATH leaked in: the ._pth is missing or wrong"
    assert "AppData" not in p.stdout, "the player's user site leaked in"
    # the only site-packages allowed is the runtime's own (pefile + yaml ride there once build_runtime.py
    # has staged it; the raw fetch_python38.py output has none at all, which is just as isolated)
    paths = [q.replace("\\\\", "\\").lower() for q in re.findall(r"'([^']*site-packages[^']*)'", p.stdout)]
    assert all(str(PY38.parent).lower() in q for q in paths), p.stdout
    if PY38 == _STAGED:
        assert paths, "the staged runtime must carry its own site-packages (pefile + yaml): " + p.stdout


def test_every_shipped_script_compiles_under_38():
    """The one gate that keeps a 3.9+ idiom (match, removeprefix, dict |, list[str] at runtime, ...)
    out of the files a Windows 7 player runs. MODULE_SPEC is what ships."""
    shipped = [_REPO / src for src, _dst in rel.MODULE_SPEC["base"]["files"] if src.endswith(".py")]
    assert len(shipped) >= 12, shipped
    p = _run("-m", "py_compile", *map(str, shipped))
    assert p.returncode == 0, f"a shipped script is not 3.8-clean:\n{p.stdout}{p.stderr}"


needs_staged = pytest.mark.skipif(not _STAGED.is_file(),
                                  reason="runtime38 not staged (build_runtime.py): the raw embeddable has no pefile/yaml")


@needs_staged
def test_the_verifier_and_manifest_import_and_run_under_38(tmp_path):
    """Importing is more than compiling (module-level code, annotations evaluated at def time, the
    third-party pefile/yaml staged beside the interpreter); the Ed25519 verifier's RFC 8032 known
    answer must hold on the 3.8 bignum path too."""
    shipped = sorted(Path(src).stem for src, _dst in rel.MODULE_SPEC["base"]["files"] if src.endswith(".py"))
    assert "install" in shipped and "bootstrap" in shipped and "ed25519_verify" in shipped
    code = f"import sys\nsys.path.insert(0, sys.argv[1])\nimport {', '.join(shipped)}\n" + r"""
import ed25519_verify
# RFC 8032 section 7.1, test 1: empty message
pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
                    "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
assert ed25519_verify.verify(pk, sig, b"") is True
assert ed25519_verify.verify(pk, sig, b"x") is False
print("ok38")
"""
    (tmp_path / "t.py").write_text(code, encoding="utf-8")
    p = _run(str(tmp_path / "t.py"), str(_SCRIPTS))
    assert p.returncode == 0 and "ok38" in p.stdout, f"{p.stdout}\n{p.stderr}"


@needs_staged
def test_install_py_help_runs_under_38():
    p = _run(str(_SCRIPTS / "install.py"), "--help")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "--game-dir" in p.stdout


@needs_staged
def test_staged_runtime_carries_the_ucrt_and_the_provenance():
    d = _STAGED.parent
    for f in ("ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll", "vcruntime140.dll", "python38.zip",
              "python38._pth", "LICENSE.txt", "PROVENANCE.txt", "_ssl.pyd", "libssl-1_1.dll"):
        assert (d / f).is_file(), f
    assert (d / "python38._pth").read_text(encoding="ascii") == "python38.zip\n.\nLib\\site-packages\n"
    # the installer's third-party imports, pure Python (no cp312 .pyd may ride along)
    assert (d / "Lib" / "site-packages" / "pefile.py").is_file()
    assert (d / "Lib" / "site-packages" / "yaml" / "parser.py").is_file(), "PyYAML's PURE parser: 3.8 has no _yaml.pyd"
    assert not list((d / "Lib" / "site-packages").rglob("*.pyd"))
    assert "sha256 760dc79bcb434ee80b1001a30bb6f798287881851bac6d8137867894d40ef1fc" in \
        (d / "PROVENANCE.txt").read_text(encoding="utf-8")
