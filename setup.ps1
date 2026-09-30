param(
    [switch]$Dev,
    [string]$PythonExecutable = ''
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$uvVersion = '0.12.20'
$uvSha256 = '95f9bc30fbb3574d276e28ac4a6de932d25153645853d13da8c21eec3bc88d06'
$toolDir = Join-Path $root ".tools\uv\$uvVersion"
$uv = Join-Path $toolDir 'uv.exe'
$pythonVersion = (Get-Content -LiteralPath (Join-Path $root '.python-version') -Raw).Trim()
$savedEnvironment = @{}
foreach ($key in @('UV_CACHE_DIR','UV_PYTHON_INSTALL_DIR','UV_PROJECT_ENVIRONMENT')) {
    $savedEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
        throw 'This setup supports Windows x64. Use a Windows x64 computer.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $root 'uv.lock'))) {
        throw 'uv.lock is missing. Download the complete project before running setup.'
    }
    if (-not (Test-Path -LiteralPath $uv)) {
        [IO.Directory]::CreateDirectory($toolDir) | Out-Null
        $archive = Join-Path $toolDir 'uv.zip'
        Write-Host "Downloading uv $uvVersion from the official release..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip" -OutFile $archive
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $uvSha256) {
            throw 'uv download checksum mismatch. Setup stopped; download again.'
        }
        Expand-Archive -LiteralPath $archive -DestinationPath $toolDir -Force
        Remove-Item -LiteralPath $archive
    }
    $toolVersion = & $uv --version
    if ($LASTEXITCODE -ne 0 -or $toolVersion -notmatch "^uv $([regex]::Escape($uvVersion))( |$)") {
        throw 'Unexpected uv executable version.'
    }
    $env:UV_CACHE_DIR = Join-Path $root '.cache\uv'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $root '.tools\python'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $root '.venv'
    $selector = $pythonVersion
    if ($PythonExecutable) {
        if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'PythonExecutable was not found.' }
        $detected = & $PythonExecutable -c 'import sys,struct; print(sys.version.split()[0]); print(struct.calcsize(chr(80))*8)'
        if ($LASTEXITCODE -ne 0 -or ($detected -join '/') -ne "$pythonVersion/64") {
            throw "PythonExecutable must be Python $pythonVersion (64 bit)."
        }
        $selector = (Resolve-Path -LiteralPath $PythonExecutable).Path
    }
    Write-Host "Preparing BRL environment (Python $pythonVersion)..."
    $arguments = @('sync','--project',$root,'--locked','--python',$selector)
    if (-not $Dev) { $arguments += '--no-dev' }
    & $uv @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and the error above.' }
    $python = Join-Path $root '.venv\Scripts\python.exe'
    & $python -c 'import sys,gmsh,numpy,pyNastran; print(sys.version); print(gmsh.__version__,numpy.__version__,pyNastran.__version__)'
    if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies could not be loaded.' }
    Write-Host ''
    Write-Host 'Setup complete. Open 01_mesh_generator\run_ui.bat to start.'
} catch {
    Write-Host ("Setup failed: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    foreach ($key in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($key, $savedEnvironment[$key], 'Process')
    }
}
