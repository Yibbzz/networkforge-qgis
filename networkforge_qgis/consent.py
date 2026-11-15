"""Asks before anything is downloaded.

The engine and what it needs are downloaded the first time a tool runs.
Before that happens the user is shown exactly what will be installed,
from where and into which folder, and nothing is fetched unless they
agree. Without QGIS's windows (qgis_process, tests) there is nobody to
ask: the person who typed the command asked for the tool to run, and the
same list goes to the log. Only QGIS desktop (`qgis.utils.iface`) asks.
"""

from qgis.core import QgsApplication, QgsProcessingException
from qgis.PyQt.QtCore import QThread
from qgis.PyQt.QtWidgets import QApplication, QMessageBox

from . import engine

DECLINED = (
    "Nothing was installed. NetworkForge's tools need its engine: run the "
    "tool again and choose Install when you are ready."
)


def _can_ask():
    """Whether a question can be put to the user: QGIS desktop, with its
    main window, on the thread that may show a window (a tool inside a
    model is prepared on another).

    qgis_process has no main window (`iface` is None). Asking there opened
    a box nobody could see or answer, on Windows, and the tool waited for
    ever: what kind of display Qt has is no guide, only QGIS desktop is.
    """
    from qgis import utils

    if utils.iface is None or utils.iface.mainWindow() is None:
        return False
    app = QgsApplication.instance()
    if not isinstance(app, QApplication) or app.platformName() == "offscreen":
        return False
    return QThread.currentThread() == app.thread()


def ask(summary, details):
    """Show what will be installed; True if the user chooses Install."""
    from qgis import utils

    box = QMessageBox(utils.iface.mainWindow())
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("NetworkForge: install the engine?")
    box.setText("NetworkForge needs to download its engine before this tool can run.")
    box.setInformativeText(summary)
    box.setDetailedText("Exactly these versions:\n\n" + details)
    install = box.addButton("Install", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(install)
    box.exec()
    return box.clickedButton() is install


def approve_install(feedback=None, traffic=False, reinstall=False):
    """Stop the tool unless the user agrees to what it would download.

    Does nothing when everything is installed already. `reinstall`: the
    tool is about to replace the engine whatever is there.
    """
    pending = engine.pending_install(traffic=traffic, reinstall=reinstall)
    if pending is None:
        return
    summary, details = pending
    if feedback is not None:
        feedback.pushInfo(summary)
    if _can_ask() and not ask(summary, details):
        raise QgsProcessingException(DECLINED)
