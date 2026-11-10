# Install the local web version without replacing an existing installation.
$ErrorActionPreference = 'Stop'
$repoUrl = 'https://github.com/xiaoyoumi9924/handwritten-notes.git'
$installDir = if ($env:MIAOBI_INSTALL_DIR) { $env:MIAOBI_INSTALL_DIR } else { Join-Path $HOME '.miaobi\app' }
$binDir = if ($env:MIAOBI_BIN_DIR) { $env:MIAOBI_BIN_DIR } else { Join-Path $HOME '.miaobi\bin' }
$launcher = Join-Path $binDir 'miaobi.cmd'
foreach ($name in @('git', 'py')) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "Missing $name. Install it and try again." }
}
& py -3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or later is required.' }
if ((Test-Path $launcher) -and -not (Select-String -Quiet -LiteralPath $launcher -Pattern '^REM Managed by Miaobi quick-start$')) {
    throw "The command already exists at $launcher and will not be overwritten."
}
if ((Test-Path $installDir) -and -not (Test-Path (Join-Path $installDir 'requirements.txt'))) {
    throw "Installation directory already exists and is not a Miaobi installation: $installDir"
}
if (-not (Test-Path $installDir)) {
    $parent = Split-Path -Parent $installDir
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $stage = Join-Path $parent ('.miaobi-install-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        Write-Host 'Downloading Miaobi...'
        $source = Join-Path $stage 'source'
        & git clone --depth 1 $repoUrl $source
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $source 'requirements.txt'))) { throw 'Could not download the source repository.' }
        Move-Item -LiteralPath $source -Destination $installDir
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}
$python = Join-Path $installDir '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    & py -3 -m venv (Join-Path $installDir '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
}
Write-Host 'Installing dependencies...'
& $python -m pip install -r (Join-Path $installDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the error and retry.' }
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$cmd = @'
@echo off
REM Managed by Miaobi quick-start
setlocal
if not defined MIAOBI_INSTALL_DIR set "MIAOBI_INSTALL_DIR=%USERPROFILE%\.miaobi\app"
cd /d "%MIAOBI_INSTALL_DIR%"
set "PYTHONPATH=%MIAOBI_INSTALL_DIR%\src;%PYTHONPATH%"
"%MIAOBI_INSTALL_DIR%\.venv\Scripts\python.exe" -m markdown_to_handwrite.quickstart %*
'@
Set-Content -LiteralPath $launcher -Value $cmd -Encoding ASCII
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not (($userPath -split ';') | Where-Object { $_.TrimEnd('\') -ieq $binDir.TrimEnd('\') })) {
    $newPath = if ($userPath) { "$userPath;$binDir" } else { $binDir }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
}
if (-not (($env:Path -split ';') | Where-Object { $_.TrimEnd('\') -ieq $binDir.TrimEnd('\') })) { $env:Path += ";$binDir" }
Write-Host 'Installation complete. Starting Miaobi. In a new terminal, run miaobi to start again. Press Ctrl+C to stop.'
& $launcher
