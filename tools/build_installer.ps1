param([Parameter(Mandatory)][string]$SeedRoot,[Parameter(Mandatory)][string]$Version,[Parameter(Mandatory)][string]$OutputRoot,[string]$InnoCompiler)
$ErrorActionPreference='Stop'
$communityRoot=Split-Path -Parent $PSScriptRoot
if (-not $InnoCompiler) {
    $candidates=@((Join-Path (Split-Path -Parent $communityRoot) 'tools\inno-setup\compiler\ISCC.exe'),'C:\Program Files (x86)\Inno Setup 6\ISCC.exe','C:\Program Files\Inno Setup 6\ISCC.exe')
    $InnoCompiler=$candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $InnoCompiler) { throw 'Inno Setup ISCC.exe not found; pass -InnoCompiler.' }
$inventory=Join-Path $SeedRoot "versions\$Version\.launcher-package.json"
$inventoryHash=(Get-FileHash -LiteralPath $inventory -Algorithm SHA256).Hash.ToLowerInvariant()
& $InnoCompiler "/DAppVersion=$Version" "/DSeedRoot=$SeedRoot" "/DSeedInventory=$inventoryHash" "/O$OutputRoot" (Join-Path $communityRoot 'installer\BC2Launcher.iss')
if ($LASTEXITCODE -ne 0) { throw 'ISCC compilation failed.' }
