from pathlib import Path
root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / 'launcher' / 'run_launcher.py')],
    pathex=[str(root / 'launcher')],
    binaries=[], datas=[(str(root / 'launcher' / 'assets'), 'assets')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True,
          name='BC2Launcher', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False, disable_windowed_traceback=False)
collect = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='BC2Launcher')
