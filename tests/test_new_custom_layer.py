"""New custom network layer: fields, drop-down lists and checks."""

from qgis import processing
from qgis.core import (
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsFieldConstraints,
    QgsProcessingContext,
    QgsVectorLayer,
)

from networkforge_qgis import engine
from networkforge_qgis.algorithms.new_custom_layer import (
    FIELDS,
    VALUE_MAP_NULL,
    _WidgetApplier,
)

ALGORITHM = "networkforge:new_custom_layer"


def is_allowed(layer, field, value):
    """Whether the layer's check on a field accepts a value."""
    feature = QgsFeature(layer.fields())
    feature[field] = value
    context = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
    context.setFeature(feature)
    expression = QgsExpression(layer.constraintExpression(layer.fields().indexOf(field)))
    result = expression.evaluate(context)
    assert not expression.hasEvalError(), expression.evalErrorString()
    return bool(result)


def assert_form_is_set_up(layer):
    info = engine.bundled_info()
    names = [field.name() for field in layer.fields() if field.name() != "fid"]
    assert names == list(FIELDS)

    setup = layer.editorWidgetSetup(layer.fields().indexOf("highway"))
    assert setup.type() == "ValueMap"
    choices = [value for entry in setup.config()["map"] for value in entry.values()]
    assert choices == [VALUE_MAP_NULL] + info["tag_values"]["highway"]

    for field in info["tag_patterns"]:
        index = layer.fields().indexOf(field)
        constraints = layer.fields().at(index).constraints()
        assert constraints.constraintStrength(
            QgsFieldConstraints.Constraint.ConstraintExpression
        ) == QgsFieldConstraints.ConstraintStrength.ConstraintStrengthHard
        assert layer.constraintDescription(index)

    for value in (None, "", "50", "30 mph", "walk"):
        assert is_allowed(layer, "maxspeed", value), value
    for value in ("fast", "30mph", "-5"):
        assert not is_allowed(layer, "maxspeed", value), value
    assert is_allowed(layer, "lanes", "2") and not is_allowed(layer, "lanes", "0")
    assert is_allowed(layer, "layer", "-1") and not is_allowed(layer, "layer", "1.5")


def test_fields_are_all_tags_the_engine_knows():
    assert set(FIELDS) <= set(engine.bundled_info()["tag_keys"])


def test_geopackage_keeps_its_form_when_opened_again(provider, feedback, tmp_path):
    path = tmp_path / "plan.gpkg"

    results = processing.run(ALGORITHM, {"CRS": "EPSG:27700", "OUTPUT": str(path)},
                             feedback=feedback)

    assert not feedback.warnings
    layer = QgsVectorLayer(results["OUTPUT"], "plan", "ogr")
    assert layer.isValid()
    assert layer.crs().authid() == "EPSG:27700"
    assert layer.featureCount() == 0
    assert_form_is_set_up(layer)


def test_temporary_layer_gets_its_form_when_loaded(provider, feedback):
    context = QgsProcessingContext()
    results = processing.run(ALGORITHM, {"CRS": "EPSG:4326", "OUTPUT": "TEMPORARY_OUTPUT"},
                             context=context, feedback=feedback)
    layer = results["OUTPUT"]  # processing.run hands back temporary layers themselves
    assert layer.providerType() == "memory"

    # What QGIS calls once it has added the layer to the project.
    _WidgetApplier.create().postProcessLayer(layer, context, feedback)

    assert_form_is_set_up(layer)
