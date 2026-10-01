"""Names that moved between QGIS versions, so the rest reads the same.

QGIS 3.36 gathered these under `Qgis`, and QGIS 4 dropped the old
spellings; QGIS 3.34 only has the old ones.
"""

from qgis.core import (
    Qgis,
    QgsField,
    QgsProcessing,
    QgsProcessingFeatureSource,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterNumber,
)

try:
    SOURCE_VECTOR_LINE = Qgis.ProcessingSourceType.VectorLine
    NUMBER_DOUBLE = Qgis.ProcessingNumberParameterType.Double
    FLAG_ADVANCED = Qgis.ProcessingParameterFlag.Advanced
    SKIP_GEOMETRY_CHECKS = Qgis.ProcessingFeatureSourceFlag.SkipGeometryValidityChecks
except AttributeError:  # QGIS 3.34
    SOURCE_VECTOR_LINE = QgsProcessing.TypeVectorLine
    NUMBER_DOUBLE = QgsProcessingParameterNumber.Double
    FLAG_ADVANCED = QgsProcessingParameterDefinition.FlagAdvanced
    SKIP_GEOMETRY_CHECKS = QgsProcessingFeatureSource.FlagSkipGeometryValidityChecks


def text_field(name):
    """A text field."""
    try:
        from qgis.PyQt.QtCore import QMetaType

        return QgsField(name, QMetaType.Type.QString)
    except (ImportError, AttributeError, TypeError):  # QGIS before 3.38
        from qgis.PyQt.QtCore import QVariant

        return QgsField(name, QVariant.String)


def whole_number_field(name):
    """A field for large whole numbers, such as feature ids."""
    try:
        from qgis.PyQt.QtCore import QMetaType

        return QgsField(name, QMetaType.Type.LongLong)
    except (ImportError, AttributeError, TypeError):  # QGIS before 3.38
        from qgis.PyQt.QtCore import QVariant

        return QgsField(name, QVariant.LongLong)


def save_default_style(layer, name, description):
    """Save the layer's style inside its file as the default.

    Returns "" on success, otherwise what went wrong.
    """
    if hasattr(layer, "saveStyleToDatabaseV2"):  # QGIS 3.44 and later
        _, error = layer.saveStyleToDatabaseV2(name, description, True, "")
    else:
        error = layer.saveStyleToDatabase(name, description, True, "")
    # The result is judged by whether the style is there: the returned
    # flags differ between QGIS versions, and a message can be a mere note.
    if layer.listStylesInDatabase()[0] > 0:
        return ""
    return error or "the style could not be written"
