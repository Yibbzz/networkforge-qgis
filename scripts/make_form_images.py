"""Saves pictures of the tools' forms, for the README.

Runs inside QGIS desktop, which can start without a screen:

    DISPLAY=:99 QT_QPA_PLATFORM=offscreen qgis --nologo --noversioncheck \
        --code scripts/make_form_images.py

The plugin must be enabled in that QGIS (see "Development install" in
the README). QGIS closes by itself when the pictures are saved.
"""

from pathlib import Path

import processing
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QApplication
from qgis.utils import iface

IMAGES = Path(QgsApplication.instance().property("nf_images")
              or Path.cwd() / "docs" / "images")
FORMS = (  # tool, picture, height of the window
    ("build_network", "build-form", 800),
    ("standalone_network", "standalone-form", 720),
)


def save():
    log = []
    try:
        registry = QgsApplication.processingRegistry()
        if registry.providerById("networkforge") is None:
            from networkforge_qgis.provider import NetworkForgeProvider
            save.provider = NetworkForgeProvider()
            registry.addProvider(save.provider)
        for tool, name, height in FORMS:
            dialog = processing.createAlgorithmDialog(f"networkforge:{tool}", {})
            dialog.resize(1000, height)
            dialog.show()
            for _ in range(30):
                QApplication.processEvents()
            dialog.grab().save(str(IMAGES / f"{name}.png"))
            dialog.close()
            log.append(f"wrote {IMAGES / (name + '.png')}")
    except Exception as error:  # noqa: BLE001 - reported in the log file
        import traceback
        log.append(traceback.format_exc())
    (IMAGES / "forms.log").write_text("\n".join(log))
    iface.actionExit().trigger()


QTimer.singleShot(4000, save)
