"""Registers the NetworkForge Processing provider with QGIS."""

from qgis.core import QgsApplication

from .provider import NetworkForgeProvider


class NetworkForgePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initProcessing(self):
        """Also called on its own by qgis_process, which has no GUI."""
        self.provider = NetworkForgeProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
