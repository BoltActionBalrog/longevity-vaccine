# Launch SMACX at a chosen resolution, then restore the original on exit.
#
# Sets ScreenWidth/ScreenHeight/WindowWidth/WindowHeight in the [PRACX] section of
# "Alpha Centauri.Ini", launches the game, waits for it to close, then puts the
# original values back. Only those keys (and the two [UIMod] keys below) are touched,
# so saves / prefs / faction choices you change in-game are preserved.
#
# [UIMod] VideoMode=0 + FullscreenModeSwitch=1 are forced for the run: Fullscreen with
# PRACX's real display-mode switch, so the DESKTOP is the game's resolution and a screen
# capture is the game's own pixels. (The mod's default Fullscreen keeps the monitor in
# its own mode and scales the game on the GPU -- every capture would be a resampled
# native-resolution image, useless for measuring a sub-4K bug.) A [UIMod] key that is
# absent is added for the run and removed again on exit.
#
# Crash-safe: the original values are stashed in a sidecar "<ini>.resbak" before the
# edit. If a previous run died without restoring, the next run recovers the true
# original from that sidecar before doing anything else, so the 4K settings can never
# be permanently clobbered by an interrupted test.
#
# Invoked by the thin wrappers run-1920x1080.bat / run-1600x1200.bat. Don't run directly
# unless you pass -Width/-Height and a resolved -GameDir/-GameExe.
# -DryRun (tests): edit the ini, copy it to "<ini>.dryrun", restore, never launch.
param(
    [Parameter(Mandatory = $true)][int]$Width,
    [Parameter(Mandatory = $true)][int]$Height,
    [Parameter(Mandatory = $true)][string]$GameDir,
    [Parameter(Mandatory = $true)][string]$GameExe,
    [switch]$DryRun,
    # Optional: launch the game UNDER FRIDA with this hook instead of directly. When set, the
    # script must already be running ELEVATED (frida injection needs SeDebugPrivilege) — the
    # run-frida-at-res.bat wrapper self-elevates first. frida.exe -f blocks until the session
    # ends (you type 'quit'), so the ini restore in the finally still fires at the right time.
    [string]$FridaHook = "",
    [string]$FridaDir  = "",
    # Optional: an extra script loaded as -l BEFORE the hook (e.g. frida_log_append.js to append
    # the log instead of truncating). Empty = none. Backward compatible: 3-arg callers pass nothing.
    [string]$FridaPre  = "",
    # Optional: -GameExe is a LAUNCHER that exits as soon as the game is up (Thinker's thinker.exe starts
    # terranx.exe suspended, injects thinker.dll, resumes and returns). Then the run waits for THIS process
    # (started from GameDir) instead, so the ini restore fires when the game closes, not when the launcher does.
    [string]$WaitExe   = "",
    # Optional: switch the DESKTOP to Width x Height before starting (restored on exit). Thinker's thinker.dll reads
    # the screen size at process start (GetSystemMetrics in its DllMain) -- before PRACX's own mode switch at window
    # creation -- so without this a Thinker test run at 1920x1080 believes the screen is the 4K desktop: its stretched
    # credits / interlude backgrounds come out 4K-sized (the top-left quarter shows) and its version label lands off
    # screen (measured 2026-10-30). PRACX then finds the mode already set.
    [switch]$SwitchDesktop
)

$ErrorActionPreference = "Stop"
$keys = @("ScreenWidth", "ScreenHeight", "WindowWidth", "WindowHeight")   # [PRACX]; always present
$uimodSection = "UIMod"
$uimodKeys = [ordered]@{ VideoMode = "0"; FullscreenModeSwitch = "1" }      # forced for the run; may be absent
$absent = "<absent>"                                                        # sidecar value for "key was not there"

$ini = Join-Path $GameDir "Alpha Centauri.Ini"
$bak = "$ini.resbak"
$exePath = Join-Path $GameDir $GameExe

if (-not (Test-Path -LiteralPath $ini))     { throw "ini not found: $ini" }
if (-not (Test-Path -LiteralPath $exePath)) { throw "exe not found: $exePath" }

# Read/replace a "Key=value" line (first match wins; these keys are unique to [PRACX]).
function Get-IniValue([string[]]$lines, [string]$key) {
    foreach ($l in $lines) { if ($l -match "^\s*$([regex]::Escape($key))\s*=\s*(.*)$") { return $Matches[1].Trim() } }
    return $null
}
function Set-IniValue([string[]]$lines, [string]$key, [string]$value) {
    return ,@($lines | ForEach-Object {
        if ($_ -match "^\s*$([regex]::Escape($key))\s*=") { "$key=$value" } else { $_ }
    })
}
# Section-aware read / write for the [UIMod] keys: @(bodyStart, bodyEnd) line indexes of a section
# (end exclusive), or $null when the ini has no such section.
function Get-SectionRange([string[]]$lines, [string]$section) {
    $start = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*\[(.+?)\]\s*$') {
            if ($start -ge 0) { return @($start, $i) }
            if ($Matches[1] -eq $section) { $start = $i + 1 }
        }
    }
    if ($start -ge 0) { return @($start, $lines.Count) }
    return $null
}
function Get-SectionValue([string[]]$lines, [string]$section, [string]$key) {
    $r = Get-SectionRange $lines $section
    if ($null -eq $r) { return $null }
    for ($i = $r[0]; $i -lt $r[1]; $i++) {
        if ($lines[$i] -match "^\s*$([regex]::Escape($key))\s*=\s*(.*)$") { return $Matches[1].Trim() }
    }
    return $null
}
# $value $null = remove the key. A missing key is inserted right under the section header; a missing
# section is appended.
function Set-SectionValue([string[]]$lines, [string]$section, [string]$key, $value) {
    $r = Get-SectionRange $lines $section
    $out = [System.Collections.Generic.List[string]]::new()
    if ($null -eq $r) {
        $out.AddRange([string[]]$lines)
        if ($null -ne $value) {
            if ($out.Count -gt 0 -and $out[$out.Count - 1].Trim() -ne '') { $out.Add('') }
            $out.Add("[$section]")
            $out.Add("$key=$value")
        }
        return ,$out.ToArray()
    }
    $found = $false
    $insertAt = $r[0]
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($i -ge $r[0] -and $i -lt $r[1] -and $lines[$i] -match "^\s*$([regex]::Escape($key))\s*=") {
            if (-not $found -and $null -ne $value) { $out.Add("$key=$value") }
            $found = $true                      # a removed key, or a duplicate line, is dropped
            continue
        }
        $out.Add($lines[$i])
        if ($i -eq $r[0] - 1) { $insertAt = $out.Count }   # right after the section header
    }
    if (-not $found -and $null -ne $value) { $out.Insert($insertAt, "$key=$value") }
    if ($null -eq $value) {
        # a section left without any key (one this script appended for the run) goes too, with the
        # blank line that separated it; an empty section and a missing one read the same to the game
        $r2 = Get-SectionRange $out.ToArray() $section
        if ($null -ne $r2) {
            $body = @(); for ($i = $r2[0]; $i -lt $r2[1]; $i++) { if ($out[$i].Trim() -ne '') { $body += $out[$i] } }
            if ($body.Count -eq 0) {
                $hdr = $r2[0] - 1
                $atEnd = ($r2[1] -eq $out.Count)
                $out.RemoveRange($hdr, $r2[1] - $hdr)          # header + its (blank) body
                # at the end of the file the blank line that separated the appended section goes too;
                # in the middle, the blank inside the body went with it and the one before stays as the separator
                if ($atEnd -and $hdr - 1 -ge 0 -and $hdr - 1 -lt $out.Count -and $out[$hdr - 1].Trim() -eq '') { $out.RemoveAt($hdr - 1) }
            }
        }
    }
    return ,$out.ToArray()
}
function Write-Keys([string]$path, [hashtable]$values) {
    $lines = Get-Content -LiteralPath $path
    foreach ($k in $keys) { $lines = Set-IniValue $lines $k $values[$k] }
    foreach ($k in $uimodKeys.Keys) {
        $v = $values[$k]
        if ($v -eq $absent) { $v = $null }
        $lines = Set-SectionValue $lines $uimodSection $k $v
    }
    Set-Content -LiteralPath $path -Value $lines -Encoding ASCII
}

# --- Recover from an interrupted previous run -------------------------------------
if (Test-Path -LiteralPath $bak) {
    Write-Host "[warn] found leftover $([IO.Path]::GetFileName($bak)) from an interrupted run; recovering original resolution first." -ForegroundColor Yellow
    $saved = Get-Content -LiteralPath $bak -Raw | ConvertFrom-StringData  # -Raw: one string -> one hashtable (piping lines makes an array of hashtables, breaking [$key] lookup)
    $h = @{}
    foreach ($k in $keys) { $h[$k] = $saved[$k] }
    foreach ($k in $uimodKeys.Keys) { $h[$k] = if ($saved.ContainsKey($k)) { $saved[$k] } else { $absent } }   # older sidecar: no [UIMod] entries
    Write-Keys $ini $h
    Remove-Item -LiteralPath $bak -Force
}

# --- Refuse to run while the game is open (it would race our edits) ----------------
$exeBase = [IO.Path]::GetFileNameWithoutExtension($GameExe)
if (Get-Process -Name $exeBase -ErrorAction SilentlyContinue) {
    throw "$GameExe is already running. Close it first, then re-run this script."
}
$waitBase = if ($WaitExe) { [IO.Path]::GetFileNameWithoutExtension($WaitExe) } else { "" }
if ($waitBase -and (Get-Process -Name $waitBase -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($GameDir, 'OrdinalIgnoreCase') })) {
    throw "$WaitExe is already running from $GameDir. Close it first, then re-run this script."
}

# --- Capture the (now guaranteed) original values ----------------------------------
$lines = Get-Content -LiteralPath $ini
$orig = @{}
foreach ($k in $keys) {
    $v = Get-IniValue $lines $k
    if ($null -eq $v) { throw "key '$k' not found in $ini" }
    $orig[$k] = $v
}
foreach ($k in $uimodKeys.Keys) {
    $v = Get-SectionValue $lines $uimodSection $k
    $orig[$k] = if ($null -eq $v) { $absent } else { $v }
}
Write-Host ("[info] original: {0}x{1} (window {2}x{3}); [UIMod] VideoMode={4} FullscreenModeSwitch={5}" -f $orig.ScreenWidth, $orig.ScreenHeight, $orig.WindowWidth, $orig.WindowHeight, $orig.VideoMode, $orig.FullscreenModeSwitch)

# Stash the original to the sidecar BEFORE editing (crash-safety net).
(@($keys) + @($uimodKeys.Keys) | ForEach-Object { "$_=$($orig[$_])" }) | Set-Content -LiteralPath $bak -Encoding ASCII

try {
    $test = @{ ScreenWidth = $Width; ScreenHeight = $Height; WindowWidth = $Width; WindowHeight = $Height }
    foreach ($k in $uimodKeys.Keys) { $test[$k] = $uimodKeys[$k] }
    Write-Keys $ini $test
    Write-Host ("[info] launching at {0}x{1} (Fullscreen, real display-mode switch) ..." -f $Width, $Height) -ForegroundColor Cyan
    if ($SwitchDesktop -and -not $DryRun) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace Longevity {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
  public struct DEVMODE {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
    public short dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra;
    public int dmFields, dmPositionX, dmPositionY, dmDisplayOrientation, dmDisplayFixedOutput;
    public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
    public short dmLogPixels;
    public int dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency;
    public int dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2, dmPanningWidth, dmPanningHeight;
  }
  public static class Display {
    [DllImport("user32.dll", CharSet = CharSet.Ansi)] public static extern int ChangeDisplaySettingsA(ref DEVMODE dm, int flags);
    [DllImport("user32.dll", EntryPoint = "ChangeDisplaySettingsA")] public static extern int RestoreDisplaySettings(IntPtr dm, int flags);
    public static int Set(int w, int h) {
      DEVMODE dm = new DEVMODE();
      dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
      dm.dmPelsWidth = w; dm.dmPelsHeight = h;
      dm.dmFields = 0x80000 | 0x100000;   // DM_PELSWIDTH | DM_PELSHEIGHT
      return ChangeDisplaySettingsA(ref dm, 0);
    }
    public static int Restore() { return RestoreDisplaySettings(IntPtr.Zero, 0); }
  }
}
"@
        $rc = [Longevity.Display]::Set($Width, $Height)
        if ($rc -ne 0) { throw "ChangeDisplaySettings($Width x $Height) failed: $rc (no such mode on this display?)" }
        $script:desktopSwitched = $true
        Write-Host ("[info] desktop switched to {0}x{1} so thinker.dll sees it at start" -f $Width, $Height) -ForegroundColor Cyan
        Start-Sleep -Milliseconds 500
    }

    if ($DryRun) {
        Copy-Item -LiteralPath $ini -Destination "$ini.dryrun" -Force
        Write-Host "[info] dry run: ini copied to $([IO.Path]::GetFileName("$ini.dryrun")); not launching." -ForegroundColor Cyan
    } elseif ($FridaHook) {
        $frida  = "D:\SmacxUi\tools\python\Scripts\frida.exe"
        $common = Join-Path $FridaDir "frida_common.js"
        $hook   = Join-Path $FridaDir $FridaHook
        if (-not (Test-Path -LiteralPath $frida))  { throw "frida.exe not found: $frida" }
        if (-not (Test-Path -LiteralPath $common)) { throw "frida_common.js not found: $common" }
        if (-not (Test-Path -LiteralPath $hook))   { throw "hook not found: $hook" }
        Write-Host ("[info] under Frida: {0}  (type %resume, open Customize Game Rules, then quit)" -f $FridaHook) -ForegroundColor Cyan
        # frida.exe -f spawns the exe by name from the game dir and BLOCKS until the session ends.
        $fargs = @('-f', $GameExe, '-l', $common)
        # scaling_laws.js publishes globalThis.SL (the shared scaling laws, JS port of
        # scripts/scaling_laws.py). Loaded for EVERY hook so none re-inlines the math.
        $laws = Join-Path $FridaDir 'scaling_laws.js'
        if (Test-Path -LiteralPath $laws) { $fargs += @('-l', $laws) }
        if ($FridaPre) {
            $pre = Join-Path $FridaDir $FridaPre
            if (-not (Test-Path -LiteralPath $pre)) { throw "pre-hook not found: $pre" }
            $fargs += @('-l', $pre)
            Write-Host ("[info] pre-hook: {0}" -f $FridaPre) -ForegroundColor Cyan
        }
        $fargs += @('-l', $hook)
        Push-Location -LiteralPath $GameDir
        try { & $frida @fargs } finally { Pop-Location }
    } else {
        $p = Start-Process -FilePath $exePath -WorkingDirectory $GameDir -PassThru
        if ($waitBase) {
            # the launcher returns once the game is up: find the game it started (by name, from GameDir) and wait on that
            $game = $null
            for ($i = 0; $i -lt 120 -and $null -eq $game; $i++) {
                Start-Sleep -Milliseconds 250
                $game = Get-Process -Name $waitBase -ErrorAction SilentlyContinue |
                        Where-Object { $_.Path -and $_.Path.StartsWith($GameDir, 'OrdinalIgnoreCase') } | Select-Object -First 1
            }
            if ($null -eq $game) { throw "$GameExe did not start $WaitExe from $GameDir within 30 s" }
            Write-Host ("[info] waiting on {0} (pid {1}) started by {2}" -f $WaitExe, $game.Id, $GameExe) -ForegroundColor Cyan
            $game.WaitForExit()
        } else {
            $p.WaitForExit()
        }
    }
    Write-Host "[info] game exited." -ForegroundColor Cyan
}
finally {
    # Restore the original keys (and the desktop mode) no matter how we got here (clean exit, error, Ctrl+C).
    if ($script:desktopSwitched) {
        [void][Longevity.Display]::Restore()
        Write-Host "[info] desktop mode restored." -ForegroundColor Green
    }
    Write-Keys $ini $orig
    if (Test-Path -LiteralPath $bak) { Remove-Item -LiteralPath $bak -Force }
    Write-Host ("[info] restored: {0}x{1}." -f $orig.ScreenWidth, $orig.ScreenHeight) -ForegroundColor Green
}
