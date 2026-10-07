""""Check custom network layer": validate the lines before building.

Runs the engine's `check` command, which reads the layer and its tags
but downloads nothing, so it answers in seconds.
"""

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProcessingOutputNumber,
    QgsProcessingParameterExtent,
)

from .. import engine
from .common import CustomNetworkAlgorithm

WGS84 = "EPSG:4326"


class CheckLayerAlgorithm(CustomNetworkAlgorithm):
    EXTENT = "EXTENT"
    FEATURES = "FEATURES"

    def name(self):
        return "check_layer"

    def displayName(self):
        return "Check custom network layer"

    def shortHelpString(self):
        return (
            "Checks that your lines and their attributes can be used by "
            "\"Build scenario network\" or \"Build standalone network\", "
            "without downloading anything.\n\n"
            "Choose the same travel type you will build with: a preset, or "
            "\"Use each feature's own attributes\".\n\n"
            "If something is wrong, the tool stops with a list of the "
            "problems and a link to the guide for fixing them, and the "
            "features concerned are selected in the layer. If all is well, "
            "it says how many lines each kind of traveller can use, and "
            "how many change existing streets, are turn restrictions or are "
            "points (barriers, signals, crossings). "
            "Whether a turn restriction sits on a junction is only known "
            "when the network is built.\n\n"
            "<b>Area</b> is optional: give the area you will build for to "
            "also check that the lines fall inside it."
        )

    def createInstance(self):
        return CheckLayerAlgorithm()

    def initAlgorithm(self, config=None):
        self.add_custom_parameters(engine.bundled_info(), lines_optional=True)
        self.addParameter(
            QgsProcessingParameterExtent(self.EXTENT, "Area", optional=True)
        )
        self.add_advanced_parameters()
        self.addOutput(QgsProcessingOutputNumber(self.FEATURES, "Features checked"))

    def processAlgorithm(self, parameters, context, feedback):
        if not self.ensure_engine(feedback):
            return {}
        custom_file = self.export_custom(parameters, context, feedback)

        args = ["check", "--json", *self.custom_args(parameters, context, custom_file)]
        extent = self.parameterAsExtent(
            parameters, self.EXTENT, context, QgsCoordinateReferenceSystem(WGS84)
        )
        if not extent.isNull() and not extent.isEmpty():
            args.append("--bbox={:.7f},{:.7f},{:.7f},{:.7f}".format(
                extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()
            ))

        done = self.run_engine(args, feedback)
        if done is None:
            return {}

        feedback.pushInfo(f"No problems found in {done.get('features', 0)} feature(s).")
        for modes, count in (done.get("modes") or {}).items():
            feedback.pushInfo(f"  {count} usable by: {modes}")
        for key, label in (("edits", "change existing streets"),
                           ("turn_restrictions", "turn restriction(s)"),
                           ("points", "point(s): barriers, signals, crossings")):
            if done.get(key):
                feedback.pushInfo(f"  {done[key]} {label}")
        return {self.FEATURES: done.get("features")}
