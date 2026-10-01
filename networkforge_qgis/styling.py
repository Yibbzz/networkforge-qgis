"""How the before and after layers look when they are loaded.

Applied on the main thread once a tool has finished, through QGIS's
"post-processor" hook for layers a Processing tool loads.
"""

from qgis.core import (
    QgsLineSymbol,
    QgsProcessingLayerPostProcessorInterface,
    QgsRuleBasedRenderer,
    QgsSingleSymbolRenderer,
)

OSM_CREDIT = "© OpenStreetMap contributors (ODbL)"

_NETWORK_LINE = {"color": "#7f8c8d", "width": "0.3"}
_CUSTOM_LINE = {"color": "#e6194b", "width": "1.2", "capstyle": "round"}


def style_before(layer):
    layer.setRenderer(
        QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(_NETWORK_LINE))
    )


def style_after(layer):
    """The whole network in grey, with the custom edges bold on top."""
    custom = QgsLineSymbol.createSimple(_CUSTOM_LINE)
    custom.symbolLayer(0).setRenderingPass(1)  # drawn after the grey lines
    root = QgsRuleBasedRenderer.Rule(None)
    root.appendChild(
        QgsRuleBasedRenderer.Rule(custom, 0, 0, "\"custom\" = 'yes'", "Custom")
    )
    root.appendChild(
        QgsRuleBasedRenderer.Rule(
            QgsLineSymbol.createSimple(_NETWORK_LINE), 0, 0, "ELSE", "OpenStreetMap"
        )
    )
    layer.setRenderer(QgsRuleBasedRenderer(root))


class LayerStyler(QgsProcessingLayerPostProcessorInterface):
    """Styles a loaded layer and credits OpenStreetMap in its metadata."""

    # QGIS doesn't keep the Python object alive by itself, so the latest
    # styler for each role is kept here until it has been used.
    _alive = {}

    def __init__(self, style):
        super().__init__()
        self._style = style

    @classmethod
    def create(cls, role, style):
        cls._alive[role] = cls(style)
        return cls._alive[role]

    def postProcessLayer(self, layer, context, feedback):
        if not layer.isValid():
            return
        self._style(layer)
        metadata = layer.metadata()
        metadata.setRights([OSM_CREDIT])
        layer.setMetadata(metadata)
        layer.triggerRepaint()
