param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"

Set-Location $RepoRoot

$versionLine = Select-String -Path "backend\pyproject.toml" -Pattern '^version = ' | Select-Object -First 1
$version = if ($versionLine) { $versionLine.Line -replace '.*"(.*)".*', '$1' } else { "0.0.0" }
$zipName = "Binderdash-$version-win64.zip"

if (-not (Test-Path "backend\static")) {
    Write-Host "Building frontend..."
    Push-Location frontend
    pnpm install
    pnpm run build
    Pop-Location
}

Write-Host "Installing dependencies..."
$filteredReq = Join-Path $env:TEMP "binderdash-requirements-no-uvloop.txt"
Get-Content (Join-Path $RepoRoot "backend\requirements.txt") |
    Where-Object { $_ -notmatch '^uvloop==' } |
    Set-Content -Path $filteredReq -Encoding utf8
uv pip install -r $filteredReq
uv pip install pywebview pyinstaller

Write-Host "Running PyInstaller..."
pyinstaller --noconfirm desktop/binderdash.spec

$distDir = Join-Path $RepoRoot "dist\Binderdash"
if (-not (Test-Path $distDir)) {
    throw "Expected dist\Binderdash after PyInstaller build"
}

# Every file extracted from a downloaded zip inherits its mark of the web, and
# .NET Framework refuses to load an assembly from the internet zone. pythonnet's
# netfx loader then fails to resolve Python.Runtime.Loader.Initialize and the app
# exits before the window opens, on a machine that is otherwise set up correctly.
# The opt-in below is read by the default AppDomain of this process only.
$exeConfig = @"
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <runtime>
    <loadFromRemoteSources enabled="true"/>
  </runtime>
</configuration>
"@
Set-Content -Path (Join-Path $distDir "Binderdash.exe.config") -Value $exeConfig -Encoding UTF8

$readme = @"
Binderdash $version (Windows)

1. Unzip this folder anywhere.
2. Open the Binderdash-$version folder and run Binderdash.exe.

Requires Microsoft Edge WebView2 runtime:
https://developer.microsoft.com/en-us/microsoft-edge/webview2/

If SmartScreen warns about an unsigned app, choose More info → Run anyway.
"@

$staging = Join-Path $RepoRoot "dist\windows-staging"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Path $staging | Out-Null
# Versioned folder name: extracting two builds of the same version-less
# "Binderdash" folder merges them, leaving a mix of both on disk.
Copy-Item -Recurse $distDir (Join-Path $staging "Binderdash-$version")
Set-Content -Path (Join-Path $staging "README.txt") -Value $readme -Encoding UTF8

$zipPath = Join-Path $RepoRoot "dist\$zipName"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath

Write-Host "Created $zipPath"
