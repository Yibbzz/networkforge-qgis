""""Build standalone network": a network from the user's own lines alone.

Hands the lines to the engine's `build --no-osm` command and loads what
it writes. There is no OpenStreetMap network, so no area, no download
and no "before" network. All the network work happens in the engine.
"""

from pathlib import Path

from qgis.core import (
    QgsProcessingOutputFile,
    QgsProcessingOutputVectorLayer,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFolderDestination,
)

from .. import engine, styling
from .common import (
    POINTS_HELP,
    CustomNetworkAlgorithm,
    more_features_help,
    turn_restrictions_help,
)

# How the engine's --join-at choices read in the form. A choice a newer
# engine adds is shown under its own name.
_JOIN_LABELS = {
    "crossings": "Wherever lines cross or touch",
    "vertices": "Only where lines share a vertex",
}


class StandaloneNetworkAlgorithm(CustomNetworkAlgorithm):
    JOIN_AT = "JOIN_AT"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    NETWORK = "NETWORK"
    NETWORK_OSM = "NETWORK_OSM"

    def name(self):
        return "standalone_network"

    def displayName(self):
        return "Build standalone network"

    def shortHelpString(self):
        return (
            "Turns a line layer of your own (council centrelines, a survey, "
            "the streets of a planned neighbourhood) into a routable "
            "network, <b>without OpenStreetMap</b>. Nothing is downloaded "
            "and there is no area to choose: the network is your lines. To "
            "add lines to the OpenStreetMap network instead, use \"Build "
            "scenario network\".\n\n"
            "<b>Travel type</b>: every line needs a kind of street. Pick a "
            "preset to treat every line the same way, or \"Use each "
            "feature's own attributes\" if your layer has fields such as "
            "highway, maxspeed and oneway. A preset only fills in what a "
            "feature leaves empty, unless you tick the overwrite box.\n\n"
            "<b>Lines join</b>: \"wherever lines cross or touch\" suits "
            "lines drawn without thought for junctions; a line marked as a "
            "bridge or tunnel, or on another layer, still crosses without "
            "joining. \"Only where lines share a vertex\" suits data that "
            "already has a vertex at every junction, such as street "
            "centrelines, where a flyover crosses a road without a shared "
            "point. Either way, ends that stop within the snap distance of "
            "each other (1 m, under Advanced parameters) are joined.\n\n"
            "<b>Results</b>: a Network layer coloured by kind of street, "
            "with travel columns (car, bike, walk, speed_kph, direction) "
            "for QGIS's network tools, and network.osm.pbf in the output "
            "folder for routers such as Valhalla.\n\n"
            "If the lines don't form one connected network, a warning says "
            "so and the lines outside the largest piece are selected: most "
            "often they stop short of the street they should meet.\n\n"
            f"{turn_restrictions_help()}\n\n"
            f"{POINTS_HELP}\n\n"
            f"{more_features_help(existing_streets=False)}\n\n"
            f"<a href=\"{engine.guide_url('a-network-of-your-own-lines')}\">"
            "Guide</a>."
        )

    def createInstance(self):
        return StandaloneNetworkAlgorithm()

    def initAlgorithm(self, config=None):
        info = engine.bundled_info()
        self._join_at = list(info["join_at"])
        self.add_custom_parameters(info, label="Network layer")
        self.addParameter(
            QgsProcessingParameterEnum(
                self.JOIN_AT,
                "Lines join",
                [_JOIN_LABELS.get(name, name) for name in self._join_at],
                defaultValue=self._join_at.index("crossings"),
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, "Output folder")
        )
        self.add_advanced_parameters(
            [self.snap_tolerance_parameter(
                "How close lines must come to be joined (metres)"
            )],
            network_type=False,
        )

        self.addOutput(QgsProcessingOutputVectorLayer(self.NETWORK, "Network"))
        self.addOutput(QgsProcessingOutputFile(self.NETWORK_OSM, "Network (OSM PBF)"))

    def processAlgorithm(self, parameters, context, feedback):
        if not self.ensure_engine(feedback):
            return {}

        custom_file = self.export_custom(parameters, context, feedback)

        folder = Path(self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))
        folder.mkdir(parents=True, exist_ok=True)
        outputs = {
            "--gpkg": folder / "network.gpkg",
            "--out": folder / "network.osm.pbf",
        }
        self.remove_old(outputs.values())

        join_at = self._join_at[self.parameterAsEnum(parameters, self.JOIN_AT, context)]
        args = ["build", "--json", "--no-osm", "--join-at", join_at,
                *self.custom_args(parameters, context, custom_file),
                "--snap-tolerance",
                self.parameterAsDouble(parameters, self.SNAP_TOLERANCE, context)]
        for flag, path in outputs.items():
            args += [flag, path]

        done = self.run_engine(args, feedback)
        if done is None:
            return {}

        feedback.pushInfo(f"Network: {done.get('edges', 0):,} street segments.")
        self.report_additions(done, feedback, "network.osm.pbf")
        feedback.pushInfo(f"Done. Files are in {folder}")

        # No OpenStreetMap data in this network, so no credit to give.
        network = self.load_edges(context, outputs["--gpkg"], "Network",
                                  self.NETWORK, styling.style_before, credit=None)
        return {
            self.NETWORK: network,
            self.NETWORK_OSM: str(outputs["--out"]),
            self.OUTPUT_FOLDER: str(folder),
        }
