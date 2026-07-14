# Build a lightweight launcher exe (mirrors OpenWind release flow).
# Output: release\BonjurLauncher.exe — the ONLY file to distribute.
# Recipients run it; launcher installs Python 3.12 via winget (if missing),
# extracts embedded app.zip, pip-installs deps, then runs main.py.
param(
    [switch]$Bump
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

# ── 1. ensure app.ico exists (from app.png) ───────────────────────
$png = Join-Path $root "app.png"
$ico = Join-Path $root "app.ico"
if ((Test-Path $png) -and -not (Test-Path $ico)) {
    Write-Host "Generating app.ico from app.png..."
    python -c @"
from pathlib import Path
from PIL import Image
img = Image.open(r'$png').convert('RGBA')
sizes = (16, 24, 32, 48, 64, 128, 256)
icons = [img.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
out = Path(r'$ico')
icons[0].save(out, format='ICO', sizes=[(i.width, i.height) for i in icons], append_images=icons[1:])
print('wrote', out)
"@
}
# copy icon into launcher dir (csproj references it there)
$launcherIco = Join-Path $root "launcher\app.ico"
if (Test-Path $ico) { Copy-Item $ico $launcherIco -Force }

# ── 2. build app.zip payload (source only — no pycache/git/notes) ──
$staging = Join-Path $root "build\payload"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging -Force | Out-Null

$includeTop = @("main.py", "requirements.txt", "app.ico")
foreach ($f in $includeTop) {
    $src = Join-Path $root $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $staging $f) }
}
# app.png: ship a 256x256 copy as fallback icon source (app.ico is preferred)
if (Test-Path (Join-Path $root "app.png")) {
    python -c @"
from PIL import Image
img = Image.open(r'$(Join-Path $root 'app.png')').convert('RGBA')
img.resize((256, 256), Image.Resampling.LANCZOS).save(r'$(Join-Path $staging 'app.png')')
"@
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

$ver = ""
$vf = Join-Path $root "VERSION"
if (Test-Path $vf) { $ver = (Get-Content $vf -First 1).Trim() }
if (-not $ver) {
    # read from theme.py
    $theme = Get-Content (Join-Path $root "app\theme.py") -Raw
    if ($theme -match 'APP_VERSION\s*=\s*"([^"]+)"') { $ver = $matches[1] }
}
$outName = if ($ver) { "BonjurLauncher_$ver.exe" } else { "BonjurLauncher.exe" }
$outPath = Join-Path $releaseDir $outName
Copy-Item $builtExe $outPath -Force
Write-Host ""
Write-Host "Done: $outPath ($((Get-Item $outPath).Length) bytes)"
