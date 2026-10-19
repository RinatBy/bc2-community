$ErrorActionPreference = 'Stop'
$communityRoot = Split-Path -Parent $PSScriptRoot
Push-Location $communityRoot
try {
    $launcherPython = Join-Path $communityRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $launcherPython)) { throw 'Create the project .venv and install requirements-lock.txt first.' }
    $env:PYTHONPATH = Join-Path $communityRoot 'launcher'
    $env:PYTHONUTF8 = '1'
    & $launcherPython -m unittest discover -s launcher/tests
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $launcherPython -m PyInstaller --noconfirm --clean launcher/BC2Launcher.spec
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    & $launcherPython -m pip freeze | Set-Content -LiteralPath requirements-lock.txt -Encoding utf8
    Compress-Archive -LiteralPath 'dist\BC2Launcher' -DestinationPath 'dist\BC2Launcher-test-0.1.0.zip' -Force
    Get-FileHash -LiteralPath 'dist\BC2Launcher-test-0.1.0.zip' -Algorithm SHA256
} finally { Pop-Location }
