from pathlib import Path
import os
import sys

# The parent environment can contain unrelated Poppler/Conda DLLs with the
# same names as Windows components (notably ICU). Never search that PATH.
if sys.platform == 'win32':
    windows_root = Path(os.environ['SystemRoot'])
    dll_search_dirs = [Path(sys.executable).parent, Path(sys.base_prefix),
                       Path(sys.base_prefix) / 'DLLs',
                       windows_root / 'System32', windows_root]
    os.environ['PATH'] = os.pathsep.join(str(p) for p in dll_search_dirs)

root = Path(SPECPATH).parent
version_file = Path(os.environ['BC2_BUILD_VERSION_FILE'])
analysis = Analysis(
    [str(root / 'launcher' / 'run_launcher.py')],
    pathex=[str(root / 'launcher')],
    binaries=[], datas=[(str(root / 'launcher' / 'assets'), 'assets'), (str(version_file), 'assets')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True,
          name='BC2Client', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False, disable_windowed_traceback=False,
          icon=str(root / 'launcher' / 'assets' / 'brand.ico'))
collect = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='BC2Client')
