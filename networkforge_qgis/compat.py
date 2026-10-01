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


def whole_number_field(name):
    """A field for large whole numbers, such as feature ids."""
    try:
        from qgis.PyQt.QtCore import QMetaType

        return QgsField(name, QMetaType.Type.LongLong)
    except (ImportError, AttributeError, TypeError):  # QGIS before 3.38
        from qgis.PyQt.QtCore import QVariant

        return QgsField(name, QVariant.LongLong)
