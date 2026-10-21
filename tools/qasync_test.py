"""
qasync_test.py - does the Python <-> Qt event loop (qasync) work on this PC?

    py -3.14 qasync_test.py

Each step prints OK or the error. Closes itself after a few seconds.
"""

import faulthandler
import sys
import threading

faulthandler.dump_traceback_later(15, exit=True)  # never hang forever
print(f"Python {sys.version.split()[0]} | elevat (Administrator): ", end="")
try:
    import ctypes

    print("DA" if ctypes.windll.shell32.IsUserAnAdmin() else "nu")
except Exception:
    print("?")

import asyncio  # noqa: E402

import qasync  # noqa: E402
from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication(sys.argv)
print("1. QApplication creat: OK")

# Qt alone: does a plain Qt timer fire?
fired = []
QTimer.singleShot(0, lambda: fired.append(True))
app.processEvents()
print(f"2. timer Qt simplu: {'OK' if fired else 'NU S-A DECLANSAT'}")



async def main(tag):
    print(f"   [{tag}] 4. corutina principala ruleaza: OK  <- asta lipseste la YASB pe laptop")
    await asyncio.sleep(0.3)
    print(f"   [{tag}] 5. asyncio.sleep in Qt: OK")
    label = QLabel("qasync merge")
    label.show()
    await asyncio.sleep(0.5)
    print(f"   [{tag}] 6. fereastra Qt afisata: OK")
    label.close()


def run(tag, cls):
    print(f"\n== {tag} ==")
    loop = cls(app)
    asyncio.set_event_loop(loop)
    print(f"   [{tag}] 3. bucla creata: OK (fir: {threading.current_thread().name})")
    try:
        loop.run_until_complete(asyncio.wait_for(main(tag), 8))
        print(f"   [{tag}] REZULTAT: MERGE")
    except Exception as e:
        print(f"   [{tag}] REZULTAT: esuat: {type(e).__name__}: {e}")
    finally:
        asyncio.set_event_loop(None)


# the simple one first: if the default (IOCP) one hangs, the watchdog stops the script after it
run("bucla simpla (selector)", qasync.QSelectorEventLoop)
faulthandler.dump_traceback_later(15, exit=True)
run("bucla implicita (IOCP, cea folosita de YASB)", qasync.QEventLoop)
print("\nGata.")
