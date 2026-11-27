$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Get-Command py -ErrorAction SilentlyContinue
if ($Python) {
    & py -3.11 -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { throw "ساخت محیط Python ناموفق بود." }
    $VenvPython = Join-Path $Root ".venv-build\Scripts\python.exe"
} else {
    $VenvPython = (Get-Command python -ErrorAction Stop).Source
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
