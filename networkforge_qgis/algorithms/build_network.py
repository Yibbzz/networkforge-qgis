""""Build scenario network": the before and after networks for an area.

Hands the chosen extent and custom lines to the engine's `build` command
and loads what it writes. All the network work happens in the engine.
"""

import os
import re
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDistanceArea,
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsFields,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProcessingOutputVectorLayer,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingUtils,
)

from .. import compat, engine, styling

# Added to the exported features so the engine's messages can name QGIS
# feature ids, whatever ids the exported file ends up with.
ID_FIELD = "nf_src_fid"
FEATURE_ATTRIBUTES = "Use each feature's own attributes"
WGS84 = "EPSG:4326"


def parse_tags(text):
    """"maxspeed=30 mph; lanes=2" -> ["maxspeed=30 mph", "lanes=2"].

    Raises ValueError naming the first piece that isn't KEY=VALUE.
    """
    tags = []
    for piece in re.split(r"[;\n]", text or ""):
        piece = piece.strip()
        if not piece:
            continue
        key, sep, value = piece.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise ValueError(piece)
        tags.append(f"{key.strip()}={value.strip()}")
    return tags


class BuildNetworkAlgorithm(QgsProcessingAlgorithm):
    EXTENT = "EXTENT"
    CUSTOM = "CUSTOM"
    PRESET = "PRESET"
    MAXSPEED = "MAXSPEED"
    EXTRA_TAGS = "EXTRA_TAGS"
    OVERWRITE = "OVERWRITE"
    NETWORK_TYPE = "NETWORK_TYPE"
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
        self._presets = list(info["presets"])
        self._network_types = list(info["network_types"])
        osm_filter = "OpenStreetMap files ({})".format(
            " ".join("*" + suffix for suffix in info["osm_formats"])
        )

        self.addParameter(QgsProcessingParameterExtent(self.EXTENT, "Area"))
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CUSTOM, "Custom network layer", [compat.SOURCE_VECTOR_LINE]
            )
        )
        preset_labels = [FEATURE_ATTRIBUTES] + [
            "{} ({})".format(
                name, ", ".join(f"{k}={v}" for k, v in preset["tags"].items())
            )
            for name, preset in info["presets"].items()
        ]
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PRESET, "Travel type", preset_labels, defaultValue=0
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.MAXSPEED,
                "Speed limit for all lines, e.g. 50 or 30 mph",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.OVERWRITE,
                "Overwrite the features' own attributes with the choices above",
                defaultValue=False,
            )
        )
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

        advanced = [
            QgsProcessingParameterEnum(
                self.NETWORK_TYPE,
                "OpenStreetMap network to use",
                self._network_types,
                defaultValue=self._network_types.index("all"),
            ),
            QgsProcessingParameterString(
                self.EXTRA_TAGS,
                "Other tags for all lines, e.g. lanes=2; bicycle=no",
                optional=True,
            ),
            QgsProcessingParameterNumber(
                self.SNAP_TOLERANCE,
                "How close a line must come to join the network (metres)",
                type=compat.NUMBER_DOUBLE,
                defaultValue=1.0,
                minValue=0.0,
            ),
        ]
        for parameter in advanced:
            parameter.setFlags(parameter.flags() | compat.FLAG_ADVANCED)
            self.addParameter(parameter)

        self.addOutput(QgsProcessingOutputVectorLayer(self.BEFORE, "Before network"))
        self.addOutput(QgsProcessingOutputVectorLayer(self.AFTER, "After network"))
        self.addOutput(QgsProcessingOutputFile(self.BEFORE_OSM, "Before network (OSM PBF)"))
        self.addOutput(QgsProcessingOutputFile(self.AFTER_OSM, "After network (OSM PBF)"))

    def checkParameterValues(self, parameters, context):
        try:
            parse_tags(self.parameterAsString(parameters, self.EXTRA_TAGS, context))
        except ValueError as err:
            return False, (
                f"Other tags: \"{err}\" should look like key=value. Separate "
                "several with semicolons, e.g. lanes=2; bicycle=no"
            )
        return super().checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        try:
            engine.ensure_installed(feedback)
        except engine.EngineCanceled:
            return {}
        except engine.EngineError as err:
            raise QgsProcessingException(str(err))

        info = engine.bundled_info()
        osm_file = self.parameterAsFile(parameters, self.OSM_FILE, context)
        bbox = self._bbox(parameters, context, feedback, info, osm_file)
        custom_file = self._export_custom(parameters, context, feedback)

        folder = Path(self.parameterAsString(parameters, self.OUTPUT_FOLDER, context))
        folder.mkdir(parents=True, exist_ok=True)
        outputs = {
            "--baseline-gpkg": folder / "before.gpkg",
            "--gpkg": folder / "after.gpkg",
            "--baseline-out": folder / "before.osm.pbf",
            "--out": folder / "after.osm.pbf",
        }
        self._remove_old(outputs.values())

        args = ["build", "--json", f"--bbox={bbox}", "--custom", custom_file,
                "--id-field", ID_FIELD]
        preset = self.parameterAsEnum(parameters, self.PRESET, context)
        if preset > 0:
            args += ["--preset", self._presets[preset - 1]]
        maxspeed = self.parameterAsString(parameters, self.MAXSPEED, context).strip()
        if maxspeed:
            args += ["--tag", f"maxspeed={maxspeed}"]
        for tag in parse_tags(self.parameterAsString(parameters, self.EXTRA_TAGS, context)):
            args += ["--tag", tag]
        if self.parameterAsBoolean(parameters, self.OVERWRITE, context):
            args.append("--overwrite-tags")
        network_type = self.parameterAsEnum(parameters, self.NETWORK_TYPE, context)
        args += ["--network-type", self._network_types[network_type]]
        if osm_file:
            args += ["--osm-source", osm_file]
        args += ["--snap-tolerance",
                 self.parameterAsDouble(parameters, self.SNAP_TOLERANCE, context)]
        for flag, path in outputs.items():
            args += [flag, path]

        error = {}

        def on_event(event):
            kind = event.get("event")
            if kind == "progress":
                feedback.setProgress(100 * (event["step"] - 1) / event["total"])
                feedback.setProgressText(event["message"])
            elif kind == "warning":
                feedback.pushWarning(event["message"])
            elif kind == "error":
                error.update(event)

        try:
            code = engine.run(args, feedback, on_event)
        except engine.EngineCanceled:
            return {}
        except engine.EngineError as err:
            raise QgsProcessingException(str(err))

        if error or code != 0:
            raise QgsProcessingException(self._error_text(error, code))

        feedback.setProgress(100)
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

    def _export_custom(self, parameters, context, feedback):
        """Write the chosen lines to a temporary GeoPackage for the engine."""
        source = self.parameterAsSource(parameters, self.CUSTOM, context)
        if source is None:
            raise QgsProcessingException(
                self.invalidSourceError(parameters, self.CUSTOM)
            )
        # A field called "fid" would clash with the GeoPackage's own ids.
        kept = [i for i, field in enumerate(source.fields())
                if field.name().lower() not in ("fid", ID_FIELD)]
        fields = QgsFields()
        for i in kept:
            fields.append(source.fields().at(i))
        fields.append(compat.whole_number_field(ID_FIELD))

        path = QgsProcessingUtils.generateTempFilename("nf_custom.gpkg", context)
        sink, _ = QgsProcessingUtils.createFeatureSink(
            path, context, fields, source.wkbType(), source.sourceCrs()
        )
        count = 0
        # Geometry problems are the engine's to report, with feature ids.
        for feature in source.getFeatures(QgsFeatureRequest(), compat.SKIP_GEOMETRY_CHECKS):
            if feedback.isCanceled():
                break
            out = QgsFeature(fields)
            out.setGeometry(feature.geometry())
            values = feature.attributes()
            out.setAttributes([values[i] for i in kept] + [feature.id()])
            if not sink.addFeature(out, QgsFeatureSink.FastInsert):
                raise QgsProcessingException(
                    f"Could not prepare feature {feature.id()} for the engine: "
                    f"{sink.lastError()}"
                )
            count += 1
        del sink  # closes the file so the engine can read it
        if count == 0:
            raise QgsProcessingException(
                "The custom network layer has no features to add. If "
                "\"Selected features only\" is ticked, select some first."
            )
        feedback.pushInfo(f"Custom lines: {count}")
        return path

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
    def _error_text(error, code):
        if not error:
            return (
                f"The engine stopped unexpectedly (exit code {code}). "
                f"Details: {engine.log_path()}"
            )
        message = error.get("message", "The engine reported an error.")
        issues = error.get("issues") or []
        # With issues, the engine's message lists them as text after its
        # first line; they are listed from the event instead.
        lines = [message.splitlines()[0] if issues else message]
        for issue in issues:
            if issue.get("feature") is None:
                lines.append(f"  - {issue['message']}")
            else:
                lines.append(f"  - feature {issue['feature']}: {issue['message']}")
        if error.get("guide"):
            lines.append(f"How to fix this: {engine.guide_url(error['guide'])}")
        return "\n".join(lines)

    @staticmethod
    def _load(context, gpkg, name, output, style):
        """Ask QGIS to add a network's edges to the project when the tool ends."""
        source = f"{gpkg}|layername=edges"
        details = QgsProcessingContext.LayerDetails(name, context.project(), output)
        details.forceName = True
        details.setPostProcessor(styling.LayerStyler.create(output, style))
        context.addLayerToLoadOnCompletion(source, details)
        return source
