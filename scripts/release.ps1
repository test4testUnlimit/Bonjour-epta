# Build a lightweight launcher exe (mirrors OpenWind release flow).
# Output: release\BonjurLauncher.exe - the ONLY file to distribute.
# Recipients run it; launcher installs Python 3.10+ via winget (if missing),
# extracts embedded app.zip, pip-installs deps, then runs main.py.
#
# Versioning (see notes/versioning.md):
#   -Bump patch  -> Z += 1            (default for code changes needing test/fix)
#   -Bump minor  -> Y += 1, Z = 0     (significant change / new feature)
#   -Bump major  -> X += 1, Y = 0, Z = 0   (ONLY when the user explicitly says so)
#   (no -Bump)   -> build current VERSION as-is
param(
    [ValidateSet("patch", "minor", "major")]
    [string]$Bump
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Find-RealPython {
    try {
        $exe = (& py -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
        if ($exe) { $exe = [string]$exe.Trim() }
        if ($exe -and (Test-Path -LiteralPath $exe) -and ($exe -notmatch '(?i)\\WindowsApps\\')) { return $exe }
    } catch {}
    foreach ($g in @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe"
    )) {
        $hit = Get-ChildItem $g -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
        if ($hit -and ($hit.FullName -notmatch '(?i)\\WindowsApps\\')) { return $hit.FullName }
    }
    throw "Python 3 not found. Install from python.org (enable py launcher). Do not use the Microsoft Store stub."
}
$Python = Find-RealPython
Write-Host "Python = $Python"

# ── 0. VERSION is source of truth ─────────────────────────────────
$vf = Join-Path $root "VERSION"
if (-not (Test-Path $vf)) { throw "Missing VERSION file at repo root" }
$ver = (Get-Content $vf -First 1).Trim()
if (-not $ver) { throw "VERSION file is empty" }

# ── 0a. optional version bump ─────────────────────────────────────
if ($Bump) {
    if ($ver -notmatch '^\d+\.\d+\.\d+$') {
        throw "VERSION '$ver' is not X.Y.Z - cannot bump automatically"
    }
    $parts = $ver.Split('.')
    [int]$x = $parts[0]; [int]$y = $parts[1]; [int]$z = $parts[2]
    switch ($Bump) {
        "patch" { $z++ }
        "minor" { $y++; $z = 0 }
        "major" { $x++; $y = 0; $z = 0 }
    }
    $old = $ver
    $ver = "$x.$y.$z"
    Set-Content -Path $vf -Value $ver -NoNewline -Encoding ascii
    Write-Host "Version bump ($Bump): $old -> $ver"
}
Write-Host "VERSION = $ver"

# ── 1. always rebuild app.ico from app.png (multi-size) ───────────
$png = Join-Path $root "app.png"
$ico = Join-Path $root "app.ico"
if (Test-Path $png) {
    Write-Host "Generating multi-size app.ico from app.png..."
    & $Python -c @"
from pathlib import Path
from PIL import Image
img = Image.open(r'$png').convert('RGBA')
sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
out = Path(r'$ico')
img.save(out, format='ICO', sizes=sizes)
print('wrote', out, out.stat().st_size, 'bytes')
"@
}
# copy icon into launcher dir (csproj references it there)
$launcherIco = Join-Path $root "launcher\app.ico"
if (Test-Path $ico) { Copy-Item $ico $launcherIco -Force }

# ── 2. build app.zip payload (source only — no pycache/git/notes) ──
$staging = Join-Path $root "build\payload"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging -Force | Out-Null

$includeTop = @("main.py", "requirements.txt", "app.ico", "VERSION")
foreach ($f in $includeTop) {
    $src = Join-Path $root $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $staging $f) }
}
# app.png: ship a 256x256 copy as fallback icon source (app.ico is preferred)
if (Test-Path (Join-Path $root "app.png")) {
    & $Python -c @"
from PIL import Image
img = Image.open(r'$(Join-Path $root 'app.png')').convert('RGBA')
img.resize((256, 256), Image.Resampling.LANCZOS).save(r'$(Join-Path $staging 'app.png')')
"@
}

# field repro HTML (also under app/assets via the app/ copy below)
$repro = Join-Path $root "notes\repro-field-bugs.html"
if (Test-Path $repro) {
    Copy-Item $repro (Join-Path $staging "repro-field-bugs.html") -Force
}

$appSrc = Join-Path $root "app"
$appDst = Join-Path $staging "app"
New-Item -ItemType Directory -Path $appDst -Force | Out-Null
Get-ChildItem $appSrc -Recurse -File | Where-Object {
    $_.FullName -notmatch '\\__pycache__\\' -and $_.Extension -ne '.pyc'
} | ForEach-Object {
    $rel = $_.FullName.Substring($appSrc.Length + 1)
    $dst = Join-Path $appDst $rel
    $dstDir = Split-Path $dst -Parent
    if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }
    Copy-Item $_.FullName $dst
}

$payloadZip = Join-Path $root "launcher\app.zip"
if (Test-Path $payloadZip) { Remove-Item $payloadZip -Force }
Write-Host "Zipping payload -> $payloadZip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($staging, $payloadZip)

# ── 3. dotnet publish launcher ────────────────────────────────────
$launcherProj = Join-Path $root "launcher\BonjurLauncher.csproj"
$publishDir = Join-Path $root "build\launcher-publish"
if (Test-Path $publishDir) { Remove-Item $publishDir -Recurse -Force }
Write-Host "dotnet publish $launcherProj"
dotnet publish $launcherProj -c Release -o $publishDir

# ── 4. stage release ──────────────────────────────────────────────
$releaseDir = Join-Path $root "release"
if (-not (Test-Path $releaseDir)) { New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null }
$builtExe = Join-Path $publishDir "BonjurLauncher.exe"
if (-not (Test-Path $builtExe)) { throw "Build failed: $builtExe not found" }

$ver = (Get-Content (Join-Path $root "VERSION") -First 1).Trim()
$outName = "BonjurLauncher_$ver.exe"
$outPath = Join-Path $releaseDir $outName
Copy-Item $builtExe $outPath -Force
# One artifact, version in the name — a second unversioned copy only made it
# ambiguous which build was actually sent.
Get-ChildItem $releaseDir -Filter "bonjour-epta-setup.exe" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Email this file (~$((Get-Item $outPath).Length) bytes):"
Write-Host "  $outPath"