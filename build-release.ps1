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
$packageName = 'ThreadFor3DPrinterTest'
$stageRoot = Join-Path $distRoot $packageName
$zipPath = Join-Path $distRoot "$packageName-v$version.zip"
$releaseFiles = @(
    @{ Source = 'ThreadFor3DPrinter.py'; Destination = "$packageName.py" },
    @{ Source = 'ThreadFor3DPrinter.manifest'; Destination = "$packageName.manifest" },
    @{ Source = 'icon-v4.png'; Destination = 'icon-v4.png' },
    @{ Source = 'LICENSE'; Destination = 'LICENSE' },
    @{ Source = 'README.md'; Destination = 'README.md' },
    @{ Source = 'README.zh-CN.md'; Destination = 'README.zh-CN.md' },
    @{ Source = '如何设计67mm滤镜螺纹.md'; Destination = '如何设计67mm滤镜螺纹.md' }
)

New-Item -ItemType Directory -Force -Path $distRoot | Out-Null
if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

foreach ($releaseFile in $releaseFiles) {
    $sourcePath = Join-Path $repoRoot $releaseFile.Source
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Missing release file: $sourcePath"
    }
    $destinationPath = Join-Path $stageRoot $releaseFile.Destination
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
}

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -LiteralPath $stageRoot -DestinationPath $zipPath `
    -CompressionLevel Optimal
Remove-Item -LiteralPath $stageRoot -Recurse -Force

# Fusion discovers a Python add-in only when the extracted folder, main Python
# file, and manifest share the same base name. Validate the final archive so a
# renamed staging folder can never produce an uninstallable release again.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $entryNames = @($zip.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
    $topLevelNames = @($entryNames | ForEach-Object { ($_ -split '/')[0] } |
        Sort-Object -Unique)
    if ($topLevelNames.Count -ne 1 -or $topLevelNames[0] -ne $packageName) {
        throw "Invalid package root. Expected only '$packageName/'."
    }
    foreach ($requiredEntry in @(
        "$packageName/$packageName.py",
        "$packageName/$packageName.manifest"
    )) {
        if ($entryNames -notcontains $requiredEntry) {
            throw "Missing Fusion entry point: $requiredEntry"
        }
    }
}
finally {
    $zip.Dispose()
}

$archive = Get-Item -LiteralPath $zipPath
Write-Output "Created $($archive.FullName)"
Write-Output "Version: $version"
Write-Output "Size: $($archive.Length) bytes"
