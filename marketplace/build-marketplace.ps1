$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$bundleRoot = Join-Path $PSScriptRoot 'ADSK.ThreadFor3DPrinter.bundle'
$contentsRoot = Join-Path $bundleRoot 'Contents'
$distRoot = Join-Path $repoRoot 'dist'
$version = '1.1.1'
$zipPath = Join-Path $distRoot "ThreadFor3DPrinter-Marketplace-$version.zip"
$releaseStage = Join-Path $distRoot 'ThreadFor3DPrinter'
$releaseZipPath = Join-Path $distRoot "ThreadFor3DPrinter-v$version.zip"

$sourceFiles = @(
    'ThreadFor3DPrinter.py',
    'ThreadFor3DPrinter.manifest',
    'icon-v4.png',
    'LICENSE'
)

New-Item -ItemType Directory -Force -Path $contentsRoot, $distRoot | Out-Null
foreach ($sourceFile in $sourceFiles) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $sourceFile) -Destination $contentsRoot -Force
}

$manifestText = Get-Content -Raw -Encoding utf8 (Join-Path $contentsRoot 'ThreadFor3DPrinter.manifest')
if ($manifestText -notmatch '"autodeskProduct"\s*:\s*"Fusion360"') { throw 'Manifest autodeskProduct must be Fusion360.' }
if ($manifestText -notmatch '"type"\s*:\s*"addin"') { throw 'Manifest type must be addin.' }
if ($manifestText -notmatch ('"version"\s*:\s*"' + [regex]::Escape($version) + '"')) { throw 'Manifest version does not match build version.' }
if ($manifestText -notmatch '"runOnStartup"\s*:\s*true') { throw 'Marketplace add-in must run on startup.' }

[xml]$package = Get-Content -Raw -Encoding utf8 (Join-Path $bundleRoot 'PackageContents.xml')
if ($package.ApplicationPackage.AutodeskProduct -ne 'Fusion360') { throw 'Package AutodeskProduct must be Fusion360.' }
if ($package.ApplicationPackage.AppVersion -ne $version) { throw 'Package version does not match build version.' }

$requiredFiles = @(
    (Join-Path $bundleRoot 'PackageContents.xml'),
    (Join-Path $contentsRoot 'ThreadFor3DPrinter.py'),
    (Join-Path $contentsRoot 'ThreadFor3DPrinter.manifest'),
    (Join-Path $contentsRoot 'icon-v4.png'),
    (Join-Path $contentsRoot 'Help.html'),
    (Join-Path $contentsRoot 'LICENSE')
)
foreach ($requiredFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Missing required package file: $requiredFile"
    }
}

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -LiteralPath $bundleRoot -DestinationPath $zipPath -CompressionLevel Optimal

if (Test-Path -LiteralPath $releaseStage) {
    Remove-Item -LiteralPath $releaseStage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $releaseStage | Out-Null
foreach ($sourceFile in $sourceFiles) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $sourceFile) -Destination $releaseStage -Force
}
Copy-Item -LiteralPath (Join-Path $repoRoot 'README.md') -Destination $releaseStage -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'README.zh-CN.md') -Destination $releaseStage -Force
if (Test-Path -LiteralPath $releaseZipPath) {
    Remove-Item -LiteralPath $releaseZipPath -Force
}
Compress-Archive -LiteralPath $releaseStage -DestinationPath $releaseZipPath -CompressionLevel Optimal
Remove-Item -LiteralPath $releaseStage -Recurse -Force

Write-Output "Created $zipPath"
Write-Output "Created $releaseZipPath"
