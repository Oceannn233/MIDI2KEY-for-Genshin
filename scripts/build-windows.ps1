[CmdletBinding()]
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$localApp = Join-Path $projectRoot "local_app"
$buildVenv = Join-Path $projectRoot ".build-venv"
$venvPython = Join-Path $buildVenv "Scripts\python.exe"
$releaseDir = Join-Path $projectRoot "release\windows"

if (-not (Test-Path -LiteralPath $venvPython)) {
    $launcher = Get-Command py -ErrorAction Stop
    & $launcher.Source -3.11 -m venv $buildVenv
}

& $venvPython -m pip install --disable-pip-version-check --upgrade pip
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $localApp "requirements-build.txt")

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

$pyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "MIDI2KEY-for-Genshin",
    "--distpath", $releaseDir,
    "--workpath", (Join-Path $projectRoot "build\.pyinstaller"),
    "--specpath", (Join-Path $projectRoot "build\.pyinstaller-spec"),
    "--paths", $localApp,
    "--add-data", ((Join-Path $localApp "web") + ";web"),
    "--collect-all", "webview",
    "--hidden-import", "mido.backends.rtmidi",
    "--version-file", (Join-Path $projectRoot "build\windows\version_info.txt"),
    (Join-Path $localApp "lyre_bridge_server.py")
)
& $venvPython -m PyInstaller @pyInstallerArgs

$portableExe = Join-Path $releaseDir "MIDI2KEY-for-Genshin.exe"
if (-not (Test-Path -LiteralPath $portableExe)) {
    throw "Portable executable was not created."
}

if (-not $SkipInstaller) {
    $compilerCandidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $compiler = $compilerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $compiler) {
        throw "Inno Setup 6 was not found. Use -SkipInstaller for a portable-only build."
    }
    Push-Location (Join-Path $projectRoot "build\windows")
    try {
        & $compiler "installer.iss"
    }
    finally {
        Pop-Location
    }
}

Get-ChildItem -LiteralPath $releaseDir -Filter "*.exe" | Select-Object Name, Length, LastWriteTime
