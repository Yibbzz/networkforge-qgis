"""How the result layers are drawn."""

from qgis.core import QgsRuleBasedRenderer, QgsVectorLayer

from networkforge_qgis import engine, styling


def edges():
    return QgsVectorLayer("LineString?crs=EPSG:4326&field=custom:string&field=highway:string", "edges", "memory")


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


def test_after_highlights_custom_edges_on_top(qgis_app):
    layer = edges()
    styling.style_after(layer)

    custom, *network = rules(layer)
    assert custom.filterExpression() == "\"custom\" = 'yes'"
    assert [rule.label() for rule in network][-1] == "Other"
    for rule in network:
        assert custom.symbol().width() > rule.symbol().width()
        assert (custom.symbol().symbolLayer(0).renderingPass()
                > rule.symbol().symbolLayer(0).renderingPass())


def test_every_highway_group_value_is_one_the_engine_knows():
    known = set(engine.bundled_info()["tag_values"]["highway"])
    for label, highways, line in styling._GROUPS:
        assert set(highways) <= known, label


def test_styler_credits_openstreetmap(qgis_app):
    layer = edges()
    styling.LayerStyler.create("AFTER", styling.style_after).postProcessLayer(layer, None, None)
    assert layer.metadata().rights() == [styling.OSM_CREDIT]
