"""Differential: thunk_uimod_preload (the two-phase DLL bootstrap, group uimod_bootstrap).

PRACX's loader stub (_SELFMOD 0x668160) ends `call eax; ret` at 0x668187 with eax = prax
ordinal #1 (PRACXHook) and hPrax on the stack. The site replaces those bytes with
`push thunk_uimod_preload; ret`; the thunk must then, in order,

    LoadLibraryA("uimod") -> GetProcAddress(hUimod, #2) -> PreInit(hPrax)
    -> PRACXHook(hPrax) -> GetProcAddress(hUimod, #1) -> Init(hUimod)

and return to the startup-table walker with hPrax consumed (esp = entry esp + 4) and
esi/edi/ebx preserved. Every missing piece degrades to the step before: no uimod.dll ->
PRACXHook alone; no ordinal #2 -> PRACXHook + Init; no ordinal #1 -> PreInit + PRACXHook.

Bytes come from patches.yaml resolved with the real symbol table; the KERNEL32 imports are
stubbed at the IAT slots the thunk reads (ds:[0x669120] LoadLibraryA, ds:[0x669124]
GetProcAddress), each emulated as a __stdcall that records its arguments.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402

SITE_VA = 0x00668187           # PRACX stub's `call eax; ret`
RET_TO_WALKER = 0x00644F00     # sentinel: where the stub's own ret would go (_initterm)
LOADLIBRARYA_SLOT = 0x669120
GETPROCADDRESS_SLOT = 0x669124
GETLASTERROR_SLOT = 0x669144
EXITPROCESS_SLOT = 0x66918C
MESSAGEBOXA_SLOT = 0x669318
STACK = 0x00200000

# fake import / export targets (one page; each is a HLT so an un-intercepted call stops)
FAKE = 0x7F000000
F_LOADLIBRARY, F_GETPROC, F_PREINIT, F_HOOK, F_INIT, F_GETLASTERROR, F_MSGBOX, F_EXIT = (FAKE + 0x10 * i for i in range(8))
H_PRAX, H_UIMOD = 0x10000000, 0x10100000


def _doc():
    return ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))


def _load_content(doc, cid):
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] == cid:
                base = cave["virtual_addr"]
                base = int(base, 16) if isinstance(base, str) else base
                off = c["offset"]
                off = int(off, 16) if isinstance(off, str) else off
                va = base + off
                return va, ap.ByteTemplate(c["bytes"]).resolve(va, symtab), symtab
    raise AssertionError(f"{cid} content entry not found")


DOC = _doc()
THUNK_VA, THUNK_CODE, SYMTAB = _load_content(DOC, "thunk_uimod_preload")
STRINGS_VA, STRINGS, _ = _load_content(DOC, "g_boot_strings")     # the boot guard's message parts (data)


def _site():
    for s in DOC["sites"]:
        if s["id"] == "PRACX_load_stub.uimod_chain":
            return s
    raise AssertionError("site PRACX_load_stub.uimod_chain not found")


def _read_cstr(uc, addr):
    out = b""
    while True:
        b = uc.mem_read(addr, 1)
        if b == b"\0":
            return out.decode()
        out += bytes(b)
        addr += 1


def _run(*, have_dll=True, have_preinit=True, have_init=True, last_error=126):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(THUNK_VA & ~0xFFF, 0x2000)
    uc.mem_map(0x668000, 0x2000)               # the stub page + IAT slots (0x669120/4)
    uc.mem_map(RET_TO_WALKER & ~0xFFF, 0x1000)
    uc.mem_map(FAKE, 0x1000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(THUNK_VA, THUNK_CODE)
    uc.mem_write(STRINGS_VA, STRINGS)
    uc.mem_write(LOADLIBRARYA_SLOT, struct.pack("<I", F_LOADLIBRARY))
    uc.mem_write(GETPROCADDRESS_SLOT, struct.pack("<I", F_GETPROC))
    uc.mem_write(GETLASTERROR_SLOT, struct.pack("<I", F_GETLASTERROR))
    uc.mem_write(EXITPROCESS_SLOT, struct.pack("<I", F_EXIT))
    uc.mem_write(MESSAGEBOXA_SLOT, struct.pack("<I", F_MSGBOX))
    uc.mem_write(FAKE, b"\xF4" * 0x100)
    uc.mem_write(RET_TO_WALKER, b"\xF4")

    calls = []

    def stdcall_return(uc, nargs, result):
        esp = uc.reg_read(UC_X86_REG_ESP)
        ret = struct.unpack("<I", uc.mem_read(esp, 4))[0]
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + 4 * nargs)
        uc.reg_write(UC_X86_REG_EAX, result)
        uc.reg_write(UC_X86_REG_EIP, ret)

    def arg(uc, i):
        esp = uc.reg_read(UC_X86_REG_ESP)
        return struct.unpack("<I", uc.mem_read(esp + 4 + 4 * i, 4))[0]

    def on_code(uc, address, size, _):
        if address == F_LOADLIBRARY:
            name = _read_cstr(uc, arg(uc, 0))
            calls.append(("LoadLibraryA", name))
            stdcall_return(uc, 1, H_UIMOD if have_dll else 0)
        elif address == F_GETPROC:
            h, ordinal = arg(uc, 0), arg(uc, 1)
            calls.append(("GetProcAddress", h, ordinal))
            if ordinal == 2:
                stdcall_return(uc, 2, F_PREINIT if have_preinit else 0)
            elif ordinal == 1:
                stdcall_return(uc, 2, F_INIT if have_init else 0)
            else:
                stdcall_return(uc, 2, 0)
        elif address == F_PREINIT:
            calls.append(("PreInit", arg(uc, 0)))
            stdcall_return(uc, 1, 0)
        elif address == F_HOOK:
            calls.append(("PRACXHook", arg(uc, 0)))
            stdcall_return(uc, 1, 0)
        elif address == F_INIT:
            calls.append(("Init", arg(uc, 0)))
            stdcall_return(uc, 1, 0)
        elif address == F_GETLASTERROR:
            calls.append(("GetLastError",))
            stdcall_return(uc, 0, last_error)
        elif address == F_MSGBOX:
            calls.append(("MessageBoxA", arg(uc, 0), _read_cstr(uc, arg(uc, 1)), _read_cstr(uc, arg(uc, 2)), arg(uc, 3)))
            stdcall_return(uc, 4, 1)
        elif address == F_EXIT:
            calls.append(("ExitProcess", arg(uc, 0)))
            uc.emu_stop()

    uc.hook_add(UC_HOOK_CODE, on_code, begin=FAKE, end=FAKE + 0x100)

    # entry state = what the stub leaves at its `call eax`: eax = PRACXHook, [esp] = hPrax, [esp+4] = ret
    esp = STACK + 0x8000
    uc.mem_write(esp, struct.pack("<II", H_PRAX, RET_TO_WALKER))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EAX, F_HOOK)
    uc.reg_write(UC_X86_REG_ESI, 0x5E5E5E5E)
    uc.reg_write(UC_X86_REG_EDI, 0x7D7D7D7D)
    uc.reg_write(UC_X86_REG_EBX, 0x3B3B3B3B)
    try:
        uc.emu_start(THUNK_VA, 0, count=20000)
    except unicorn.UcError:
        pass
    return uc, esp, calls


def _assert_balanced(uc, esp):
    # the sentinel is a HLT: unicorn stops on it with EIP just past it
    assert uc.reg_read(UC_X86_REG_EIP) in (RET_TO_WALKER, RET_TO_WALKER + 1), "did not return to the startup-table walker"
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 8, "hPrax + the return address must both be consumed"
    assert uc.reg_read(UC_X86_REG_ESI) == 0x5E5E5E5E
    assert uc.reg_read(UC_X86_REG_EDI) == 0x7D7D7D7D
    assert uc.reg_read(UC_X86_REG_EBX) == 0x3B3B3B3B


def test_full_chain_preinit_then_pracx_then_init():
    uc, esp, calls = _run()
    assert calls == [
        ("LoadLibraryA", "uimod"),
        ("GetProcAddress", H_UIMOD, 2),
        ("PreInit", H_PRAX),
        ("PRACXHook", H_PRAX),
        ("GetProcAddress", H_UIMOD, 1),
        ("Init", H_UIMOD),
    ]
    _assert_balanced(uc, esp)


def test_no_dll_shows_the_error_and_exits_before_the_game():
    """The boot guard (user decision 2026-10-28): a uimod.dll that does not load is a half-applied mod,
    never a game without the mod. The message names the DLL, carries the Windows error code and
    says to reinstall; PRACXHook is never reached; ExitProcess(1) ends the run."""
    uc, esp, calls = _run(have_dll=False, last_error=126)
    assert calls[0] == ("LoadLibraryA", "uimod")
    assert calls[1] == ("GetLastError",)
    assert calls[2][0] == "MessageBoxA"
    hwnd, text, caption, flags = calls[2][1:]
    assert hwnd == 0 and flags == 0x10, (hwnd, flags)
    assert caption == "Longevity Vaccine"
    assert "could not load uimod.dll" in text and "(Windows error 126)" in text, text
    assert "Reinstall the Longevity Vaccine mod" in text and ".bak" in text, text
    assert calls[3] == ("ExitProcess", 1)
    assert len(calls) == 4, calls
    assert not any(c[0] in ("PRACXHook", "PreInit", "Init") for c in calls)


def test_the_error_code_is_rendered_in_decimal_for_any_value():
    for code in (0, 5, 1114, 65535, 0xFFFFFFFF):
        uc, esp, calls = _run(have_dll=False, last_error=code)
        text = calls[2][2]
        assert f"(Windows error {code})" in text, (code, text)


def test_yaml_bytes_are_the_assemblers_output():
    """patches.yaml carries the bytes by hand; the assembler is the source. Strings are addressed
    absolutely, so a moved symbol without a re-run would silently point at the old cave offset."""
    import assemble_uimod_preload as A
    assert bytes(THUNK_CODE) == A.assemble()
    assert bytes(STRINGS) == A.strings()
    assert THUNK_VA == A.PCAVE2_VA + A.LAYOUT["thunk_uimod_preload"]
    assert STRINGS_VA == A.PCAVE2_VA + A.LAYOUT["g_boot_strings"]
    # The thunk addresses g_boot_strings / g_boot_msg as RAW absolute bytes (no {abs32:} template), so a yaml
    # symbol move without an assembler re-run would leave it pointing at the old offsets. Pin the yaml symbols
    # to the assembler's LAYOUT, and the message pointer bytes to the symbol (audit 2026-10-29).
    assert SYMTAB["g_boot_strings"] == A.PCAVE2_VA + A.LAYOUT["g_boot_strings"]
    assert SYMTAB["g_boot_msg"] == A.PCAVE2_VA + A.LAYOUT["g_boot_msg"]
    assert struct.pack("<I", SYMTAB["g_boot_msg"]) in bytes(THUNK_CODE), "the thunk does not reference g_boot_msg"
    assert struct.pack("<I", SYMTAB["g_boot_strings"]) in bytes(THUNK_CODE), "the thunk does not reference g_boot_strings"


def test_old_dll_without_preinit_still_gets_init_after_pracx():
    uc, esp, calls = _run(have_preinit=False)
    assert calls == [
        ("LoadLibraryA", "uimod"),
        ("GetProcAddress", H_UIMOD, 2),
        ("PRACXHook", H_PRAX),
        ("GetProcAddress", H_UIMOD, 1),
        ("Init", H_UIMOD),
    ]
    _assert_balanced(uc, esp)


def test_missing_init_still_runs_pracx():
    uc, esp, calls = _run(have_init=False)
    assert calls == [
        ("LoadLibraryA", "uimod"),
        ("GetProcAddress", H_UIMOD, 2),
        ("PreInit", H_PRAX),
        ("PRACXHook", H_PRAX),
        ("GetProcAddress", H_UIMOD, 1),
    ]
    _assert_balanced(uc, esp)


def test_site_replaces_the_stubs_call_and_ret():
    s = _site()
    va = s["virtual_addr"]
    va = int(va, 16) if isinstance(va, str) else va
    assert va == SITE_VA
    assert s["length"] == 8
    assert ap.ByteTemplate(s["original_bytes"]).resolve(va, SYMTAB)[:3] == b"\xFF\xD0\xC3"
    new = ap.ByteTemplate(s["new_bytes"]).resolve(va, SYMTAB)
    assert new == b"\x68" + struct.pack("<I", THUNK_VA) + b"\xC3\x00\x00"


def test_thunk_matches_the_keystone_source():
    keystone = pytest.importorskip("keystone", reason="keystone absent — source parity unverified")  # noqa: F841
    import assemble_uimod_preload as src
    assert src.PCAVE2_VA + src.LAYOUT["thunk_uimod_preload"] == THUNK_VA
    assert src.assemble() == THUNK_CODE
