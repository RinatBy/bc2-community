import json
import sys
from pathlib import Path


def configure_smoke_logging():
    """A deliberately broken diagnostic plugin must fail without desktop popups."""
    import os
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType

    def diagnostic_message(kind, context, message):
        if sys.stderr:
            print(message, file=sys.stderr, flush=True)
        if (context.category == 'qt.qpa.plugin'
                and kind in (QtMsgType.QtWarningMsg, QtMsgType.QtInfoMsg)
                and ('Could not find the Qt platform plugin' in message
                     or 'Could not load the Qt platform plugin' in message)):
            os._exit(78)

    qInstallMessageHandler(diagnostic_message)


def self_test(assets):
    from bc2launcher import VERSION

    result = dict(version=VERSION, ok=False)
    try:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.kernel32.SetErrorMode(0x8003)
        from PySide6.QtCore import qVersion
        from PySide6 import QtGui, QtWidgets
        from bc2launcher import ui
        ui.configure_process_identity()
        result.update(qt_version=qVersion(), qt_imports_ok=True)

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes((assets / 'public-key.bin').read_bytes())
        for name in ['valparaiso-original.png', 'Oswald.ttf', 'Manrope.ttf', 'brand.ico', 'FAQ_RU.md']:
            if not (assets / name).is_file():
                raise RuntimeError('Missing resource: ' + name)
        result.update(resources_ok=True, ok=True)
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error=str(exc))
    return result


def main():
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x8003)
    assets=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'assets'
    if '--self-test' in sys.argv:
        result = self_test(assets)
        if '--report' in sys.argv:Path(sys.argv[sys.argv.index('--report')+1]).write_text(json.dumps(result),encoding='utf-8')
        if sys.stdout: print(json.dumps(result))
        return 0 if result['ok'] else 1
    from bc2launcher.ui import run
    if not getattr(sys,'frozen',False):return run(assets)
    from bc2launcher import VERSION
    from bc2launcher.selfupdate.paths import inside,validate_version
    from bc2launcher.selfupdate.store import UpdateStore
    from bc2launcher.selfupdate.process import acknowledge_ready
    from bc2launcher.selfupdate.service import SelfUpdateService
    from bc2launcher.settings import Settings
    from bc2launcher.manifest import UpdateError
    import os,subprocess
    executable=Path(sys.executable).absolute()
    version=validate_version(executable.parent.name)
    if version!=VERSION or executable.parent.parent.name!='versions':raise UpdateError('Invalid installed application path.')
    root=executable.parent.parent.parent
    smoke='--smoke-startup' in sys.argv
    if smoke:configure_smoke_logging()
    if '--self-test-restart' in sys.argv:
        result=dict(ok=False,version=VERSION)
        try:
            if not smoke:raise UpdateError('Restart probe requires smoke startup mode.')
            with UpdateStore(root).locked('client.lock'):
                updates=SelfUpdateService(root,(assets/'public-key.bin').read_bytes())
                status=updates.prepare(manual=True)
                if not status.restart_ready:raise UpdateError(status.error or 'No prepared update.')
                status=updates.request_restart()
                result.update(ok=status.state=='RESTARTING',pid=os.getpid())
        except Exception as exc:result['error']=str(exc)
        if '--report' in sys.argv:Path(sys.argv[sys.argv.index('--report')+1]).write_text(json.dumps(result),encoding='utf-8')
        return 0 if result['ok'] else 1
    if '--ready-handle' not in sys.argv:
        subprocess.Popen([str(inside(root,'BC2Launcher.exe'))],cwd=root,shell=False)
        return 0
    handle=int(sys.argv[sys.argv.index('--ready-handle')+1]);nonce=sys.argv[sys.argv.index('--ready-token')+1]
    if smoke:os.environ['QT_QPA_PLATFORM']='offscreen'
    def ready():
        try:acknowledge_ready(handle,nonce,VERSION)
        except Exception:
            from PySide6.QtWidgets import QApplication
            QApplication.instance().exit(1)
    settings=Settings(inside(root,'cache','smoke-settings.json')) if smoke else None
    with UpdateStore(root).locked('client.lock'):
        return run(assets,settings=settings,app_updates=None if smoke else SelfUpdateService(root,(assets/'public-key.bin').read_bytes()),
                   ready=ready,smoke=smoke)


if __name__=='__main__': raise SystemExit(main())
