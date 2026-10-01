""""Build scenario network": the before and after networks for an area.

Hands the chosen extent and custom lines to the engine's `build` command
and loads what it writes. All the network work happens in the engine.
"""

import os
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDistanceArea,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProcessingOutputVectorLayer,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
)

from .. import compat, engine, styling
from .common import CustomNetworkAlgorithm

WGS84 = "EPSG:4326"


class BuildNetworkAlgorithm(CustomNetworkAlgorithm):
    EXTENT = "EXTENT"
    OSM_FILE = "OSM_FILE"
    SNAP_TOLERANCE = "SNAP_TOLERANCE"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    BEFORE_OSM = "BEFORE_OSM"
    AFTER_OSM = "AFTER_OSM"

    def name(self):
        return "build_network"

    def displayName(self):
        return "Build scenario network"

    def shortHelpString(self):
        limit = engine.bundled_info()["max_overpass_area_km2"]
        return (
            "Adds your own proposed roads, cycleways and paths to the "
            "OpenStreetMap network for an area, and gives you two networks "
            "back: <b>before</b> (OpenStreetMap as it is) and <b>after</b> "
            "(with your lines joined in).\n\n"
            "<b>Travel type</b>: pick a preset to treat every line the same "
            "way (for example primary_road), or \"Use each feature's own "
            "attributes\" if your layer has fields such as highway and "
            "maxspeed. A preset only fills in what a feature leaves empty, "
            "unless you tick the overwrite box.\n\n"
            "<b>OpenStreetMap data</b>: downloaded for the extent unless you "
            f"give a local OSM file, which is required above {limit:,} km2.\n\n"
            "<b>Results</b>: the before and after layers are added to the "
            "project with your lines highlighted, and the output folder "
            "also gets before.osm.pbf and after.osm.pbf for routers such as "
            "Valhalla.\n\n"
            "Not included: public transport, traffic simulation and turn "
            "restrictions.\n\n"
            "Map data © OpenStreetMap contributors (ODbL)."
        )

    def createInstance(self):
        return BuildNetworkAlgorithm()

    def initAlgorithm(self, config=None):
        info = engine.bundled_info()
        osm_filter = "OpenStreetMap files ({})".format(
            " ".join("*" + suffix for suffix in info["osm_formats"])
        )
        self.addParameter(QgsProcessingParameterExtent(self.EXTENT, "Area"))
        self.add_custom_parameters(info)
        self.addParameter(
            QgsProcessingParameterFile(
                self.OSM_FILE,
                "Local OSM file (instead of downloading)",
                fileFilter=osm_filter,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(self.OUTPUT_FOLDER, "Output folder")
        )
        self.add_advanced_parameters([
            QgsProcessingParameterNumber(
                self.SNAP_TOLERANCE,
                "How close a line must come to join the network (metres)",
                type=compat.NUMBER_DOUBLE,
                defaultValue=1.0,
                minValue=0.0,
            ),
        ])

        self.addOutput(QgsProcessingOutputVectorLayer(self.BEFORE, "Before network"))
        self.addOutput(QgsProcessingOutputVectorLayer(self.AFTER, "After network"))
        self.addOutput(QgsProcessingOutputFile(self.BEFORE_OSM, "Before network (OSM PBF)"))
        self.addOutput(QgsProcessingOutputFile(self.AFTER_OSM, "After network (OSM PBF)"))

    def processAlgorithm(self, parameters, context, feedback):
        if not self.ensure_engine(feedback):
            return {}

        info = engine.bundled_info()
        osm_file = self.parameterAsFile(parameters, self.OSM_FILE, context)
        bbox = self._bbox(parameters, context, feedback, info, osm_file)
        custom_file = self.export_custom(parameters, context, feedback)

        folder = Path(self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))
        folder.mkdir(parents=True, exist_ok=True)
        outputs = {
            "--baseline-gpkg": folder / "before.gpkg",
            "--gpkg": folder / "after.gpkg",
            "--baseline-out": folder / "before.osm.pbf",
            "--out": folder / "after.osm.pbf",
        }
        self._remove_old(outputs.values())

        args = ["build", "--json", f"--bbox={bbox}",
                *self.custom_args(parameters, context, custom_file)]
        if osm_file:
            args += ["--osm-source", osm_file]
        args += ["--snap-tolerance",
                 self.parameterAsDouble(parameters, self.SNAP_TOLERANCE, context)]
        for flag, path in outputs.items():
            args += [flag, path]

        if self.run_engine(args, feedback) is None:
            return {}

        feedback.pushInfo(f"Done. Files are in {folder}")
        feedback.pushInfo(f"Map data {styling.OSM_CREDIT}")

        before = self._load(context, outputs["--baseline-gpkg"], "Before network",
                            self.BEFORE, styling.style_before)
        after = self._load(context, outputs["--gpkg"], "After network",
                           self.AFTER, styling.style_after)
        return {
            self.BEFORE: before,
            self.AFTER: after,
            self.BEFORE_OSM: str(outputs["--baseline-out"]),
            self.AFTER_OSM: str(outputs["--out"]),
            self.OUTPUT_FOLDER: str(folder),
        }

    def _bbox(self, parameters, context, feedback, info, osm_file):
        """The area as "W,S,E,N" in longitude/latitude, as the engine wants it."""
        wgs84 = QgsCoordinateReferenceSystem(WGS84)
        extent = self.parameterAsExtent(parameters, self.EXTENT, context, wgs84)
        if extent.isNull() or extent.isEmpty():
            raise QgsProcessingException("The area is empty: choose an extent.")

        measure = QgsDistanceArea()
        measure.setSourceCrs(wgs84, context.transformContext())
        measure.setEllipsoid("WGS84")
        area = measure.measureArea(
            self.parameterAsExtentGeometry(parameters, self.EXTENT, context, wgs84)
        ) / 1e6
        feedback.pushInfo(f"Area: about {area:,.0f} km2")
        limit = info["max_overpass_area_km2"]
        if area > limit and not osm_file:
            feedback.pushWarning(
                f"The area is over {limit:,} km2, which is too big to "
                "download from OpenStreetMap. Choose a smaller area or give "
                "a local OSM file."
            )
        return ",".join(
            f"{value:.7f}"
            for value in (extent.xMinimum(), extent.yMinimum(),
                          extent.xMaximum(), extent.yMaximum())
        )

    @staticmethod
    def _remove_old(paths):
        """Clear results of an earlier run in the same folder."""
        for path in paths:
            try:
                if path.exists():
                    os.remove(path)
            except OSError:
                raise QgsProcessingException(
                    f"Could not replace {path}. It is probably still open in "
                    "QGIS: remove the earlier Before and After layers from "
                    "the project, or choose another output folder."
                )

    @staticmethod
    def _load(context, gpkg, name, output, style):
        """Ask QGIS to add a network's edges to the project when the tool ends."""
        source = f"{gpkg}|layername=edges"
        details = QgsProcessingContext.LayerDetails(name, context.project(), output)
        details.forceName = True
        details.setPostProcessor(styling.LayerStyler.create(output, style))
        context.addLayerToLoadOnCompletion(source, details)
        return source
