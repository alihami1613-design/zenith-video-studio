$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Launcher = Get-Command py -ErrorAction SilentlyContinue
if ($Launcher) {
    & $Launcher.Source -3.11 -m venv (Join-Path $Root ".venv-build")
    if ($LASTEXITCODE -ne 0) { throw "ساخت محیط Python 3.11 ناموفق بود." }
} else {
    $Python = Get-Command python -ErrorAction Stop
    $Version = & $Python.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0 -or $Version.Trim() -ne "3.11") {
        throw "Python 3.11 لازم است. Python پیدا‌شده: $Version"
    }
    & $Python.Source -m venv (Join-Path $Root ".venv-build")
    if ($LASTEXITCODE -ne 0) { throw "ساخت محیط Python 3.11 ناموفق بود." }
}

$VenvPython = Join-Path $Root ".venv-build\Scripts\python.exe"
if (-not (Test-Path $VenvPython -PathType Leaf)) {
    throw "Python محیط ساخت پیدا نشد."
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "به‌روزرسانی pip ناموفق بود." }

& $VenvPython -m pip install -r (Join-Path $Root "desktop_app\requirements.txt") pyinstaller
if ($LASTEXITCODE -ne 0) { throw "نصب وابستگی‌های ساخت ناموفق بود." }

& $VenvPython -m PyInstaller --noconfirm --clean (Join-Path $Root "ZENITH_Desktop.spec")
if ($LASTEXITCODE -ne 0) { throw "ساخت برنامه ناموفق بود." }

$Executable = Join-Path $Root "dist\ZENITH Desktop\ZENITH Desktop.exe"
if (-not (Test-Path $Executable -PathType Leaf)) {
    throw "فایل اجرایی نهایی ساخته نشد."
}

Write-Host "Build completed: $Executable"
