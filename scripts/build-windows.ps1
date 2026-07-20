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
& $venvPython (Join-Path $projectRoot "scripts\make-icon.py")

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
    "--icon", (Join-Path $projectRoot "assets\app-icon.ico"),
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

$checksumPath = Join-Path $releaseDir "SHA256SUMS.txt"
$checksumLines = Get-ChildItem -LiteralPath $releaseDir -Filter "*.exe" |
    Sort-Object Name |
    ForEach-Object {
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        "$hash  $($_.Name)"
    }
[System.IO.File]::WriteAllLines($checksumPath, $checksumLines, [System.Text.UTF8Encoding]::new($false))

Get-ChildItem -LiteralPath $releaseDir -Filter "*.exe" | Select-Object Name, Length, LastWriteTime
