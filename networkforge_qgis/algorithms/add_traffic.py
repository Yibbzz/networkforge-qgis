""""Add traffic": time-of-day speeds for Valhalla on a network NetworkForge built.

Hands the network's PBF, the time bands (a table in the form) and an
optional layer of single streets to the engine's `traffic` command,
which writes Valhalla's graph with the speeds as a .tar file: the
Network Analyst plugin loads it with "From Tar". All the work happens in
the engine.
"""

import json
from pathlib import Path

from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsFields,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterMatrix,
    QgsProcessingUtils,
)

from .. import compat, engine
from .common import ID_FIELD, CustomNetworkAlgorithm

BAND_COLUMNS = ["Name", "Days", "Time", "Roads", "Factor"]
# An example to start from, not data: the help says so.
EXAMPLE_BANDS = [
    "Morning peak", "Mo-Fr", "07:00-09:30", "motorway, trunk, primary, secondary", "0.6",
    "Evening peak", "Mo-Fr", "16:00-18:30", "motorway, trunk, primary, secondary", "0.6",
]


def bands_from_table(cells):
    """The form's table (a flat list, row after row) as the engine's band settings."""
    cells = ["" if cell is None else str(cell).strip() for cell in cells or []]
    width = len(BAND_COLUMNS)
    bands = []
    for i in range(0, len(cells) - len(cells) % width, width):
        name, days, time, roads, factor = cells[i : i + width]
        if not any((name, days, time, roads, factor)):
            continue  # an empty row left in the table
        band = {"time": time, "roads": [r.strip() for r in roads.replace(";", ",").split(",")
                                        if r.strip()] or roads}
        if name:
            band["name"] = name
        if days:
            band["days"] = days
        try:
            band["factor"] = float(factor.replace(",", "."))
        except ValueError:
            band["factor"] = factor  # the engine explains what is wrong with it
        bands.append(band)
    return bands


class AddTrafficAlgorithm(CustomNetworkAlgorithm):
    NETWORK_FILE = "NETWORK_FILE"
    BANDS = "BANDS"
    # The street layer takes the custom layer's role, so the engine's
    # warnings select its features.
    CUSTOM = "STREETS"
    OUTPUT = "OUTPUT"

    def name(self):
        return "add_traffic"

    def displayName(self):
        return "Add traffic (time of day)"

    def shortHelpString(self):
        info = engine.bundled_info()["traffic"]
        low, high = info["factor_range"]
        return (
            "Makes streets slower at busy times, for routing with "
            "<b>Valhalla</b>: \"main roads at 60% of their normal speed on "
            "weekday mornings\". A route asked for at Monday 08:00 then "
            "allows for the slower roads and may go another way; the same "
            "route at night or on a Sunday doesn't change. These are your "
            "assumptions, not measured traffic: say so in your results.\n\n"
            "<b>Network</b>: an OSM PBF file this plugin made "
            "(after.osm.pbf, before.osm.pbf or network.osm.pbf). Run the "
            "tool on before and after with the same settings, so both have "
            "the same traffic.\n\n"
            "<b>Time bands by road class</b>: one row per band. Days like "
            "Mo-Fr or Sa,Su; time like 07:00-09:30 (5-minute steps; "
            "22:00-02:00 runs past midnight); roads are kinds of street "
            "(motorway, trunk, primary, secondary, tertiary, residential "
            "... each includes its slip roads; \"all\" for every street); "
            f"factor is the share of the normal speed ({low} to {high}: 0.6 "
            "is 60%). Where bands overlap, the slower wins. The rows filled "
            "in are an example: change them, or delete them to use single "
            "streets only.\n\n"
            "<b>Single streets</b> (optional): a line layer, one row per "
            "street and time band, with fields days, time, factor and "
            "optionally direction (both, or forward: only the way the line "
            "is drawn). Lines are matched onto the streets they run along; "
            "copying a street from the Before or After layer gets it "
            "exactly. A street with rows of its own ignores the road-class "
            "bands. Lines that match no street are selected and named in "
            "a warning.\n\n"
            "<b>Result</b>: a .tar file, Valhalla's routing graph with the "
            "speeds. In the Network Analyst plugin: Graphs > From Tar, start "
            "its server on that graph, then in the routing panel tick the "
            "time box and choose Depart and a time. Routes without a time "
            "(and that plugin's Processing tools, which send none) see the "
            "normal network. QGIS's own network tools and the GeoPackage "
            "layers don't show traffic.\n\n"
            "The first run installs Valhalla for the engine (about 100 MB).\n\n"
            f"<a href=\"{engine.guide_url('traffic.md')}\">Guide</a>."
        )

    def createInstance(self):
        return AddTrafficAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.NETWORK_FILE,
                "Network (OSM PBF made by NetworkForge)",
                fileFilter="OSM PBF (*.osm.pbf *.pbf)",
            )
        )
        self.addParameter(
            QgsProcessingParameterMatrix(
                self.BANDS,
                "Time bands by road class",
                hasFixedNumberRows=False,
                headers=BAND_COLUMNS,
                defaultValue=EXAMPLE_BANDS,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CUSTOM,
                "Single streets: lines with days, time, factor (optional)",
                [compat.SOURCE_VECTOR_LINE],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                "Network with traffic for Valhalla",
                fileFilter="Valhalla graph (*.tar)",
            )
        )
        self.addOutput(QgsProcessingOutputFile("TAR", "Valhalla graph with traffic"))

    def checkParameterValues(self, parameters, context):
        bands = bands_from_table(self.parameterAsMatrix(parameters, self.BANDS, context))
        if not bands and not parameters.get(self.CUSTOM):
            return False, "Fill in at least one time band, or choose a single-streets layer."
        return super().checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        if not self.ensure_engine(feedback):
            return {}
        try:
            engine.ensure_traffic(feedback)
        except engine.EngineError as err:
            raise QgsProcessingException(str(err))

        network = Path(self.parameterAsFile(parameters, self.NETWORK_FILE, context))
        out = Path(self.parameterAsFileOutput(parameters, self.OUTPUT, context))
        if out.suffix.lower() != ".tar":
            out = out.with_suffix(".tar")
        self.remove_old([out])

        args = ["traffic", "--json", "--pbf", network, "--out", out]
        bands = bands_from_table(self.parameterAsMatrix(parameters, self.BANDS, context))
        if bands:
            settings = QgsProcessingUtils.generateTempFilename("nf_traffic.json", context)
            Path(settings).write_text(json.dumps({"band": bands}), encoding="utf-8")
            args += ["--settings", settings]
            feedback.pushInfo(f"Time bands: {len(bands)}")
        if self.parameterAsSource(parameters, self.CUSTOM, context) is not None:
            args += ["--streets", self.export_streets(parameters, context, feedback),
                     "--id-field", ID_FIELD]

        done = self.run_engine(args, feedback)
        if done is None:
            return {}

        roads = ", ".join(f"{count:,} {road}" for road, count in
                          (done.get("by_road") or {}).items())
        feedback.pushInfo(f"Streets with traffic: {done.get('streets', 0):,} "
                          f"({done.get('segments', 0):,} road segments).")
        if roads:
            feedback.pushInfo(f"By road class: {roads}.")
        if done.get("single_streets"):
            feedback.pushInfo(f"Single streets: {done['single_streets']:,} "
                              f"({done.get('single_segments', 0):,} road segments).")
        feedback.pushInfo(
            f"Done: {out}\nIn the Network Analyst plugin: Graphs > From Tar, then route "
            "with a departure time (the time box in its routing panel)."
        )
        return {self.OUTPUT: str(out), "TAR": str(out)}

    def export_streets(self, parameters, context, feedback):
        """Write the single streets to a temporary GeoPackage, with their QGIS ids."""
        source = self.parameterAsSource(parameters, self.CUSTOM, context)
        fields = QgsFields()
        for field in source.fields():
            if field.name().lower() not in ("fid", ID_FIELD):
                fields.append(field)
        fields.append(compat.whole_number_field(ID_FIELD))
        path = QgsProcessingUtils.generateTempFilename("nf_streets.gpkg", context)
        sink, _ = QgsProcessingUtils.createFeatureSink(
            path, context, fields, source.wkbType(), source.sourceCrs())
        names = [field.name() for field in source.fields()]
        count = 0
        for feature in source.getFeatures(QgsFeatureRequest(), compat.SKIP_GEOMETRY_CHECKS):
            if feedback.isCanceled():
                break
            out = QgsFeature(fields)
            out.setGeometry(feature.geometry())
            for name, value in zip(names, feature.attributes()):
                if fields.indexOf(name) >= 0 and name != ID_FIELD:
                    out[name] = value
            out[ID_FIELD] = feature.id()
            if not sink.addFeature(out, QgsFeatureSink.Flag.FastInsert):
                raise QgsProcessingException(
                    f"Could not prepare street {feature.id()} for the engine: "
                    f"{sink.lastError()}")
            count += 1
        del sink  # closes the file so the engine can read it
        if count == 0:
            raise QgsProcessingException(
                "The single-streets layer has no features to use. If \"Selected "
                "features only\" is ticked, select some first.")
        feedback.pushInfo(f"Single streets: {count}")
        return path
