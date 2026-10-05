"""How the result layers are drawn."""

from qgis.core import QgsRuleBasedRenderer, QgsVectorLayer

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
