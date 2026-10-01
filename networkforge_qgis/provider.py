"""The "NetworkForge" group in the Processing Toolbox."""

from pathlib import Path

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.engine_info import EngineInfoAlgorithm

ICON_PATH = Path(__file__).parent / "icons" / "networkforge.svg"


class NetworkForgeProvider(QgsProcessingProvider):
    def id(self):
        return "networkforge"

    def name(self):
        return "NetworkForge"

    def longName(self):
        return "NetworkForge (scenario networks from OpenStreetMap)"

    def icon(self):
        return QIcon(str(ICON_PATH))

    def loadAlgorithms(self):
        self.addAlgorithm(EngineInfoAlgorithm())
