from pathlib import Path
import os
import sys

root = Path(SPECPATH).parent
if sys.platform == 'win32':
    windows_root = Path(os.environ['SystemRoot'])
    os.environ['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent, Path(sys.base_prefix),
        Path(sys.base_prefix)/'DLLs', windows_root/'System32', windows_root]))
assets = root/'launcher'/'assets'
analysis = Analysis([str(root/'launcher'/'run_bootstrap.py')], pathex=[str(root/'launcher')],
    binaries=[], datas=[(str(assets/'public-key.bin'),'assets'),(str(assets/'brand.ico'),'assets'),
                        (os.environ['BC2_BUILD_VERSION_FILE'],'assets')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6','tkinter'], noarchive=False)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name='BC2Launcher', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    icon=str(assets/'brand.ico'))
