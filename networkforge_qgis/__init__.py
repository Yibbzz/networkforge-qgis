"""NetworkForge QGIS plugin: a front end for the NetworkForge engine."""


def classFactory(iface):
    """Entry point QGIS calls to load the plugin."""
    from .plugin import NetworkForgePlugin

    return NetworkForgePlugin(iface)
