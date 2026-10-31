"""g=16 no-op net for the multiplayer negotiation window (diplowin_scale): pristine exe vs a FRESH apply of the
current patches.yaml (not the installed exe, which may predate the bake).

Every DiploWin function the bake redirects is emulated in both images from an identical synthetic state with
g_popup_scale_num = 16, every out-of-function call stubbed and recorded (target + ecx + 8 stack args) and every
non-stack write logged (harness: test_strip_g16_identity.FnRun).  The whole pcave2 section is executable in the
patched image, so the thunks run and must tail into the same native callees with the same state: at g=16 the
traces must be IDENTICAL -- the executable form of "1024x768 is byte-identical vanilla".
"""
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import test_strip_g16_identity as H  # noqa: E402

if not H.HAVE_EMU:
    pytest.skip("pefile/unicorn not installed", allow_module_level=True)


PCAVE2_ALL = (0xA0C000, 0xA0C000 + 0x30000)
FNS = {
    "diplo":               (0x444D90, 0x444DA7),
    "DiploWin_build":      (0x443F10, 0x444D8F),
    "DiploWin_draw":       (0x4436C0, 0x443C6F),
    "DiploWin_draw_left":  (0x442A10, 0x442DBF),
    "DiploWin_draw_right": (0x442DC0, 0x44316F),
    "DiploWin_draw_offers": (0x443170, 0x4436BF),
    "DiploWinIface_on_mode": (0x443C70, 0x443D76),
}


@pytest.fixture(scope="module")
def images(bak_path, baked_exe):
    return H.load_sections(str(bak_path)), H.load_sections(str(baked_exe))


FIND_FONT = 0x5882F0


def norm(trace):
    """find_font is cdecl(size, variant): ecx and the stack past its two args are not inputs.  The patched image
    reaches it through t_ffn (the shared face-law drop-in, a pass-through at g=16) from inside t_ffn's own
    frame, so only (target, size, variant) is compared for it."""
    return [("call", e[1], None, e[3][:2]) if e[0] == "call" and e[1] == FIND_FONT else e for e in trace]


@pytest.mark.parametrize("name", sorted(FNS))
def test_scaling_diplowin_fn_g16_identity(images, name):
    pristine, patched = images
    fn = FNS[name]
    for seed in H.SEEDS:
        ta = norm(H.FnRun(pristine, fn, seed, extra_exec=[]).run().trace)
        tb = norm(H.FnRun(patched, fn, seed, extra_exec=[PCAVE2_ALL]).run().trace)
        for i in range(min(len(ta), len(tb))):
            assert ta[i] == tb[i], (f"{name} seed={seed} diverges at event {i}:\n"
                                    f"  pristine: {ta[i]}\n  patched:  {tb[i]}")
        assert len(ta) == len(tb), (name, seed, len(ta), len(tb))
        assert len(ta) >= (1 if name == "diplo" else 4), (name, ta)   # the run actually exercised the function
