param([switch]$Dev, [switch]$UpdateLock)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$uvVersion = '0.12.20'
$uvHash = '95f9bc30fbb3574d276e28ac4a6de932d25153645853d13da8c21eec3bc88d06'
$toolDir = Join-Path $projectRoot ".tools\uv\$uvVersion"
$uvExe = Join-Path $toolDir 'uv.exe'
$savedEnvironment = @{}
foreach ($key in @('UV_CACHE_DIR', 'UV_PYTHON_INSTALL_DIR', 'UV_PROJECT_ENVIRONMENT')) {
    $savedEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
        throw 'Windows x64 is required.'
    }
    if (-not (Test-Path -LiteralPath $uvExe)) {
        [IO.Directory]::CreateDirectory($toolDir) | Out-Null
        $downloadPath = Join-Path $toolDir 'uv.zip'
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip" -OutFile $downloadPath
        if ((Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $uvHash) {
            throw 'uv checksum mismatch; installation stopped.'
        }
        Expand-Archive -LiteralPath $downloadPath -DestinationPath $toolDir -Force
        Remove-Item -LiteralPath $downloadPath
    }
    $detected = & $uvExe --version
    if ($LASTEXITCODE -ne 0 -or $detected -notmatch "^uv $([regex]::Escape($uvVersion))( |$)") {
        throw 'Unexpected uv version.'
    }
    $env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.tools\python'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv'
    if ($UpdateLock) {
        & $uvExe lock --project $projectRoot
        if ($LASTEXITCODE -ne 0) { throw 'Lock generation failed.' }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'uv.lock'))) {
        throw 'uv.lock is missing. Maintainers can generate it with -UpdateLock.'
    }
    $syncArgs = @('sync', '--project', $projectRoot, '--locked')
    if (-not $Dev) { $syncArgs += '--no-dev' }
    & $uvExe @syncArgs
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & (Join-Path $projectRoot '.venv\Scripts\python.exe') -c 'import sys,gmsh,numpy,pyNastran; print(sys.version.split()[0], gmsh.__version__, numpy.__version__, pyNastran.__version__)'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency import failed.' }
} finally {
    foreach ($key in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($key, $savedEnvironment[$key], 'Process')
    }
}
