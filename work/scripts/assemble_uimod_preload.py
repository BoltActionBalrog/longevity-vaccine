#!/usr/bin/env python
# Keystone assembler for thunk_uimod_preload (group uimod_bootstrap): the two-phase DLL
# bootstrap, with the BOOT GUARD (user decision 2026-10-28).
#
# PRACX's own loader stub (_SELFMOD 0x668160) ends `call eax; ret` at 0x668187 with eax = prax
# ordinal #1 (PRACXHook) and hPrax on the stack. PRACXHook switches the display mode
# (SetVideoMode -> ChangeDisplaySettings) before anything of ours has run, so a non-native
# [PRACX] ScreenWidth x ScreenHeight used to blank the monitor once at boot: PRACX's switch,
# then uimod's restore. The site now reads `push thunk_uimod_preload; ret`, and this thunk
# runs, in order:
#
#   LoadLibraryA("uimod")                      (FAILS -> the boot guard below, never the game)
#   GetProcAddress(hUimod, #2) = PreInit       (absent -> skip)   PreInit(hPrax) [__stdcall]
#   PRACXHook(hPrax)                           [__stdcall]        <- the call the site replaced
#   GetProcAddress(hUimod, #1) = Init          (absent -> skip)   Init(hUimod) [__stdcall]
#   ret to the CRT initializer-table walker (_initterm), hPrax discarded, esi/edi preserved
#
# PreInit redirects prax.dll's ChangeDisplaySettingsA import to a no-op (and sets the process
# DPI-aware) BEFORE PRACXHook can switch; Init is the ordinary entry, unchanged. A DLL without
# ordinal #2 (older uimod) or #1 falls back to the step before, as before.
#
# BOOT GUARD. A uimod.dll that does not load used to mean "the game runs without the mod",
# silently. That was never safe: the exe carries the patch set and the DLL completes it
# (Design Workshop depth buffer and three more sites on the PRACX + Thinker build; every
# runtime fix on both builds), and the usual causes -- one of the five ffmpeg libraries
# missing, quarantined by an antivirus, lost in an interrupted update, or unloadable on an old
# Windows -- leave the player with a half-applied mod and no message (audit 2026-10-28). Now:
#
#   LoadLibraryA("uimod") == 0  ->  GetLastError() -> compose into g_boot_msg (a BSS slot in
#   this cave): PART1 + decimal error code + PART2 -> MessageBoxA(NULL, msg, CAPTION,
#   MB_OK | MB_ICONERROR) -> ExitProcess(1). The game never starts.
#
# KERNEL32 / USER32 IAT slots of the exe: ds:[0x669120] LoadLibraryA, ds:[0x669124]
# GetProcAddress, ds:[0x669144] GetLastError, ds:[0x66918C] ExitProcess, ds:[0x669318]
# MessageBoxA. The strings live inside the thunk and are addressed ABSOLUTELY (the thunk is
# assembled at its cave offset; they live in the DATA content g_boot_strings right after the code),
# so re-run this script whenever LAYOUT moves and paste both byte strings into patches.yaml (tests\test_uimod_preload_thunk.py checks yaml == assembler).

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0xA0C000
LOADLIBRARYA_SLOT = 0x669120
GETPROCADDRESS_SLOT = 0x669124
GETLASTERROR_SLOT = 0x669144
EXITPROCESS_SLOT = 0x66918C
MESSAGEBOXA_SLOT = 0x669318
MB_OK_ICONERROR = 0x10

LAYOUT = {
    'thunk_uimod_preload': 0x35340,   # 2026-10-28: moved from 0xD490 (78 B) for the boot guard's growth (code only)
    'g_boot_strings': 0x35440,        # data: PART1, PART2, CAPTION (NUL-terminated, in that order)
    'g_boot_msg': 0x35800,            # BSS, 0x200: the composed message (PART1 + digits + PART2)
}
BOOT_MSG_SIZE = 0x200

PART1 = "Longevity Vaccine could not load uimod.dll (Windows error "
PART2 = (").\n\n"
         "One of the mod's files is missing or damaged, so the game cannot start safely with the mod "
         "installed.\n\n"
         "Reinstall the Longevity Vaccine mod to repair it. To play without the mod, restore this program "
         "from its .bak backup copy.")
CAPTION = "Longevity Vaccine"


def _bytes(s: str) -> str:
    return ", ".join(f"0x{b:02X}" for b in s.encode("ascii") + b"\0")


def _strip(asm: str) -> str:
    return "\n".join(line.split('#', 1)[0].rstrip() for line in asm.splitlines())


def strings() -> bytes:
    """g_boot_strings: the three NUL-terminated strings, a DATA content of the cave (code thunks must
    end in a control transfer and hold no data -- tests/test_thunk_disasm.py)."""
    return b"".join(s.encode("ascii") + b"\0" for s in (PART1, PART2, CAPTION))


def asm_text() -> str:
    """The code; the strings are addressed absolutely in g_boot_strings."""
    msg = PCAVE2_VA + LAYOUT['g_boot_msg']
    part1_va = PCAVE2_VA + LAYOUT['g_boot_strings']
    part2_va = part1_va + len(PART1) + 1
    caption_va = part2_va + len(PART2) + 1
    assert len(PART1) + 10 + len(PART2) + 1 < BOOT_MSG_SIZE
    # Comments are '#' (keystone reads ';' as an instruction separator); stripped before assembly.
    return f"""
thunk_uimod_preload:
    push esi                        # [esp]=esi [esp+4]=hPrax [esp+8]=ret
    push edi                        # [esp]=edi [esp+4]=esi [esp+8]=hPrax [esp+12]=ret
    mov  esi, eax                   # esi = PRACXHook
    xor  edi, edi                   # edi = hUimod (0 = not loaded)
    call name_end                   # push &"uimod"
    .byte 0x75, 0x69, 0x6D, 0x6F, 0x64, 0x00
name_end:
    call dword ptr [{LOADLIBRARYA_SLOT:#x}]       # LoadLibraryA("uimod") -> eax
    mov  edi, eax
    test edi, edi
    jz   fail                       # the boot guard: no game without the DLL
    push 2
    push edi
    call dword ptr [{GETPROCADDRESS_SLOT:#x}]     # GetProcAddress(hUimod, #2) = PreInit
    test eax, eax
    jz   pracx
    push dword ptr [esp+8]          # hPrax
    call eax                        # PreInit(hPrax) [__stdcall]
pracx:
    push dword ptr [esp+8]          # hPrax
    call esi                        # PRACXHook(hPrax) [__stdcall]
    test edi, edi
    jz   done
    push 1
    push edi
    call dword ptr [{GETPROCADDRESS_SLOT:#x}]     # GetProcAddress(hUimod, #1) = Init
    test eax, eax
    jz   done
    push edi
    call eax                        # Init(hUimod) [__stdcall]
done:
    pop  edi
    pop  esi
    pop  eax                        # discard hPrax (the prax stub's own push)
    ret
fail:
    call dword ptr [{GETLASTERROR_SLOT:#x}]       # eax = the Windows error code
    mov  edi, {msg:#x}              # g_boot_msg
    mov  esi, {part1_va:#x}            # &PART1
    mov  ecx, {len(PART1)}
    rep  movsb                      # PART1 (no NUL)
    mov  ecx, 10
    sub  esp, 16                    # digits, composed backwards on the stack
    lea  ebx, [esp+15]
    mov  byte ptr [ebx], 0
conv:
    xor  edx, edx
    div  ecx
    dec  ebx
    add  dl, 0x30
    mov  byte ptr [ebx], dl
    test eax, eax
    jnz  conv
copy_digits:
    mov  al, byte ptr [ebx]
    inc  ebx
    test al, al
    jz   digits_done
    stosb
    jmp  copy_digits
digits_done:
    add  esp, 16
    mov  esi, {part2_va:#x}            # &PART2
    mov  ecx, {len(PART2) + 1}
    rep  movsb                      # PART2 with its NUL
    push {MB_OK_ICONERROR:#x}       # MB_OK | MB_ICONERROR
    push {caption_va:#x}               # &CAPTION
    push {msg:#x}
    push 0
    call dword ptr [{MESSAGEBOXA_SLOT:#x}]        # MessageBoxA(NULL, msg, caption, flags)
    push 1
    call dword ptr [{EXITPROCESS_SLOT:#x}]        # ExitProcess(1): never returns (the thunk ends here)
"""


def assemble() -> bytes:
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    va = PCAVE2_VA + LAYOUT['thunk_uimod_preload']
    enc, _ = ks.asm(_strip(asm_text()), va)
    code = bytes(enc)
    assert va + len(code) <= PCAVE2_VA + LAYOUT['g_boot_strings'], "code runs into g_boot_strings"
    assert PCAVE2_VA + LAYOUT['g_boot_strings'] + len(strings()) <= PCAVE2_VA + LAYOUT['g_boot_msg']
    return code


def main():
    code, data = assemble(), strings()
    print(f"thunk_uimod_preload @ pcave2+0x{LAYOUT['thunk_uimod_preload']:X} "
          f"(VA 0x{PCAVE2_VA + LAYOUT['thunk_uimod_preload']:X}), {len(code)} bytes; "
          f"g_boot_strings @ pcave2+0x{LAYOUT['g_boot_strings']:X}, {len(data)} bytes; "
          f"g_boot_msg @ pcave2+0x{LAYOUT['g_boot_msg']:X} ({BOOT_MSG_SIZE} B BSS)")
    print("code:", " ".join(f"{b:02X}" for b in code))
    print("data:", " ".join(f"{b:02X}" for b in data))


if __name__ == '__main__':
    main()
