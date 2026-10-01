"""The "NetworkForge" group in the Processing Toolbox."""

from pathlib import Path

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.build_network import BuildNetworkAlgorithm
from .algorithms.check_layer import CheckLayerAlgorithm
from .algorithms.engine_info import EngineInfoAlgorithm
from .algorithms.new_custom_layer import NewCustomLayerAlgorithm

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
        self.addAlgorithm(NewCustomLayerAlgorithm())
        self.addAlgorithm(CheckLayerAlgorithm())
        self.addAlgorithm(BuildNetworkAlgorithm())
        self.addAlgorithm(EngineInfoAlgorithm())
