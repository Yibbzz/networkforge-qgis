"""How the result layers are drawn."""

from qgis.core import QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsVectorLayer

from networkforge_qgis import styling


def edges():
    return QgsVectorLayer("LineString?crs=EPSG:4326&field=custom:string", "edges", "memory")


def test_before_is_one_plain_style(qgis_app):
    layer = edges()
    styling.style_before(layer)
    assert isinstance(layer.renderer(), QgsSingleSymbolRenderer)


def test_after_highlights_custom_edges_on_top(qgis_app):
    layer = edges()
    styling.style_after(layer)

    renderer = layer.renderer()
    assert isinstance(renderer, QgsRuleBasedRenderer)
    custom, rest = renderer.rootRule().children()
    assert custom.filterExpression() == "\"custom\" = 'yes'"
    assert rest.isElse()
    assert custom.symbol().width() > rest.symbol().width()
    assert custom.symbol().symbolLayer(0).renderingPass() > rest.symbol().symbolLayer(0).renderingPass()


def test_styler_credits_openstreetmap(qgis_app):
    layer = edges()
    styling.LayerStyler.create("AFTER", styling.style_after).postProcessLayer(layer, None, None)
    assert layer.metadata().rights() == [styling.OSM_CREDIT]
