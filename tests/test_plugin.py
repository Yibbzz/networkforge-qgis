"""Loading the plugin the way QGIS does: classFactory, initGui, unload."""

from qgis.core import QgsApplication

import networkforge_qgis

TOOLS = {"add_traffic", "build_network", "check_layer", "engine_info", "standalone_network"}


def test_plugin_adds_its_tools_and_takes_them_away_again(qgis_processing, qgis_iface):
    registry = QgsApplication.processingRegistry()
    assert registry.providerById("networkforge") is None

    plugin = networkforge_qgis.classFactory(qgis_iface)
    plugin.initGui()
    try:
        provider = registry.providerById("networkforge")
        assert provider is not None
        assert {algorithm.name() for algorithm in provider.algorithms()} == TOOLS
        # Every form can be built: none needs the engine to be installed.
        for tool in TOOLS:
            algorithm = registry.createAlgorithmById(f"networkforge:{tool}")
            assert algorithm is not None and algorithm.parameterDefinitions()
    finally:
        plugin.unload()

    assert registry.providerById("networkforge") is None
    plugin.unload()  # a second unload does no harm
