$ErrorActionPreference = 'Stop'

$repoRoot = $PSScriptRoot
$manifestPath = Join-Path $repoRoot 'ThreadFor3DPrinter.manifest'
$manifestText = Get-Content -Raw -Encoding utf8 $manifestPath
$versionMatch = [regex]::Match(
    $manifestText, '"version"\s*:\s*"(?<version>[^"]+)"')
if (-not $versionMatch.Success) {
    throw 'Manifest version is missing.'
}
$version = $versionMatch.Groups['version'].Value

$distRoot = Join-Path $repoRoot 'dist'
$stageRoot = Join-Path $distRoot 'ThreadFor3DPrinter-Test'
$zipPath = Join-Path $distRoot "ThreadFor3DPrinter-Test-v$version.zip"
$releaseFiles = @(
    'ThreadFor3DPrinter.py',
    'ThreadFor3DPrinter.manifest',
    'icon-v4.png',
    'LICENSE',
    'README.md',
    'README.zh-CN.md',
    '如何设计67mm滤镜螺纹.md'
)

New-Item -ItemType Directory -Force -Path $distRoot | Out-Null
if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

foreach ($releaseFile in $releaseFiles) {
    $sourcePath = Join-Path $repoRoot $releaseFile
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Missing release file: $sourcePath"
    }
    Copy-Item -LiteralPath $sourcePath -Destination $stageRoot -Force
}

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -LiteralPath $stageRoot -DestinationPath $zipPath `
    -CompressionLevel Optimal
Remove-Item -LiteralPath $stageRoot -Recurse -Force

$archive = Get-Item -LiteralPath $zipPath
Write-Output "Created $($archive.FullName)"
Write-Output "Version: $version"
Write-Output "Size: $($archive.Length) bytes"
