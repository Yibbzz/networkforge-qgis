"""The "NetworkForge" group in the Processing Toolbox."""

from pathlib import Path

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.build_network import BuildNetworkAlgorithm
from .algorithms.check_layer import CheckLayerAlgorithm
from .algorithms.engine_info import EngineInfoAlgorithm
from .algorithms.standalone_network import StandaloneNetworkAlgorithm

ICON_PATH = Path(__file__).parent / "icons" / "networkforge.svg"


class NetworkForgeProvider(QgsProcessingProvider):
    def id(self):
        return "networkforge"

    def name(self):
        return "NetworkForge"

    def longName(self):
        return "NetworkForge (street networks from OpenStreetMap and your own lines)"

    def icon(self):
        return QIcon(str(ICON_PATH))

    def loadAlgorithms(self):
        self.addAlgorithm(CheckLayerAlgorithm())
        self.addAlgorithm(BuildNetworkAlgorithm())
        self.addAlgorithm(StandaloneNetworkAlgorithm())
        self.addAlgorithm(EngineInfoAlgorithm())
