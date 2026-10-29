"""How the network layers look when they are loaded.

Applied on the main thread once a tool has finished, through QGIS's
"post-processor" hook for layers a Processing tool loads.
"""

from qgis.core import (
    QgsLineSymbol,
    QgsMarkerLineSymbolLayer,
    QgsMarkerSymbol,
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


# The nodes a router acts on. Each entry: label, conditions (column,
# values; None for any value but "kerb"), marker. A nodes layer shows
# only these; the rest are plain junctions and line ends. Later entries
# are drawn on top. Access tags on a node without a barrier are left
# out: routers ignore them there.
_NODE_GROUPS = (
    ("Crossings", (("highway", ("crossing",)), ("crossing", None)),
     {"name": "circle", "color": "#ffffff", "outline_color": "#555555", "size": "1.6"}),
    ("Level crossings", (("railway", ("level_crossing", "crossing")),),
     {"name": "cross2", "color": "#333333", "outline_color": "#333333", "size": "2.4"}),
    ("Stop and give way", (("highway", ("stop", "give_way")),),
     {"name": "triangle", "color": "#ffffff", "outline_color": "#c0392b", "size": "2"}),
    ("Traffic signals", (("highway", ("traffic_signals",)),),
     {"name": "circle", "color": "#f5a623", "outline_color": "#333333", "size": "2.2"}),
    ("Kerbs", (("barrier", ("kerb",)),),
     {"name": "line", "color": "#888888", "outline_color": "#888888", "size": "1.6"}),
    ("Barriers", (("barrier", None),),
     {"name": "square", "color": "#d7191c", "outline_color": "#ffffff", "size": "2.4"}),
)


def _node_condition(column, values):
    if values is None:  # any value; kerbs have a group of their own
        return f'("{column}" IS NOT NULL AND "{column}" <> \'kerb\')'
    listed = ", ".join(f"'{value}'" for value in values)
    return f'"{column}" IN ({listed})'


# The nodes the user's points tagged: a ring on top, in the colours of
# custom and changed streets.
_NODE_RINGS = (
    ("Your points (new nodes)", "custom", _CUSTOM_LINE["color"]),
    ("Your points (changed nodes)", "modified", _CHANGED_LINE["color"]),
)


def style_nodes(layer):
    """Only the nodes routers act on: barriers, signals, crossings, ...

    The layer is filtered to them (the attribute table too), and to the
    nodes the user's points tagged, ringed on top. Built from the
    columns the file has: the engine leaves out a column no node has a
    value for.
    """
    root = QgsRuleBasedRenderer.Rule(None)
    shown = []
    for label, column, colour in _NODE_RINGS:
        if layer.fields().indexOf(column) < 0:
            continue
        expression = f'"{column}" = \'yes\''
        shown.append(f"({expression})")
        ring = QgsMarkerSymbol.createSimple({
            "name": "circle", "color": "0,0,0,0", "outline_color": colour,
            "outline_width": "0.6", "size": "4"})
        ring.symbolLayer(0).setRenderingPass(1)
        root.appendChild(QgsRuleBasedRenderer.Rule(ring, 0, 0, expression, label))
    for label, conditions, marker in _NODE_GROUPS:
        conditions = [_node_condition(column, values) for column, values in conditions
                      if layer.fields().indexOf(column) >= 0]
        if not conditions:
            continue
        expression = " OR ".join(conditions)
        shown.append(f"({expression})")
        root.appendChild(QgsRuleBasedRenderer.Rule(
            QgsMarkerSymbol.createSimple(marker), 0, 0, expression, label))
    layer.setSubsetString(" OR ".join(shown) if shown else "1 = 0")
    layer.setRenderer(QgsRuleBasedRenderer(root))


def _restriction_line(colour, width):
    """A line ending in an arrowhead: the way the banned turn goes."""
    symbol = QgsLineSymbol.createSimple({"color": colour, "width": width,
                                         "capstyle": "round", "joinstyle": "round"})
    arrow = QgsMarkerLineSymbolLayer.create({"placement": "lastvertex", "rotate": "1"})
    arrow.setSubSymbol(QgsMarkerSymbol.createSimple({
        "name": "filled_arrowhead", "color": colour, "outline_color": colour,
        "size": str(float(width) * 4)}))
    symbol.appendSymbolLayer(arrow)
    for symbol_layer in symbol.symbolLayers():
        symbol_layer.setRenderingPass(2)  # above streets and nodes
    return symbol


def style_restrictions(layer):
    """Turn restrictions as arrows through their junction; the user's bold."""
    root = QgsRuleBasedRenderer.Rule(None)
    if layer.fields().indexOf("custom") >= 0:
        root.appendChild(QgsRuleBasedRenderer.Rule(
            _restriction_line(_CUSTOM_LINE["color"], "1"), 0, 0, "\"custom\" = 'yes'",
            "Your turn restrictions"))
    root.appendChild(QgsRuleBasedRenderer.Rule(
        _restriction_line("#8b1a1a", "0.6"), 0, 0, "ELSE", "Turn restrictions"))
    layer.setRenderer(QgsRuleBasedRenderer(root))


def hide(layer, context):
    """Untick a loaded layer in the Layers panel."""
    project = context.project() if context is not None else None
    node = project.layerTreeRoot().findLayer(layer) if project is not None else None
    if node is not None:
        node.setItemVisibilityChecked(False)


class LayerStyler(QgsProcessingLayerPostProcessorInterface):
    """Styles a loaded layer and, given a credit, puts it in its metadata."""

    # QGIS doesn't keep the Python object alive by itself, so the latest
    # styler for each role is kept here until it has been used.
    _alive = {}

    def __init__(self, style, credit=OSM_CREDIT, hidden=False):
        super().__init__()
        self._style = style
        self._credit = credit
        self._hidden = hidden

    @classmethod
    def create(cls, role, style, credit=OSM_CREDIT, hidden=False):
        cls._alive[role] = cls(style, credit, hidden)
        return cls._alive[role]

    def postProcessLayer(self, layer, context, feedback):
        if not layer.isValid():
            return
        self._style(layer)
        if self._credit:
            metadata = layer.metadata()
            metadata.setRights([self._credit])
            layer.setMetadata(metadata)
        if self._hidden:
            hide(layer, context)
        layer.triggerRepaint()
