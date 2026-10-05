"""What the tools that hand a custom line layer to the engine share.

The form fields for the layer and its travel type, exporting the lines
to a file the engine can read, running the engine, and showing its
warnings and errors - including selecting the features they are about.
"""

import os
import re

from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsFields,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingUtils,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QObject, pyqtSignal

from .. import compat, engine, styling

# Added to the exported features so the engine's messages can name QGIS
# feature ids, whatever ids the exported file ends up with.
ID_FIELD = "nf_src_fid"
FEATURE_ATTRIBUTES = "Use each feature's own attributes"


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


def error_text(error, code):
    """What to tell the user when the engine failed.

    `error` is the engine's error event ({} if it sent none) and `code`
    its exit code.
    """
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


class FeatureSelector(QObject):
    """Selects features in a project layer, from a tool's background thread.

    Tools run off the main thread, where layers must not be touched. This
    object is created on the main thread, so a request sent through its
    signal is carried out there.
    """

    _requested = pyqtSignal(list)

    def __init__(self, layer_id):
        super().__init__()
        self._layer_id = layer_id
        self._requested.connect(self._select)

    def select(self, feature_ids):
        self._requested.emit(list(feature_ids))

    def _select(self, feature_ids):
        layer = QgsProject.instance().mapLayer(self._layer_id)
        if layer is not None:
            layer.selectByIds(feature_ids)


class CustomNetworkAlgorithm(QgsProcessingAlgorithm):
    """Base for the tools that send a custom line layer to the engine."""

    CUSTOM = "CUSTOM"
    PRESET = "PRESET"
    MAXSPEED = "MAXSPEED"
    EXTRA_TAGS = "EXTRA_TAGS"
    OVERWRITE = "OVERWRITE"
    NETWORK_TYPE = "NETWORK_TYPE"
    SNAP_TOLERANCE = "SNAP_TOLERANCE"

    def add_custom_parameters(self, info, label="Custom network layer"):
        """The layer and how its lines are travelled."""
        self._presets = list(info["presets"])
        self._network_types = list(info["network_types"])
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CUSTOM, label, [compat.SOURCE_VECTOR_LINE]
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

    def add_advanced_parameters(self, extra=(), network_type=True):
        """Rarely changed settings, tucked under "Advanced parameters".

        `network_type` is left out by a tool that uses no OpenStreetMap
        network.
        """
        advanced = []
        if network_type:
            advanced.append(
                QgsProcessingParameterEnum(
                    self.NETWORK_TYPE,
                    "OpenStreetMap network to use",
                    self._network_types,
                    defaultValue=self._network_types.index("all"),
                )
            )
        advanced += [
            QgsProcessingParameterString(
                self.EXTRA_TAGS,
                "Other tags for all lines, e.g. lanes=2; bicycle=no",
                optional=True,
            ),
            *extra,
        ]
        for parameter in advanced:
            parameter.setFlags(parameter.flags() | compat.FLAG_ADVANCED)
            self.addParameter(parameter)

    def snap_tolerance_parameter(self, label):
        """How close lines must come to be joined, for add_advanced_parameters."""
        return QgsProcessingParameterNumber(
            self.SNAP_TOLERANCE,
            label,
            type=compat.NUMBER_DOUBLE,
            defaultValue=1.0,
            minValue=0.0,
        )

    def checkParameterValues(self, parameters, context):
        try:
            parse_tags(self.parameterAsString(parameters, self.EXTRA_TAGS, context))
        except ValueError as err:
            return False, (
                f"Other tags: \"{err}\" should look like key=value. Separate "
                "several with semicolons, e.g. lanes=2; bicycle=no"
            )
        return super().checkParameterValues(parameters, context)

    def prepareAlgorithm(self, parameters, context, feedback):
        # Runs on the main thread, before the work starts on another one.
        self._selector = None
        self._layer_name = None
        layer = self.parameterAsVectorLayer(parameters, self.CUSTOM, context)
        if layer is not None and QgsProject.instance().mapLayer(layer.id()) is not None:
            self._selector = FeatureSelector(layer.id())
            self._layer_name = layer.name()
        return True

    def ensure_engine(self, feedback):
        """Install the engine if needed. False if the user cancelled."""
        try:
            engine.ensure_installed(feedback)
        except engine.EngineCanceled:
            return False
        except engine.EngineError as err:
            raise QgsProcessingException(str(err))
        return True

    def export_custom(self, parameters, context, feedback):
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
                "The custom network layer has no features to use. If "
                "\"Selected features only\" is ticked, select some first."
            )
        feedback.pushInfo(f"Custom lines: {count}")
        return path

    def custom_args(self, parameters, context, custom_file):
        """The engine options for the custom layer and its travel type."""
        args = ["--custom", custom_file, "--id-field", ID_FIELD]
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
        if self.parameterDefinition(self.NETWORK_TYPE) is not None:
            network_type = self.parameterAsEnum(parameters, self.NETWORK_TYPE, context)
            args += ["--network-type", self._network_types[network_type]]
        return args

    @staticmethod
    def remove_old(paths):
        """Clear results of an earlier run in the same folder."""
        for path in paths:
            try:
                if path.exists():
                    os.remove(path)
            except OSError:
                raise QgsProcessingException(
                    f"Could not replace {path}. It is probably still open in "
                    "QGIS: remove the layers of the earlier run from the "
                    "project, or choose another output folder."
                )

    @staticmethod
    def count_edges(gpkg, flags=()):
        """How many rows a network's edges layer has.

        Returns (all rows, rows where each of `flags` is "yes"...), or
        None if the file can't be read. The layer's rows are counted,
        rather than using the numbers in the engine's "done" event, because
        those count a two-way street once per direction.
        """
        layer = QgsVectorLayer(f"{gpkg}|layername=edges", "edges", "ogr")
        if not layer.isValid():
            return None
        counts = [layer.featureCount()]
        for flag in flags:
            if layer.fields().indexOf(flag) < 0:  # left out when no edge has it
                counts.append(0)
                continue
            request = QgsFeatureRequest().setFilterExpression(f"\"{flag}\" = 'yes'")
            request.setNoAttributes()
            counts.append(sum(1 for _ in layer.getFeatures(request)))
        return tuple(counts)

    @staticmethod
    def load_edges(context, gpkg, name, output, style, credit=styling.OSM_CREDIT):
        """Ask QGIS to add a network's edges to the project when the tool ends."""
        source = f"{gpkg}|layername=edges"
        details = QgsProcessingContext.LayerDetails(name, context.project(), output)
        details.forceName = True
        details.setPostProcessor(styling.LayerStyler.create(output, style, credit))
        context.addLayerToLoadOnCompletion(source, details)
        return source

    def run_engine(self, args, feedback):
        """Run an engine command, showing its progress and warnings.

        Returns the engine's "done" event, or None if the user cancelled.
        Raises QgsProcessingException with the engine's explanation if it
        failed. Features named by an error (or, on success, by warnings)
        are selected in the custom layer.
        """
        done = {}
        error = {}
        warned = []

        def on_event(event):
            kind = event.get("event")
            if kind == "progress":
                feedback.setProgress(100 * (event["step"] - 1) / event["total"])
                feedback.setProgressText(event["message"])
            elif kind == "warning":
                feedback.pushWarning(event["message"])
                warned.extend(event.get("features") or [])
            elif kind == "done":
                done.update(event)
            elif kind == "error":
                error.update(event)

        try:
            code = engine.run(args, feedback, on_event)
        except engine.EngineCanceled:
            return None
        except engine.EngineError as err:
            raise QgsProcessingException(str(err))

        if error or code != 0:
            text = error_text(error, code)
            broken = [issue["feature"] for issue in error.get("issues") or []
                      if issue.get("feature") is not None]
            note = self._select(broken)
            raise QgsProcessingException(f"{text}\n{note}" if note else text)

        note = self._select(warned)
        if note:
            feedback.pushWarning(note)
        feedback.setProgress(100)
        return done

    def _select(self, feature_ids):
        """Select the features in the custom layer; returns a note for the user."""
        ids = sorted({i for i in feature_ids if isinstance(i, int)})
        if not ids or self._selector is None:
            return ""
        self._selector.select(ids)
        count = "feature concerned is" if len(ids) == 1 else f"{len(ids)} features concerned are"
        return f"The {count} now selected in \"{self._layer_name}\"."
