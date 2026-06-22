param(
    [string]$OutputDir = "dist/client/linux",
    [string]$PyInstallerVersion = "6.21.0"
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputPath = Join-Path $root $OutputDir

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

docker build `
    -f (Join-Path $root "Dockerfile.client-linux") `
    --build-arg "PYINSTALLER_VERSION=$PyInstallerVersion" `
    --target export `
    --output "type=local,dest=$outputPath" `
    $root

$binary = Join-Path $outputPath "buckshot-client"
if (-not (Test-Path -LiteralPath $binary)) {
    throw "Linux client binary was not produced: $binary"
}

Write-Output "Linux client binary: $binary"
