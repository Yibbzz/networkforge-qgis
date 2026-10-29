"""How the result layers are drawn."""

from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingContext,
    QgsProject,
    QgsRuleBasedRenderer,
    QgsVectorLayer,
)

from networkforge_qgis import engine, styling


def edges(*extra):
    fields = "".join(f"&field={name}:string" for name in ("highway", *extra))
    return QgsVectorLayer(f"LineString?crs=EPSG:4326{fields}", "edges", "memory")


def rules(layer):
    assert isinstance(layer.renderer(), QgsRuleBasedRenderer)
    return layer.renderer().rootRule().children()


def test_before_is_coloured_by_kind_of_street(qgis_app):
    layer = edges()
    styling.style_before(layer)

    labels = [rule.label() for rule in rules(layer)]
    assert labels == ["Main roads", "Secondary roads", "Streets", "Cycleways", "Paths", "Other"]
    assert rules(layer)[-1].isElse()
    assert "'cycleway'" in rules(layer)[3].filterExpression()


def test_after_highlights_custom_and_changed_edges_on_top(qgis_app):
    layer = edges("custom", "modified")
    styling.style_after(layer)

    custom, changed, *network = rules(layer)
    assert custom.filterExpression() == "\"custom\" = 'yes'"
    assert changed.filterExpression() == "\"modified\" = 'yes'"
    assert custom.symbol().color() != changed.symbol().color()
    assert [rule.label() for rule in network][-1] == "Other"
    for highlighted in (custom, changed):
        for rule in network:
            assert highlighted.symbol().width() > rule.symbol().width()
            assert (highlighted.symbol().symbolLayer(0).renderingPass()
                    > rule.symbol().symbolLayer(0).renderingPass())


def test_after_leaves_out_a_highlight_whose_column_the_layer_lacks(qgis_app):
    # No changed streets: the engine writes no "modified" column.
    layer = edges("custom")
    styling.style_after(layer)
    assert [rule.label() for rule in rules(layer)][:2] == ["Custom", "Main roads"]

    # Changes only, no new lines: no "custom" column.
    layer = edges("modified")
    styling.style_after(layer)
    assert [rule.label() for rule in rules(layer)][:2] == ["Changed", "Main roads"]


def test_every_highway_group_value_is_one_the_engine_knows():
    known = set(engine.bundled_info()["tag_values"]["highway"])
    for label, highways, line in styling._GROUPS:
        assert set(highways) <= known, label


def test_styler_credits_openstreetmap(qgis_app):
    layer = edges("custom")
    styling.LayerStyler.create("AFTER", styling.style_after).postProcessLayer(layer, None, None)
    assert layer.metadata().rights() == [styling.OSM_CREDIT]


def test_styler_gives_no_credit_for_a_network_without_openstreetmap(qgis_app):
    layer = edges()
    styler = styling.LayerStyler.create("NETWORK", styling.style_before, None)
    styler.postProcessLayer(layer, None, None)
    assert layer.metadata().rights() == []
    assert [rule.label() for rule in rules(layer)][0] == "Main roads"


def nodes(*rows, columns=("highway", "barrier", "crossing", "railway")):
    fields = "".join(f"&field={name}:string" for name in columns)
    layer = QgsVectorLayer(f"Point?crs=EPSG:4326{fields}", "nodes", "memory")
    provider = layer.dataProvider()
    for row in rows:
        feature = QgsFeature(layer.fields())
        feature.setAttributes([row.get(name) for name in columns])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0, 0)))
        provider.addFeature(feature)
    return layer


def test_nodes_show_only_what_routers_act_on(qgis_app):
    layer = nodes({}, {"highway": "turning_circle"}, {"barrier": "bollard"},
                  {"barrier": "kerb"}, {"highway": "traffic_signals"},
                  {"crossing": "zebra"}, {"highway": "give_way"},
                  {"railway": "level_crossing"})
    styling.style_nodes(layer)

    shown = sorted(str(f["barrier"] or f["highway"] or f["crossing"] or f["railway"])
                   for f in layer.getFeatures())
    assert shown == ["bollard", "give_way", "kerb", "level_crossing", "traffic_signals",
                     "zebra"]
    labels = [rule.label() for rule in rules(layer)]
    assert labels == ["Crossings", "Level crossings", "Stop and give way",
                      "Traffic signals", "Kerbs", "Barriers"]
    barriers = rules(layer)[-1].filterExpression()
    assert "'kerb'" in barriers  # kerbs aren't drawn as barriers


def test_nodes_use_only_the_columns_the_layer_has(qgis_app):
    # A network with signals but no barriers or crossings at all.
    layer = nodes({"highway": "traffic_signals"}, {}, columns=("highway",))
    styling.style_nodes(layer)
    assert layer.featureCount() == 1
    assert "Barriers" not in [rule.label() for rule in rules(layer)]

    layer = nodes({}, columns=("ref",))
    styling.style_nodes(layer)
    assert layer.isValid() and layer.featureCount() == 0


def test_styler_can_untick_the_layer(qgis_app, qgis_new_project):
    layer = nodes({"barrier": "gate"})
    project = QgsProject.instance()
    project.addMapLayer(layer)
    context = QgsProcessingContext()
    context.setProject(project)
    styling.LayerStyler.create("BEFORE_NODES", styling.style_nodes, hidden=True) \
        .postProcessLayer(layer, context, None)
    assert not project.layerTreeRoot().findLayer(layer).isVisible()


def restrictions():
    return QgsVectorLayer("LineString?crs=EPSG:4326&field=custom:string"
                          "&field=restriction:string", "restrictions", "memory")


def test_restrictions_are_arrows_with_the_users_on_top(qgis_app):
    layer = restrictions()
    styling.style_restrictions(layer)

    mine, osm = rules(layer)
    assert mine.filterExpression() == "\"custom\" = 'yes'" and osm.isElse()
    assert mine.label() == "Your turn restrictions"
    for rule in (mine, osm):
        line, arrow = rule.symbol().symbolLayers()
        assert arrow.subSymbol() is not None  # the arrowhead
        assert line.renderingPass() == arrow.renderingPass() == 2
    assert mine.symbol().width() > osm.symbol().width()
    assert mine.symbol().color() == styling.QgsLineSymbol.createSimple(
        styling._CUSTOM_LINE).color()


def test_nodes_your_points_tagged_are_shown_and_ringed(qgis_app):
    layer = nodes({}, {"custom": "yes"}, {"modified": "yes"}, {"barrier": "gate"},
                  columns=("highway", "barrier", "custom", "modified"))
    styling.style_nodes(layer)

    assert layer.featureCount() == 3  # the plain junction is left out
    new, changed, *groups = rules(layer)
    assert new.filterExpression() == "\"custom\" = 'yes'"
    assert changed.filterExpression() == "\"modified\" = 'yes'"
    assert new.symbol().symbolLayer(0).renderingPass() == 1
    assert [rule.label() for rule in groups][-1] == "Barriers"
