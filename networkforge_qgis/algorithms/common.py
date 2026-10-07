"""What the tools that hand a custom line layer to the engine share.

The form fields for the layer and its travel type, exporting the lines
to a file the engine can read, running the engine, and showing its
warnings and errors - including selecting the features they are about.
"""

import os
import re

from qgis.core import (
    QgsCoordinateTransform,
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


def turn_restrictions_help():
    """The paragraph on drawing turn restrictions, for a tool's help."""
    info = engine.bundled_info()
    field = info["turn_restriction_fields"][0]
    values = info["tag_values"][field]
    return (
        "<b>Turn restrictions</b>: to ban or force a turn at a junction, "
        "draw a short line in the same layer from the street you arrive "
        "on, through the junction, onto the street you leave on, and give "
        f"it a field called {field} with a value such as {values[0]} or "
        f"{values[-3]}. It needs no kind of street. Routers such as "
        "Valhalla obey it; it is written to the PBF file only, because "
        "the QGIS layers can't show it. "
        f"<a href=\"{engine.guide_url('turn-restrictions')}\">Guide</a>."
    )


def more_features_help(existing_streets=True):
    """The paragraph on ferries and (with OpenStreetMap) deleting tags."""
    info = engine.bundled_info()
    text = (
        "<b>Ferries</b>: a line with a field called route set to "
        f"{info['tag_values']['route'][0]}, and no kind of street, is a ferry. "
        "It joins the streets at its two ends only; a duration field "
        "(hh:mm) sets the crossing time."
    )
    if existing_streets:
        text += (
            " <b>Deleting a tag</b>: on a feature with an OpenStreetMap "
            f"id, a field called {info['remove_tags_field']} lists tags to "
            "take off the street, separated by semicolons (for example "
            "maxspeed;motor_vehicle)."
        )
    return text


POINTS_HELP = (
    "<b>Points layer</b> (optional): barriers, traffic signals and "
    "crossings. Each point needs the fields of an OpenStreetMap node, "
    "for example barrier = bollard, or highway = traffic_signals, or "
    "highway = crossing with crossing = zebra. A point on a junction "
    "tags that junction; anywhere else the street under it is cut there. "
    "Routers such as Valhalla obey them (a bollard stops cars, not "
    "walkers or bikes); QGIS's own network tools don't."
)


def error_text(error, code, describe=None):
    """What to tell the user when the engine failed.

    `error` is the engine's error event ({} if it sent none) and `code`
    its exit code. `describe` turns the id of a feature into the words
    for it ("feature 3"), where ids need explaining.
    """
    describe = describe or (lambda feature: f"feature {feature}")
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
            lines.append(f"  - {describe(issue['feature'])}: {issue['message']}")
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
    POINTS = "POINTS"

    def add_custom_parameters(self, info, label="Custom network layer",
                              lines_optional=False):
        """The layers and how their lines are travelled.

        With `lines_optional` the line layer may be left out when there is
        a points layer (signals on existing junctions need no lines).
        """
        self._presets = list(info["presets"])
        self._network_types = list(info["network_types"])
        self._lines_optional = lines_optional
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CUSTOM, label, [compat.SOURCE_VECTOR_LINE],
                optional=lines_optional,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.POINTS, "Points layer: barriers, signals, crossings",
                [compat.SOURCE_VECTOR_POINT], optional=True,
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
        if (getattr(self, "_lines_optional", False)
                and not parameters.get(self.CUSTOM) and not parameters.get(self.POINTS)):
            return False, "Choose a custom network layer, a points layer, or both."
        return super().checkParameterValues(parameters, context)

    def prepareAlgorithm(self, parameters, context, feedback):
        # Runs on the main thread, before the work starts on another one.
        self._selectors = {}
        self._point_base = None
        for role in (self.CUSTOM, self.POINTS):
            layer = self.parameterAsVectorLayer(parameters, role, context)
            if layer is not None and QgsProject.instance().mapLayer(layer.id()) is not None:
                self._selectors[role] = (FeatureSelector(layer.id()), layer.name())
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
        """Write the chosen lines and points to a temporary GeoPackage for the engine.

        The engine reads one layer, so lines and points go into it
        together. Each feature carries its QGIS id in ID_FIELD; a point's
        is raised by a round number (self._point_base) so that it can't be
        mistaken for a line's.
        """
        lines = self.parameterAsSource(parameters, self.CUSTOM, context)
        points = self.parameterAsSource(parameters, self.POINTS, context)
        if lines is None and (points is None or not self._lines_optional):
            raise QgsProcessingException(
                self.invalidSourceError(parameters, self.CUSTOM)
            )
        sources = [source for source in (lines, points) if source is not None]

        # A field called "fid" would clash with the GeoPackage's own ids.
        fields = QgsFields()
        for source in sources:
            for field in source.fields():
                if (field.name().lower() not in ("fid", ID_FIELD)
                        and fields.indexOf(field.name()) < 0):
                    fields.append(field)
        fields.append(compat.whole_number_field(ID_FIELD))

        if points is not None:
            ids_only = QgsFeatureRequest().setNoAttributes()
            ids = [feature.id() for source in sources
                   for feature in source.getFeatures(ids_only, compat.SKIP_GEOMETRY_CHECKS)]
            largest = max((abs(i) for i in ids), default=0)
            self._point_base = 10 ** max(6, len(str(largest)) + 1)

        path = QgsProcessingUtils.generateTempFilename("nf_custom.gpkg", context)
        sink, _ = QgsProcessingUtils.createFeatureSink(
            path, context, fields,
            lines.wkbType() if points is None else compat.ANY_GEOMETRY,
            sources[0].sourceCrs(),
        )
        counts = []
        for source in sources:
            is_point = source is points
            names = [field.name() for field in source.fields()]
            transform = None
            if source.sourceCrs() != sources[0].sourceCrs():
                transform = QgsCoordinateTransform(
                    source.sourceCrs(), sources[0].sourceCrs(), context.transformContext())
            count = 0
            # Geometry problems are the engine's to report, with feature ids.
            for feature in source.getFeatures(QgsFeatureRequest(), compat.SKIP_GEOMETRY_CHECKS):
                if feedback.isCanceled():
                    break
                out = QgsFeature(fields)
                geometry = feature.geometry()
                if transform is not None:
                    geometry.transform(transform)
                out.setGeometry(geometry)
                for name, value in zip(names, feature.attributes()):
                    if name != ID_FIELD and fields.indexOf(name) >= 0:
                        out[name] = value
                out[ID_FIELD] = self._export_id(feature.id(), is_point)
                if not sink.addFeature(out, QgsFeatureSink.FastInsert):
                    raise QgsProcessingException(
                        f"Could not prepare feature {feature.id()} for the engine: "
                        f"{sink.lastError()}"
                    )
                count += 1
            counts.append(count)
        del sink  # closes the file so the engine can read it
        if sum(counts) == 0:
            raise QgsProcessingException(
                "The custom network layer has no features to use. If "
                "\"Selected features only\" is ticked, select some first."
            )
        if lines is not None:
            feedback.pushInfo(f"Custom lines: {counts[0]}")
        if points is not None:
            feedback.pushInfo(f"Custom points: {counts[-1]}")
        return path

    def _export_id(self, feature_id, is_point):
        """The id a feature is given in the exported file."""
        if not is_point:
            return feature_id
        # A point not saved yet has a negative id.
        return self._point_base * (1 if feature_id >= 0 else 2) + abs(feature_id)

    def _source_of(self, export_id):
        """(layer role, QGIS feature id) of an id from the exported file."""
        base = self._point_base
        if base is None or not isinstance(export_id, int) or abs(export_id) < base:
            return self.CUSTOM, export_id
        if export_id >= 2 * base:
            return self.POINTS, -(export_id - 2 * base)
        return self.POINTS, export_id - base

    def _describe(self, export_id):
        role, feature_id = self._source_of(export_id)
        return f"point {feature_id}" if role == self.POINTS else f"feature {feature_id}"

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
                features = event.get("features") or []
                warned.extend(features)
                if any(self._source_of(f)[0] == self.POINTS for f in features):
                    feedback.pushWarning(
                        f"(Numbers from {self._point_base:,} are points: take "
                        f"{self._point_base:,} off for the point's id.)"
                    )
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
            text = error_text(error, code, self._describe)
            broken = [issue["feature"] for issue in error.get("issues") or []
                      if issue.get("feature") is not None]
            note = self._select(broken)
            raise QgsProcessingException(f"{text}\n{note}" if note else text)

        note = self._select(warned)
        if note:
            feedback.pushWarning(note)
        feedback.setProgress(100)
        return done

    @staticmethod
    def report_additions(done, feedback, file_name):
        """Say how many turn restrictions and points were made, and where they are."""
        count = done.get("turn_restrictions", 0)
        if count:
            feedback.pushInfo(
                f"Turn restrictions added: {count:,}. They are in {file_name} "
                "for routers; the QGIS layers can't show them."
            )
        count = done.get("tagged_nodes", 0)
        if count:
            feedback.pushInfo(
                f"Points put on the network: {count:,}. They are in {file_name} "
                "for routers, and in the \"nodes\" layer of the GeoPackage."
            )

    def _select(self, export_ids):
        """Select the features in their layers; returns a note for the user."""
        notes = []
        for role, noun in ((self.CUSTOM, "feature"), (self.POINTS, "point")):
            ids = sorted({feature_id for source, feature_id in map(self._source_of, export_ids)
                          if source == role and isinstance(feature_id, int)})
            if not ids or role not in self._selectors:
                continue
            selector, layer_name = self._selectors[role]
            selector.select(ids)
            count = (f"{noun} concerned is" if len(ids) == 1
                     else f"{len(ids)} {noun}s concerned are")
            notes.append(f"The {count} now selected in \"{layer_name}\".")
        return "\n".join(notes)
