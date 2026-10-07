"""Makes the data for the hands-on checklist in manual-test/.

    QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/make_test_data.py

Writes manual-test/test-data.gpkg (ready-made layers and empty ones to
draw in), copies the Monaco extract next to it, saves a QGIS project
with everything loaded, and prints what each test in the checklist
should report, from a real run of the tools on that data.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_examples as m  # noqa: E402  (starts QGIS and the tools)
from qgis.core import (  # noqa: E402
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsLineSymbol,
    QgsPointXY,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsReferencedRectangle,
    QgsSingleSymbolRenderer,
    QgsSnappingConfig,
    QgsTolerance,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

OUT = m.ROOT / "manual-test"
GPKG = OUT / "test-data.gpkg"
SLOWER_STREET = "Rue Grimaldi"
LINE_FIELDS = ("name", "highway", "maxspeed", "oneway", "bridge", "tunnel", "layer",
               "access", "motor_vehicle", "restriction", "route", "duration",
               "osm_id", "remove", "remove_tags")
POINT_FIELDS = ("barrier", "highway", "crossing", "access", "remove_tags")


def save(layer, name):
    """Add a layer to the GeoPackage under `name`."""
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = name
    options.actionOnExistingFile = (
        QgsVectorFileWriter.CreateOrOverwriteLayer if GPKG.exists()
        else QgsVectorFileWriter.CreateOrOverwriteFile)
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(GPKG), QgsCoordinateTransformContext(), options)
    assert error[0] == QgsVectorFileWriter.NoError, error
    return name


def named_points(crs, rows):
    layer = QgsVectorLayer(f"Point?crs={crs.authid()}&field=name:string", "points", "memory")
    features = []
    for name, (x, y) in rows:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        feature.setAttributes([name])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def make_layers():
    """Write every layer; returns {name: group in the project}."""
    wgs84, grid = m.WGS84, m.GRID_CRS
    layers = {}

    # ---- Monaco, on OpenStreetMap
    west, south, east, north = m.MONACO_BBOX
    area = QgsVectorLayer("Polygon?crs=EPSG:4326&field=name:string", "area", "memory")
    feature = QgsFeature(area.fields())
    feature.setGeometry(QgsGeometry.fromRect(QgsRectangle(west, south, east, north)))
    feature.setAttributes(["Monaco harbour"])
    area.dataProvider().addFeatures([feature])
    layers[save(area, "monaco_area")] = "Monaco"

    probe = m.memory_layer("LineString", wgs84, [([m.QUAY_NORTH, m.QUAY_SOUTH], "footway")],
                           fields=("highway",))
    existing = QgsVectorLayer(m.monaco_build("monaco-probe", probe)["BEFORE"], "before", "ogr")
    ends = [m.on_a_path(existing, m.QUAY_NORTH), m.on_a_path(existing, m.QUAY_SOUTH)]
    layers[save(m.memory_layer(
        "LineString", wgs84, [(ends, "Harbour footbridge", "footway", "yes", "1")],
        fields=("name", "highway", "bridge", "layer")), "monaco_footbridge")] = "Monaco"

    def stretches(street, **values):
        rows = [(f.geometry(), str(int(f["osmid"])), *values.values())
                for f in existing.getFeatures() if f["name"] == street]
        return m.memory_layer("LineString", existing.crs(), rows, fields=("osmid", *values))

    layers[save(stretches(m.CLOSED_STREET, remove="yes"), "monaco_closed_street")] = "Monaco"
    layers[save(stretches(SLOWER_STREET, maxspeed="20"), "monaco_slower_street")] = "Monaco"
    layers[save(named_points(wgs84, [
        ("walk A", (7.4270, 43.7371)), ("walk B", (7.4240, 43.7327)),
        ("drive A", (7.4232, 43.7322)), ("drive B", (7.4222, 43.7372)),
    ]), "monaco_trips")] = "Monaco"
    layers[save(m.memory_layer("LineString", wgs84, [
        ([(7.4200, 43.7350), (7.4210, 43.7350)], "good", "footway", "20"),
        ([(7.4200, 43.7352), (7.4210, 43.7352)], "bad speed", "residential", "fast"),
        ([(7.4200, 43.7354), (7.4210, 43.7354)], "no highway", None, None),
    ], fields=("name", "highway", "maxspeed")), "broken_lines")] = "Monaco"

    # ---- Newtown, an invented neighbourhood without OpenStreetMap
    at = m.at
    turn = ([at(280, 0), at(300, 0), at(300, 20)], "no left turn", None, "no_left_turn")
    track = ([at(605, 100), at(700, 100)], "Farm Track", "track")
    layers[save(m.memory_layer("LineString", grid, m.NEWTOWN, fields=("name", "highway")),
                "newtown_streets")] = "Newtown"
    layers[save(m.memory_layer("LineString", grid, [*m.NEWTOWN, turn],
                               fields=("name", "highway", "restriction")),
                "newtown_streets_and_turn")] = "Newtown"
    layers[save(m.memory_layer("LineString", grid, [*m.NEWTOWN, track],
                               fields=("name", "highway")),
                "newtown_streets_with_gap")] = "Newtown"
    layers[save(m.memory_layer("Point", grid, [(at(300, 50), "bollard")], fields=("barrier",)),
                "newtown_bollard")] = "Newtown"
    layers[save(named_points(grid, [("A", m.A), ("B", m.B), ("C", m.C)]),
                "newtown_trips")] = "Newtown"

    # ---- empty layers to draw in
    layers[save(m.memory_layer("LineString", wgs84, [], fields=LINE_FIELDS),
                "my_lines")] = "Draw your own"
    layers[save(m.memory_layer("Point", wgs84, [], fields=POINT_FIELDS),
                "my_points")] = "Draw your own"
    return layers


def make_project(layers):
    """A QGIS project with the layers in groups, a street map and snapping on."""
    project = QgsProject.instance()
    project.clear()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    root = project.layerTreeRoot()
    groups = {}
    for name, group in layers.items():
        layer = QgsVectorLayer(f"{GPKG}|layername={name}", name, "ogr")
        assert layer.isValid(), name
        project.addMapLayer(layer, False)
        if group not in groups:
            groups[group] = root.addGroup(group)
        node = groups[group].addLayer(layer)
        node.setItemVisibilityChecked(name in ("monaco_area", "monaco_footbridge",
                                               "monaco_trips"))
        if name == "monaco_area":
            # An outline only, so the map behind it stays visible.
            layer.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
                {"style": "no", "outline_color": "#d62728", "outline_width": "0.6"})))
            view = QgsCoordinateTransform(layer.crs(), project.crs(), project) \
                .transformBoundingBox(layer.extent())
            view.scale(1.15)
            project.viewSettings().setDefaultViewExtent(
                QgsReferencedRectangle(view, project.crs()))
        elif name == "monaco_footbridge":
            layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(
                {"color": "#e6007e", "width": "0.9"})))
    basemap = QgsRasterLayer(
        "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0",
        "OpenStreetMap (background)", "wms")
    if basemap.isValid():
        project.addMapLayer(basemap, False)
        root.addLayer(basemap)
    snapping = QgsSnappingConfig(project)
    snapping.setEnabled(True)
    snapping.setMode(QgsSnappingConfig.AllLayers)
    try:
        snapping.setTypeFlag(QgsSnappingConfig.VertexFlag | QgsSnappingConfig.SegmentFlag)
    except (AttributeError, TypeError):
        pass
    snapping.setTolerance(12)
    snapping.setUnits(QgsTolerance.Pixels)
    project.setSnappingConfig(snapping)
    assert project.write(str(OUT / "manual-test.qgz"))
    assert all(isinstance(g, QgsLayerTreeGroup) for g in groups.values())


class Log(QgsProcessingFeedback):
    def __init__(self):
        super().__init__()
        self.lines = []

    def pushInfo(self, info):
        self.lines.append(info)

    def pushWarning(self, warning):
        self.lines.append("WARNING: " + warning)


def expect(title, tool, **parameters):
    """Run a tool on the test data and print what its log says."""
    import processing

    log = Log()
    for key, value in parameters.items():
        if isinstance(value, str) and value.startswith("layer:"):
            parameters[key] = f"{GPKG}|layername={value[6:]}"
    print(f"\n== {title}")
    try:
        processing.run(f"networkforge:{tool}", parameters, feedback=log)
    except Exception as error:  # noqa: BLE001 - the message is the expected result
        print("  STOPS WITH:", str(error).replace("\n", "\n    "))
    keep = ("After network", "Network:", "Street segments", "Turn restrictions", "Points put",
            "No problems", "usable by", "WARNING", "Custom ", "change existing", "point(s)",
            "turn restriction(s)")
    for line in log.lines:
        if line.strip().startswith(keep):
            print("  " + line)


def expectations():
    osm, area = str(OUT / "monaco.osm.pbf"), m.MONACO_AREA
    out = str(m.WORK / "manual")
    expect("check: footbridge", "check_layer", CUSTOM="layer:monaco_footbridge")
    expect("check: broken lines", "check_layer", CUSTOM="layer:broken_lines")
    for layer in ("monaco_footbridge", "monaco_closed_street", "monaco_slower_street"):
        expect(f"build: {layer}", "build_network", EXTENT=area, CUSTOM=f"layer:{layer}",
               OSM_FILE=osm, OUTPUT_FOLDER=out)
    expect("standalone: streets", "standalone_network", CUSTOM="layer:newtown_streets",
           OUTPUT_FOLDER=out)
    expect("standalone: turn and bollard", "standalone_network",
           CUSTOM="layer:newtown_streets_and_turn", POINTS="layer:newtown_bollard",
           OUTPUT_FOLDER=out)
    expect("standalone: gap, snap 1 m", "standalone_network",
           CUSTOM="layer:newtown_streets_with_gap", OUTPUT_FOLDER=out)
    expect("standalone: gap, snap 10 m", "standalone_network",
           CUSTOM="layer:newtown_streets_with_gap", SNAP_TOLERANCE=10, OUTPUT_FOLDER=out)
    expect("standalone: vertices only", "standalone_network", CUSTOM="layer:newtown_streets",
           JOIN_AT=1, OUTPUT_FOLDER=out)
    expect("standalone: preset over everything", "standalone_network",
           CUSTOM="layer:newtown_streets", OVERWRITE=True, OUTPUT_FOLDER=out,
           PRESET=list(m.engine.bundled_info()["presets"]).index("residential_street") + 1)
    network = QgsVectorLayer(f"{out}/network.gpkg|layername=edges", "network", "ogr")
    print("  highway values:", sorted({f["highway"] for f in network.getFeatures()}))


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    GPKG.unlink(missing_ok=True)
    shutil.copy(m.monaco_extract(), OUT / "monaco.osm.pbf")
    made = make_layers()
    make_project(made)
    print("wrote", GPKG, "with", ", ".join(made))
    expectations()
