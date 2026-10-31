# WRITES TO YOUR DESKTOP: creates or overwrites up to four "SMACX Frida Trace*.lnk" shortcuts,
# without asking. Nothing else is touched.
#
# Repoint the desktop Frida-trace shortcuts at the current trace hook, at
# 4K AND the two reference non-4K resolutions. Every UI fix must be verified at
# 4K + at least one non-4K res, so a trace MUST be launchable at all three
# without hand-editing args -- this script wires all of them in one shot.
#
# Usage:  pwsh -File repoint-trace-shortcut.ps1 hook_<name>.js [-Pre frida_log_append.js]
#   Arg may be a bare hook .js name (resolved against work\scripts) or full path.
#   (Legacy: a run-frida-*.bat arg still works -- repoints only the plain 4K shortcut.)
#
# Builds shortcuts that target run-frida-at-res.bat <hook.js> <W> <H> [pre.js],
# which sets the resolution (crash-safe ini set/restore) then injects Frida.
# run-frida-at-res.bat self-elevates via UAC, so no Run-as-admin lnk flag needed.
param(
    [Parameter(Mandatory)][string]$Hook,
    [string]$Pre = '',
    [switch]$Pristine,   # target run-frida-pristine.bat (terranx_pristine.exe baseline) instead
    [switch]$Vanilla     # target run-frida-truevanilla.bat (un-PRACX'd terranx.exe) instead
)

$work = $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell

# --- Legacy path: a .bat arg repoints just the plain "SMACX Frida Trace" lnk ---
if ($Hook -match '\.bat$') {
    $target = if (Test-Path $Hook) { (Resolve-Path $Hook).Path } else { Join-Path $work $Hook }
    if (-not (Test-Path $target)) { throw "Trace bat not found: $target" }
    $lnk = Join-Path $desktop 'SMACX Frida Trace.lnk'
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = $target
    $s.Arguments = ''
    $s.WorkingDirectory = $work
    $s.Description = 'SMACX current Frida trace (repoint via repoint-trace-shortcut.ps1)'
    $s.IconLocation = 'D:\SmacxUi\tools\python\python.exe,0'
    $s.Save()
    "Repointed (legacy bat) $lnk -> $target"
    return
}

# --- Normal path: a hook .js wires all three resolutions ---
$hookName = Split-Path $Hook -Leaf            # run-frida-at-res.bat resolves it under work\scripts
$runner = if ($Vanilla) { 'run-frida-truevanilla.bat' }
          elseif ($Pristine) { 'run-frida-pristine.bat' }
          else { 'run-frida-at-res.bat' }
$atRes = Join-Path $work $runner
if (-not (Test-Path $atRes)) { throw "$runner not found: $atRes" }
if (-not (Test-Path (Join-Path $work "scripts\$hookName"))) {
    Write-Warning "Hook not found under work\scripts: $hookName (wiring anyway)"
}

# label -> "W H"  (plain shortcut = 4K). Edit/extend here to add reference resolutions.
$variants = [ordered]@{
    'SMACX Frida Trace'           = '3840 2160'
    'SMACX Frida Trace 1920x1080' = '1920 1080'
    'SMACX Frida Trace 1600x1200' = '1600 1200'
    'SMACX Frida Trace 1024x768'  = '1024 768'
}

foreach ($label in $variants.Keys) {
    $res = $variants[$label]
    $args = "$hookName $res"
    if ($Pre) { $args = "$args $Pre" }
    $lnk = Join-Path $desktop "$label.lnk"
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = $atRes
    $s.Arguments = $args
    $s.WorkingDirectory = $work
    $s.Description = "SMACX current Frida trace$(if ($Pristine) {' (PRISTINE exe)'}): $hookName @ $res"
    $s.IconLocation = 'D:\SmacxUi\tools\python\python.exe,0'
    $s.Save()
    "Repointed $lnk -> $runner $args"
}
