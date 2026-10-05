"""How the network layers look when they are loaded.

Applied on the main thread once a tool has finished, through QGIS's
"post-processor" hook for layers a Processing tool loads.
"""

from qgis.core import (
    QgsLineSymbol,
    QgsProcessingLayerPostProcessorInterface,
    QgsRuleBasedRenderer,
)

OSM_CREDIT = "© OpenStreetMap contributors (ODbL)"

# The OpenStreetMap network is drawn in quiet colours, grouped by the
# kind of street, so the custom lines stand out. Each entry: label,
# highway values, line. Anything else falls under "Other".
_GROUPS = (
    ("Main roads",
     ("motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"),
     {"color": "#4a5560", "width": "0.9"}),
    ("Secondary roads",
     ("secondary", "secondary_link", "tertiary", "tertiary_link"),
     {"color": "#75828c", "width": "0.6"}),
    ("Streets",
     ("residential", "unclassified", "living_street", "service", "road"),
     {"color": "#a3adb5", "width": "0.35"}),
    ("Cycleways",
     ("cycleway",),
     {"color": "#2c7fb8", "width": "0.45"}),
    ("Paths",
     ("footway", "path", "pedestrian", "steps", "bridleway", "track", "corridor"),
     {"color": "#4b9b55", "width": "0.3", "line_style": "dot"}),
)
_OTHER_LINE = {"color": "#c3cace", "width": "0.25"}
_CUSTOM_LINE = {"color": "#e6007e", "width": "1.4", "capstyle": "round"}
_CHANGED_LINE = {"color": "#f28e2b", "width": "1.4", "capstyle": "round"}


def _network_rules(root):
    for label, highways, line in _GROUPS:
        values = ", ".join(f"'{value}'" for value in highways)
        root.appendChild(QgsRuleBasedRenderer.Rule(
            QgsLineSymbol.createSimple(line), 0, 0, f'"highway" IN ({values})', label
        ))
    root.appendChild(QgsRuleBasedRenderer.Rule(
        QgsLineSymbol.createSimple(_OTHER_LINE), 0, 0, "ELSE", "Other"
    ))


def style_before(layer):
    """The network coloured by kind of street.

    Also how a standalone network is drawn: all of its lines are the
    user's own, so there is nothing to make stand out.
    """
    root = QgsRuleBasedRenderer.Rule(None)
    _network_rules(root)
    layer.setRenderer(QgsRuleBasedRenderer(root))


def style_after(layer):
    """As the before network, with the custom and changed edges bold on top."""
    root = QgsRuleBasedRenderer.Rule(None)
    # The engine leaves a column out when no edge has a value for it
    # (a build of changes only has no custom edges, for example).
    for field, line, label in (("custom", _CUSTOM_LINE, "Custom"),
                               ("modified", _CHANGED_LINE, "Changed")):
        if layer.fields().indexOf(field) < 0:
            continue
        symbol = QgsLineSymbol.createSimple(line)
        symbol.symbolLayer(0).setRenderingPass(1)  # drawn after everything else
        root.appendChild(
            QgsRuleBasedRenderer.Rule(symbol, 0, 0, f"\"{field}\" = 'yes'", label)
        )
    _network_rules(root)
    layer.setRenderer(QgsRuleBasedRenderer(root))


class LayerStyler(QgsProcessingLayerPostProcessorInterface):
    """Styles a loaded layer and, given a credit, puts it in its metadata."""

    # QGIS doesn't keep the Python object alive by itself, so the latest
    # styler for each role is kept here until it has been used.
    _alive = {}

    def __init__(self, style, credit=OSM_CREDIT):
        super().__init__()
        self._style = style
        self._credit = credit

    @classmethod
    def create(cls, role, style, credit=OSM_CREDIT):
        cls._alive[role] = cls(style, credit)
        return cls._alive[role]

    def postProcessLayer(self, layer, context, feedback):
        if not layer.isValid():
            return
        self._style(layer)
        if self._credit:
            metadata = layer.metadata()
            metadata.setRights([self._credit])
            layer.setMetadata(metadata)
        layer.triggerRepaint()
