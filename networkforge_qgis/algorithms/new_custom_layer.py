""""New custom network layer": an empty line layer ready for drawing.

The layer gets the attributes the engine understands, with drop-down
lists and checks built from what the engine accepts, so QGIS catches
invalid values while you draw.
"""

from qgis.core import (
    Qgis,
    QgsEditorWidgetSetup,
    QgsFieldConstraints,
    QgsFields,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingParameterCrs,
    QgsProcessingParameterFeatureSink,
    QgsProcessingUtils,
)

from .. import compat, engine

# The attributes offered for drawing; what each may hold comes from the engine.
FIELDS = ("highway", "maxspeed", "oneway", "lanes", "access", "bicycle", "foot",
          "motor_vehicle", "bridge", "tunnel", "layer", "name")
# How QGIS's drop-down list stores "no value".
VALUE_MAP_NULL = "{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}"
PATTERN_HINTS = {
    "maxspeed": "A speed such as 50, 30 mph, or walk",
    "lanes": "A whole number of lanes, 1 or more",
    "layer": "A whole number such as -1, 0 or 1",
}


def _expression_text(text):
    """A piece of text written as a QGIS expression string."""
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def apply_tag_widgets(layer, info):
    """Give the layer's attribute form drop-downs and checks from the engine."""
    for name, values in info["tag_values"].items():
        index = layer.fields().indexOf(name)
        if index < 0:
            continue
        choices = [{"(not set)": VALUE_MAP_NULL}] + [{value: value} for value in values]
        layer.setEditorWidgetSetup(index, QgsEditorWidgetSetup("ValueMap", {"map": choices}))
    for name, pattern in info["tag_patterns"].items():
        index = layer.fields().indexOf(name)
        if index < 0:
            continue
        layer.setConstraintExpression(
            index,
            f'"{name}" IS NULL OR "{name}" = \'\' OR '
            f'regexp_match("{name}", {_expression_text(pattern)}) > 0',
            PATTERN_HINTS.get(name, "Not a valid value"),
        )
        layer.setFieldConstraint(
            index,
            QgsFieldConstraints.Constraint.ConstraintExpression,
            QgsFieldConstraints.ConstraintStrength.ConstraintStrengthHard,
        )


class _WidgetApplier(QgsProcessingLayerPostProcessorInterface):
    """Sets up the attribute form once the new layer is in the project."""

    _alive = None  # QGIS doesn't keep the Python object alive by itself

    @classmethod
    def create(cls):
        cls._alive = cls()
        return cls._alive

    def postProcessLayer(self, layer, context, feedback):
        if layer.isValid():
            apply_tag_widgets(layer, engine.bundled_info())


class NewCustomLayerAlgorithm(QgsProcessingAlgorithm):
    CRS = "CRS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "new_custom_layer"

    def displayName(self):
        return "New custom network layer"

    def shortHelpString(self):
        return (
            "Creates an empty line layer for drawing your proposed roads, "
            "cycleways and paths, with the attributes \"Build scenario "
            "network\" understands: " + ", ".join(FIELDS) + ".\n\n"
            "Attributes with a fixed set of values (such as highway) get a "
            "drop-down list, and maxspeed, lanes and layer are checked as "
            "you type, so mistakes are caught while you draw. Only highway "
            "is needed; leave the others empty unless you know them.\n\n"
            "<b>Save it to a GeoPackage file</b> (the default is a "
            "temporary layer, which is lost when QGIS closes). Then switch "
            "on editing and draw lines that touch or cross existing "
            "streets where they should connect."
        )

    def createInstance(self):
        return NewCustomLayerAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterCrs(self.CRS, "Coordinate system", defaultValue="ProjectCrs")
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT, "Custom network layer", compat.SOURCE_VECTOR_LINE
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        info = engine.bundled_info()
        fields = QgsFields()
        for name in FIELDS:
            fields.append(compat.text_field(name))
        crs = self.parameterAsCrs(parameters, self.CRS, context)
        sink, destination = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, Qgis.WkbType.LineString, crs
        )
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))
        del sink  # closes the file

        layer = QgsProcessingUtils.mapLayerFromString(destination, context)
        if layer is not None and layer.providerType() == "ogr":
            # Saved inside the GeoPackage, so the form is set up whenever
            # the layer is opened, in any project.
            apply_tag_widgets(layer, info)
            error = compat.save_default_style(
                layer, "networkforge", "Attribute form for NetworkForge tags"
            )
            if error:
                feedback.pushWarning(
                    "The drop-down lists could not be saved with the layer, so "
                    f"they will only be there in this project: {error}"
                )
        if context.willLoadLayerOnCompletion(destination):
            context.layerToLoadOnCompletionDetails(destination).setPostProcessor(
                _WidgetApplier.create()
            )
        return {self.OUTPUT: destination}
