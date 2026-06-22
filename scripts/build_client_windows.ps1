param(
    [string]$OutputDir = "dist/client/windows",
    [string]$PyInstallerVersion = "6.21.0",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$buildRoot = Join-Path $root "build/client-windows"
$venv = Join-Path $buildRoot ".venv"
$python = Join-Path $venv "Scripts/python.exe"
$outputPath = Join-Path $root $OutputDir
$entrypoint = Join-Path $root "scripts/pyinstaller/buckshot_client_entry.py"

if ($Clean -and (Test-Path -LiteralPath $buildRoot)) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}

if (-not (Test-Path -LiteralPath $python)) {
    New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
    python -m venv $venv
}

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

& $python -m pip install --upgrade pip
& $python -m pip install "pyinstaller==$PyInstallerVersion"

Push-Location $root
try {
    & $python -m PyInstaller `
        --clean `
        --noconfirm `
        --onefile `
        --console `
        --name buckshot-client `
        --paths $root `
        --distpath $outputPath `
        --workpath (Join-Path $buildRoot "work") `
        --specpath (Join-Path $buildRoot "spec") `
        $entrypoint
}
finally {
    Pop-Location
}

$binary = Join-Path $outputPath "buckshot-client.exe"
if (-not (Test-Path -LiteralPath $binary)) {
    throw "Windows client binary was not produced: $binary"
}

Write-Output "Windows client binary: $binary"
