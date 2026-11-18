param([switch]$Versioned, [switch]$InstallPreview, [string]$Version = '0.2.6',
      [int]$PolicyRevision = 7, [string]$MinimumLauncherVersion = '0.2.6',
      [string]$SigningKey, [string]$InnoCompiler)

$ErrorActionPreference = 'Stop'
$communityRoot = Split-Path -Parent $PSScriptRoot
Push-Location $communityRoot
try {
    $launcherPython = Join-Path $communityRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $launcherPython)) { throw 'Create the project .venv first.' }
    $env:PYTHONPATH = Join-Path $communityRoot 'launcher'
    $env:PYTHONUTF8 = '1'
    $env:SOURCE_DATE_EPOCH = '1767225600'
    & $launcherPython -c 'import sys;from bc2launcher.selfupdate.paths import validate_version;validate_version(sys.argv[1])' $Version
    if ($LASTEXITCODE -ne 0) { throw 'Invalid launcher version.' }
    if (-not $SigningKey) { $SigningKey = Join-Path $communityRoot '.secrets\release-signing.key' }
    if (-not (Test-Path -LiteralPath $SigningKey)) { throw 'Local signing key is required; no key will be generated.' }
    $outputRelative = if ($InstallPreview) { "dist\install-preview-$Version" } elseif ($Versioned) { "dist\local-$Version" } else { 'dist\release-build' }
    $outputRoot = [IO.Path]::GetFullPath((Join-Path $communityRoot $outputRelative))
    $allowedOutput = [IO.Path]::GetFullPath((Join-Path $communityRoot 'dist'))
    if (-not $outputRoot.StartsWith($allowedOutput + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Build output must stay inside community/dist.' }
    & $launcherPython -c 'import sys;from bc2launcher.selfupdate.paths import reject_links;reject_links(sys.argv[1])' $outputRoot
    if ($LASTEXITCODE -ne 0) { throw 'Build output cannot contain reparse points.' }
    New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
    $versionRoot = Join-Path $communityRoot "build\version-$Version"
    New-Item -ItemType Directory -Path $versionRoot -Force | Out-Null
    $env:BC2_BUILD_VERSION_FILE = Join-Path $versionRoot 'build-version.txt'
    [IO.File]::WriteAllText($env:BC2_BUILD_VERSION_FILE, $Version, [Text.Encoding]::ASCII)
    Remove-Item Env:BC2_INSTALL_PREVIEW_FILE -ErrorAction SilentlyContinue
    if ($InstallPreview) {
        $env:BC2_INSTALL_PREVIEW_FILE = Join-Path $versionRoot 'install-preview.flag'
        [IO.File]::WriteAllText($env:BC2_INSTALL_PREVIEW_FILE, 'local-only', [Text.Encoding]::ASCII)
    }
    & $launcherPython tools/build_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
    & $launcherPython tools/build_help.py
    if ($LASTEXITCODE -ne 0) { throw 'Shared help generation failed.' }
    & $launcherPython -m unittest discover -s launcher/tests
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $launcherPython -m PyInstaller --noconfirm --clean --distpath (Join-Path $outputRoot 'client') launcher/BC2Launcher.spec
    if ($LASTEXITCODE -ne 0) { throw 'Client build failed.' }
    & $launcherPython -m PyInstaller --noconfirm --clean --distpath (Join-Path $outputRoot 'bootstrap') launcher/BC2Bootstrap.spec
    if ($LASTEXITCODE -ne 0) { throw 'Bootstrap build failed.' }
    $clientPath = Join-Path $outputRoot 'client\BC2Client'
    $bootstrapExe = Join-Path $outputRoot 'bootstrap\BC2Launcher.exe'
    foreach ($component in @(@{name='client';exe=(Join-Path $clientPath 'BC2Client.exe')},@{name='bootstrap';exe=$bootstrapExe})) {
        $reportPath = Join-Path $outputRoot ($component.name + '-self-test.json')
        if (Test-Path -LiteralPath $reportPath) { Remove-Item -LiteralPath $reportPath }
        $probe = Start-Process -FilePath $component.exe -ArgumentList @('--self-test','--report',('"'+$reportPath+'"')) -WindowStyle Hidden -PassThru
        if (-not $probe.WaitForExit(60000)) { Stop-Process -Id $probe.Id -ErrorAction SilentlyContinue; throw 'Frozen self-test timed out.' }
        if ($probe.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath)) { throw ('Frozen self-test failed: '+$component.name) }
        $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
        if (-not $report.ok) { throw 'Frozen component did not confirm startup.' }
        if ($component.name -eq 'client' -and (-not ($report.qt_imports_ok -and $report.resources_ok) -or $report.version -ne $Version)) { throw 'Client Qt/resources/version mismatch.' }
        if ($component.name -eq 'client') {
            if ($InstallPreview.IsPresent -ne [bool]$report.install_preview) { throw 'Client preview mode differs from the requested build.' }
            if ((Test-Path -LiteralPath 'launcher/assets/game-install/profile.json') -and -not $report.libtorrent_version) { throw 'Game installation dependencies are missing.' }
        }
        Write-Output ($component.name + ' frozen startup: OK')
    }
    $archive = Join-Path $outputRoot "BC2Launcher-app-$Version.zip"
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive }
    & $launcherPython tools/package_launcher.py package --folder $clientPath --version $Version --private $SigningKey --output $archive
    if ($LASTEXITCODE -ne 0) { throw 'App package signing failed.' }
    if ($InstallPreview) {
        Get-FileHash -LiteralPath $archive -Algorithm SHA256 | Format-List Path,Hash
        return
    }
    $policyPath = Join-Path $outputRoot 'launcher-stable.json'
    $artifactUrl = "https://github.com/RinatBy/bc2-community/releases/download/v$Version-beta/BC2Launcher-app-$Version.zip"
    & $launcherPython tools/package_launcher.py policy --archive $archive --version $Version --url $artifactUrl --revision $PolicyRevision --minimum $MinimumLauncherVersion --private $SigningKey --output $policyPath
    if ($LASTEXITCODE -ne 0) { throw 'Launcher policy signing failed.' }
    $seedRoot = Join-Path $outputRoot 'seed'
    if (Test-Path -LiteralPath $seedRoot) {
        $seedResolved = [IO.Path]::GetFullPath($seedRoot)
        if (-not $seedResolved.StartsWith($outputRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe seed output.' }
        Remove-Item -LiteralPath $seedResolved -Recurse -Force
    }
    New-Item -ItemType Directory -Path (Join-Path $seedRoot 'versions') -Force | Out-Null
    Copy-Item -LiteralPath $bootstrapExe -Destination (Join-Path $seedRoot 'BC2Launcher.exe')
    Copy-Item -LiteralPath $clientPath -Destination (Join-Path $seedRoot "versions\$Version") -Recurse
    Copy-Item -LiteralPath $policyPath -Destination (Join-Path $seedRoot 'seed-policy.json')
    [IO.File]::WriteAllText((Join-Path $seedRoot 'installation.json'),'{"schema":1,"product":"BC2Launcher"}')
    $portableArchive = Join-Path $outputRoot "BC2Launcher-$Version-portable.zip"
    if (Test-Path -LiteralPath $portableArchive) { Remove-Item -LiteralPath $portableArchive }
    & $launcherPython tools/package_portable.py --seed $seedRoot --version $Version --output $portableArchive
    if ($LASTEXITCODE -ne 0) { throw 'Portable package failed.' }
    & $PSScriptRoot/build_installer.ps1 -SeedRoot $seedRoot -Version $Version -OutputRoot $outputRoot -InnoCompiler $InnoCompiler
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
    Get-FileHash -LiteralPath (Join-Path $outputRoot 'BC2Launcher-Setup.exe'),$archive,$portableArchive -Algorithm SHA256 | Format-List Path,Hash
} finally {
    Remove-Item Env:BC2_BUILD_VERSION_FILE -ErrorAction SilentlyContinue
    Remove-Item Env:BC2_INSTALL_PREVIEW_FILE -ErrorAction SilentlyContinue
    Pop-Location
}
