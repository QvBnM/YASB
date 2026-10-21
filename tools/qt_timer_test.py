"""
qt_timer_test.py - do real Qt timers work at all (no qasync, no YASB)?

    py -3.14 qt_timer_test.py
"""

import faulthandler
import sys
import threading

faulthandler.dump_traceback_later(12, exit=True)

from PyQt6.QtCore import QCoreApplication, QObject, QThread, QTimer, qVersion  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

print(
    f"Python {sys.version.split()[0]} | Qt {qVersion()} | "
    f"fir Python: {threading.current_thread().name} (id {threading.get_ident()})"
)
app = QApplication(sys.argv)
main_qt = app.thread()
cur = QThread.currentThread()
print(f"1. firul curent e firul principal Qt: {'DA' if cur is main_qt or cur == main_qt else 'NU <- problema'}")
print(f"2. dispatcher de evenimente pe firul principal: {main_qt.eventDispatcher()}")
print(f"   dispatcher al aplicatiei: {QCoreApplication.eventDispatcher()}")


class Probe(QObject):
    def timerEvent(self, e):  # noqa: N802
        print("4. QObject.startTimer: OK")
        self.killTimer(e.timerId())


probe = Probe()
print(f"3. obiect nou apartine firului principal: {'DA' if probe.thread() == main_qt else 'NU'}")
tid = probe.startTimer(100)
print(f"   startTimer a intors id {tid} ({'OK' if tid else 'ESUAT'})")

t = QTimer()
t.setInterval(300)
t.setSingleShot(True)
t.timeout.connect(lambda: (print("5. QTimer real (300 ms): OK"), QTimer.singleShot(200, app.quit)))
t.start()
print(f"   QTimer activ: {t.isActive()}")

app.exec()
print("REZULTAT: timerele Qt merg.")
