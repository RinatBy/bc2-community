import sys
from pathlib import Path

VERSION = "0.2.6"
if getattr(sys, 'frozen', False):
    VERSION = (Path(sys._MEIPASS) / 'assets' / 'build-version.txt').read_text(encoding='ascii').strip()
