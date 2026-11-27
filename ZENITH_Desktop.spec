# PyInstaller onedir build for ZENITH Desktop.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

project_root = Path(SPECPATH)
desktop_root = project_root / "desktop_app"

ffmpeg_datas, ffmpeg_binaries, ffmpeg_hidden = collect_all("imageio_ffmpeg")
ai_hidden = collect_submodules("ai_editor")

a = Analysis(
    [str(desktop_root / "main.py")],
    pathex=[str(desktop_root)],
    binaries=ffmpeg_binaries,
    datas=ffmpeg_datas,
    hiddenimports=ffmpeg_hidden + ai_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ZENITH Desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ZENITH Desktop",
)
