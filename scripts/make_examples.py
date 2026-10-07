"""Makes the pictures in docs/examples.md (and the forms in the README).

Every picture is a real run: the networks are built with this plugin's
own tools and the real engine, and the routes drawn on them come from
Valhalla (the router the QGIS Network Analyst plugin runs), started on
this computer for each network.

    QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/make_examples.py

Needs the same things as the tests: the engine and pyvalhalla are
installed into .pytest_cache on first use, and port 8002 must be free.
The Monaco examples read a small OpenStreetMap extract, downloaded once
from Geofabrik into .pytest_cache/examples.
"""

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsLineSymbol,
    QgsMapRendererParallelJob,
    QgsMapSettings,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsProcessingFeedback,
    QgsProject,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter, QPen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CACHE = ROOT / ".pytest_cache"
WORK = CACHE / "examples"
IMAGES = ROOT / "docs" / "images"
MONACO_URL = "https://download.geofabrik.de/europe/monaco-latest.osm.pbf"
PYVALHALLA_VERSION = "3.9.0"
PORT = 8002
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")

app = QgsApplication([], True)
app.initQgis()
sys.path.append(str(Path(QgsApplication.pkgDataPath()) / "python" / "plugins"))
import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402

from networkforge_qgis import engine, styling  # noqa: E402
from networkforge_qgis.provider import NetworkForgeProvider  # noqa: E402

Processing.initialize()
PROVIDER = NetworkForgeProvider()
QgsApplication.processingRegistry().addProvider(PROVIDER)
# The engine the tests use, not the one in the QGIS profile.
engine.base_dir = lambda: CACHE / "networkforge-engine"
engine.ensure_installed()


# ------------------------------------------------------------- Valhalla

def valhalla_programs():
    venv = CACHE / "network-analyst" / f"pyvalhalla-{PYVALHALLA_VERSION}"
    python = venv / "bin" / "python"
    env = engine._clean_env()
    if not (venv / "ready").exists():
        uv = engine._ensure_uv(None)
        for cmd in ([uv, "venv", "--python", engine.ENGINE_PYTHON,
                     "--python-preference", "only-managed", venv],
                    [uv, "pip", "install", "--python", python,
                     f"pyvalhalla=={PYVALHALLA_VERSION}"]):
            subprocess.run([str(c) for c in cmd], check=True, env=env, capture_output=True)
        (venv / "ready").write_text("")
    found = subprocess.run(
        [str(python), "-c",
         "from valhalla._scripts import PYVALHALLA_BIN_DIR; print(PYVALHALLA_BIN_DIR)"],
        check=True, env=env, capture_output=True, text=True)
    return python, Path(found.stdout.strip())


def decode(shape):
    """Valhalla's route shape (a polyline with six decimals) as lon/lat points."""
    points, index, lat, lon = [], 0, 0, 0
    while index < len(shape):
        for is_lon in (False, True):
            shift = result = 0
            while True:
                byte = ord(shape[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            change = ~(result >> 1) if result & 1 else result >> 1
            if is_lon:
                lon += change
            else:
                lat += change
        points.append(QgsPointXY(lon / 1e6, lat / 1e6))
    return points


class Route:
    def __init__(self, trip):
        self.metres = trip["summary"]["length"] * 1000
        self.seconds = trip["summary"]["time"]
        self.line = QgsGeometry.fromPolylineXY(
            [p for leg in trip["legs"] for p in decode(leg["shape"])])

    def __str__(self):
        minutes, seconds = divmod(round(self.seconds), 60)
        return f"{round(self.metres, -1):,.0f} m, {minutes} min {seconds:02d} s"


@contextmanager
def valhalla(pbf, name):
    """Serve a Valhalla graph of `pbf`; yields route(costing, start, end) in lon/lat."""
    python, programs = valhalla_programs()
    env = engine._clean_env()
    folder = WORK / "graphs" / name
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "tiles").mkdir(parents=True)
    config = folder / "valhalla.json"
    subprocess.run(
        [str(python), "-c",
         "import json, sys\n"
         "from valhalla.config import get_config\n"
         "config = get_config(tile_extract='', tile_dir=sys.argv[1])\n"
         "config['mjolnir']['concurrency'] = 1\n"
         f"config['httpd']['service']['listen'] = 'tcp://127.0.0.1:{PORT}'\n"
         "json.dump(config, open(sys.argv[2], 'w'))\n",
         str(folder / "tiles"), str(config)], check=True, env=env, capture_output=True)
    subprocess.run([str(programs / "valhalla_build_tiles"), "-c", str(config), str(pbf)],
                   check=True, env=env, capture_output=True)
    with open(folder / "service.log", "w") as log:
        server = subprocess.Popen([str(programs / "valhalla_service"), str(config), "1"],
                                  env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/status", timeout=2)
                break
            except OSError:
                time.sleep(0.2)

        def route(costing, start, end):
            request = urllib.request.Request(
                f"http://127.0.0.1:{PORT}/route",
                data=json.dumps({
                    "locations": [{"lon": x, "lat": y} for x, y in (start, end)],
                    "costing": costing, "units": "km",
                }).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as reply:
                return Route(json.load(reply)["trip"])

        yield route
    finally:
        server.kill()
        server.wait()


# -------------------------------------------------------------- layers

def memory_layer(kind, crs, rows, fields=()):
    """A layer of (geometry points, *values) rows; kind is LineString or Point."""
    spec = "".join(f"&field={name}:string" for name in fields)
    layer = QgsVectorLayer(f"{kind}?crs={crs.authid()}{spec}", "layer", "memory")
    features = []
    for points, *values in rows:
        feature = QgsFeature(layer.fields())
        if isinstance(points, QgsGeometry):
            feature.setGeometry(points)
        elif kind == "Point":
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*points)))
        else:
            feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in points]))
        feature.setAttributes(values + [None] * (len(fields) - len(values)))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    QgsProject.instance().addMapLayer(layer)
    return layer


def network(source, style):
    layer = QgsVectorLayer(source, "network", "ogr")
    assert layer.isValid(), source
    style(layer)
    return layer


def lines(crs, geometries, **symbol):
    layer = memory_layer("LineString", crs, [(g,) for g in geometries])
    layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(
        {"capstyle": "round", "joinstyle": "round", **symbol})))
    return layer


def markers(crs, points, **symbol):
    layer = memory_layer("Point", crs, [(p,) for p in points])
    layer.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(symbol)))
    return layer


ROUTE = {"color": "31,119,180,200", "width": "1.3"}
STOP = {"name": "circle", "color": "#ffffff", "outline_color": "#1f2933",
        "outline_width": "0.45", "size": "3"}
BOLLARD = {"name": "square", "color": "#e6007e", "outline_color": "#ffffff",
           "outline_width": "0.4", "size": "2.8"}
TURN = {"color": "#d62728", "width": "0.9", "line_style": "solid"}


# ------------------------------------------------------------- drawing

PANEL = QSize(760, 600)
INK, MUTED, PAPER = QColor("#1f2933"), QColor("#5f6b76"), QColor("#fbfbfa")


def font(size, bold=False):
    f = QFont("DejaVu Sans")
    f.setPixelSize(size)
    f.setBold(bold)
    return f


def render(layers, extent, crs, labels=(), size=PANEL, dpi=120):
    """A map of the layers (first on top), with (x, y, text) labels drawn on it.

    A higher dpi draws every line and marker thicker.
    """
    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setDestinationCrs(crs)
    settings.setOutputSize(size)
    settings.setExtent(extent)
    settings.setBackgroundColor(PAPER)
    settings.setOutputDpi(dpi)
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    image = job.renderedImage()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(font(15, bold=True))
    to_pixel = settings.mapToPixel()
    for x, y, text in labels:
        point = to_pixel.transform(QgsPointXY(x, y))
        box = QRectF(point.x() + 9, point.y() - 26, 12 + 9 * len(text), 22)
        painter.fillRect(box, QColor(255, 255, 255, 225))
        painter.setPen(INK)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
    painter.setPen(QPen(QColor("#d9dcdf"), 2))
    painter.drawRect(1, 1, size.width() - 2, size.height() - 2)
    painter.end()
    return image


def figure(name, title, panels, caption):
    """Save panels [(heading, note, image), ...] side by side with a title."""
    gap, margin, top = 24, 24, 100
    size = panels[0][2].size()
    width = margin * 2 + size.width() * len(panels) + gap * (len(panels) - 1)
    image = QImage(width, top + size.height() + 56, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(INK)
    painter.setFont(font(24, bold=True))
    painter.drawText(margin, 40, title)
    for i, (heading, note, panel) in enumerate(panels):
        x = margin + i * (size.width() + gap)
        painter.setPen(INK)
        painter.setFont(font(18, bold=True))
        painter.drawText(x, 76, heading)
        offset = painter.fontMetrics().horizontalAdvance(heading) + 18
        painter.setPen(MUTED)
        painter.setFont(font(15))
        painter.drawText(x + offset, 76, note)
        painter.drawImage(x, top, panel)
    painter.setPen(MUTED)
    painter.setFont(font(13))
    painter.drawText(margin, top + size.height() + 36, caption)
    painter.end()
    IMAGES.mkdir(parents=True, exist_ok=True)
    image.save(str(IMAGES / f"{name}.png"))
    print("wrote", IMAGES / f"{name}.png")


class Notes(QgsProcessingFeedback):
    """Prints a tool's warnings, so a picture is never made from a bad build."""

    def pushWarning(self, warning):
        print("  WARNING:", warning)

    def reportError(self, error, fatalError=False):
        print("  ERROR:", error)


def run(tool, **parameters):
    return processing.run(f"networkforge:{tool}", parameters, feedback=Notes())


def to_lonlat(crs):
    transform = QgsCoordinateTransform(crs, WGS84, QgsProject.instance())
    return lambda point: tuple(transform.transform(QgsPointXY(*point)))


def from_lonlat(crs, geometry):
    geometry = QgsGeometry(geometry)
    geometry.transform(QgsCoordinateTransform(WGS84, crs, QgsProject.instance()))
    return geometry


# ----------------------------------------- a network of your own lines

# In metres. A WGS 84 UTM zone, so QGIS never has to ask which datum
# transformation to use when it shows the layers on a web map.
GRID_CRS = QgsCoordinateReferenceSystem("EPSG:32630")
EAST, NORTH = 451000, 5706000


def at(x, y):
    return (EAST + x, NORTH + y)


NEWTOWN = [   # points, name, highway
    ([at(0, 0), at(600, 0)], "High Street", "tertiary"),
    ([at(0, 200), at(600, 200)], "North Road", "residential"),
    ([at(0, 0), at(0, 200)], "West Lane", "residential"),
    ([at(300, -150), at(300, 200)], "Mill Lane", "residential"),
    ([at(600, 0), at(600, 200)], "East Lane", "residential"),
    ([at(0, 200), at(200, 0)], "Park Path", "footway"),
]
NEWTOWN_EXTENT = QgsRectangle(EAST - 60, NORTH - 200, EAST + 660, NORTH + 255)
NEWTOWN_PANEL = QSize(760, 480)
A, B, C = at(100, 0), at(300, 100), at(450, 0)


def newtown(name, extra=(), extra_fields=(), points=None):
    """Build Newtown, with more features or fields; returns the tool's results."""
    layer = memory_layer("LineString", GRID_CRS, [*NEWTOWN, *extra],
                         fields=("name", "highway", *extra_fields))
    return run("standalone_network", CUSTOM=layer, POINTS=points,
               OUTPUT_FOLDER=str(WORK / name))


def newtown_map(built, route=None, stops=(), extra=()):
    lonlat_route = [from_lonlat(GRID_CRS, route.line)] if route else []
    layers = [
        markers(GRID_CRS, [p for p, _ in stops], **STOP),
        *extra,
        lines(GRID_CRS, lonlat_route, **ROUTE),
        network(built["NETWORK"], styling.style_before),
    ]
    return render(layers, NEWTOWN_EXTENT, GRID_CRS, size=NEWTOWN_PANEL, dpi=190,
                  labels=[(p[0], p[1], text) for p, text in stops])


def own_network_examples():
    lonlat = to_lonlat(GRID_CRS)
    plain = newtown("newtown")
    with valhalla(plain["NETWORK_OSM"], "newtown") as route:
        drive = route("auto", lonlat(A), lonlat(B))
        walk = route("pedestrian", lonlat(at(0, 200)), lonlat(B))
        back = route("auto", lonlat(C), lonlat(A))

    drawn = lines(GRID_CRS, [QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in points])
                             for points, *_ in NEWTOWN], color="#4a5560", width="0.5")
    ends = markers(GRID_CRS, [p for points, *_ in NEWTOWN for p in (points[0], points[-1])],
                   name="circle", color="#4a5560", outline_style="no", size="1.6")
    figure(
        "example-own-network", "Six lines become a network you can route on",
        [("What you draw", "six lines with a name and a highway type",
          render([ends, drawn], NEWTOWN_EXTENT, GRID_CRS, size=NEWTOWN_PANEL, dpi=190, labels=[
              (*at(400, 0), "High Street"), (*at(400, 200), "North Road"),
              (*at(300, -100), "Mill Lane"), (*at(80, 110), "Park Path")])),
         ("The network", f"driving A to B: {drive}",
          newtown_map(plain, drive, [(A, "A"), (B, "B")]))],
        "An invented neighbourhood. Mill Lane and High Street share no vertex: "
        "they are joined where they cross.")

    rows = [(*row, "yes" if row[1] == "High Street" else None) for row in NEWTOWN]
    layer = memory_layer("LineString", GRID_CRS, rows, fields=("name", "highway", "oneway"))
    one_way = run("standalone_network", CUSTOM=layer, OUTPUT_FOLDER=str(WORK / "newtown-oneway"))
    with valhalla(one_way["NETWORK_OSM"], "newtown-oneway") as route:
        back_after = route("auto", lonlat(C), lonlat(A))
    figure(
        "example-one-way", "High Street made one-way, west to east",
        [("Two-way", f"driving C to A: {back}",
          newtown_map(plain, back, [(C, "C"), (A, "A")])),
         ("One-way eastbound", f"driving C to A: {back_after}",
          newtown_map(one_way, back_after, [(C, "C"), (A, "A")]))],
        "oneway = yes on High Street, which is drawn from west to east. "
        "Routes by Valhalla.")

    turn = [at(280, 0), at(300, 0), at(300, 20)]
    banned = newtown("newtown-turn", extra=[(turn, None, None, "no_left_turn")],
                     extra_fields=("restriction",))
    with valhalla(banned["NETWORK_OSM"], "newtown-turn") as route:
        drive_after = route("auto", lonlat(A), lonlat(B))
        walk_after = route("pedestrian", lonlat(A), lonlat(B))
    turn_line = lines(GRID_CRS, [QgsGeometry.fromPolylineXY(
        [QgsPointXY(*at(240, 0)), QgsPointXY(*at(300, 0)), QgsPointXY(*at(300, 60))])], **TURN)
    figure(
        "example-banned-turn", "No left turn from High Street into Mill Lane",
        [("Before", f"driving A to B: {drive}",
          newtown_map(plain, drive, [(A, "A"), (B, "B")])),
         ("With the turn banned", f"driving A to B: {drive_after}",
          newtown_map(banned, drive_after, [(A, "A"), (B, "B")], extra=[turn_line]))],
        "The red line is the feature: drawn through the junction, restriction = "
        f"no_left_turn (shown longer than drawn). On foot it is still {walk_after}.")

    bollard_at = at(300, 50)
    bollards = memory_layer("Point", GRID_CRS, [(bollard_at, "bollard")], fields=("barrier",))
    filtered = newtown("newtown-bollard", points=bollards)
    with valhalla(filtered["NETWORK_OSM"], "newtown-bollard") as route:
        car = route("auto", lonlat(A), lonlat(B))
        foot = route("pedestrian", lonlat(A), lonlat(B))
        bike = route("bicycle", lonlat(A), lonlat(B))
    post = markers(GRID_CRS, [bollard_at], **BOLLARD)
    figure(
        "example-bollard", "A bollard on Mill Lane: one point makes a low-traffic street",
        [("By car", f"A to B: {car}",
          newtown_map(filtered, car, [(A, "A"), (B, "B")], extra=[post])),
         ("On foot", f"A to B: {foot}",
          newtown_map(filtered, foot, [(A, "A"), (B, "B")], extra=[post]))],
        f"The pink square is a point with barrier = bollard. By bike: {bike}. "
        "Routes by Valhalla.")
    return {"drive": drive, "walk": walk, "back": back, "back_after": back_after,
            "drive_after": drive_after, "walk_after": walk_after,
            "car": car, "foot": foot, "bike": bike}


# ------------------------------------------------------- Monaco (OSM)

MONACO_BBOX = (7.4175, 43.7315, 7.4315, 43.7395)
MONACO_AREA = "{},{},{},{} [EPSG:4326]".format(
    MONACO_BBOX[0], MONACO_BBOX[2], MONACO_BBOX[1], MONACO_BBOX[3])
QUAY_NORTH, QUAY_SOUTH = (7.4255, 43.7370), (7.4255, 43.7330)   # roughly: snapped below
CLOSED_STREET = "Boulevard Albert 1er"


def monaco_extract():
    path = WORK / "monaco.osm.pbf"
    if not path.exists():
        urllib.request.urlretrieve(MONACO_URL, path)
    return str(path)


def monaco_build(name, layer):
    return run("build_network", EXTENT=MONACO_AREA, CUSTOM=layer,
               OSM_FILE=monaco_extract(), OUTPUT_FOLDER=str(WORK / name))


def on_a_path(layer, lonlat):
    """The nearest point to lon/lat on a street people may walk on, as lon/lat."""
    here = from_lonlat(layer.crs(), QgsGeometry.fromPointXY(QgsPointXY(*lonlat)))
    best = min((f.geometry() for f in layer.getFeatures() if f["walk"]),
               key=lambda geometry: geometry.distance(here))
    nearest = best.nearestPoint(here)
    nearest.transform(QgsCoordinateTransform(layer.crs(), WGS84, QgsProject.instance()))
    return tuple(nearest.asPoint())


def monaco_map(source, style, crs, route=None, stops=(), extra=(), labels=()):
    west, south, east, north = MONACO_BBOX
    extent = QgsCoordinateTransform(WGS84, crs, QgsProject.instance()).transformBoundingBox(
        QgsRectangle(west, south, east, north))
    layers = [
        markers(WGS84, [p for p, _ in stops], **STOP),
        *extra,
        lines(WGS84, [route.line] if route else [], **ROUTE),
        network(source, style),
    ]
    to_map = QgsCoordinateTransform(WGS84, crs, QgsProject.instance())
    placed = [(*to_map.transform(QgsPointXY(*p)), text) for p, text in [*stops, *labels]]
    return render(layers, extent, crs, labels=placed)


def monaco_examples():
    # A first build, only to have the existing network to work from.
    probe = memory_layer("LineString", WGS84, [([QUAY_NORTH, QUAY_SOUTH], "footway")],
                         fields=("highway",))
    existing = QgsVectorLayer(monaco_build("monaco-probe", probe)["BEFORE"], "before", "ogr")
    crs = existing.crs()

    # 1. A footbridge across the harbour, from quay to quay.
    north, south = on_a_path(existing, QUAY_NORTH), on_a_path(existing, QUAY_SOUTH)
    bridge = memory_layer("LineString", WGS84, [([north, south], "footway", "yes", "1")],
                          fields=("highway", "bridge", "layer"))
    built = monaco_build("monaco-bridge", bridge)
    start, end = (7.4270, 43.7371), (7.4240, 43.7327)
    with valhalla(built["BEFORE_OSM"], "monaco-before") as route:
        walk_before = route("pedestrian", start, end)
        # The boulevard is one-way northbound, so the trip runs south to north.
        drive_trip = ((7.4232, 43.7322), (7.4222, 43.7372))
        drive_before = route("auto", *drive_trip)
    with valhalla(built["AFTER_OSM"], "monaco-bridge") as route:
        walk_after = route("pedestrian", start, end)
    stops = [(start, "A"), (end, "B")]
    figure(
        "example-footbridge", "A footbridge across the harbour",
        [("Before", f"walking A to B: {walk_before}",
          monaco_map(built["BEFORE"], styling.style_before, crs, walk_before, stops)),
         ("After", f"walking A to B: {walk_after}",
          monaco_map(built["AFTER"], styling.style_after, crs, walk_after, stops))],
        "Monaco. Map data \u00a9 OpenStreetMap contributors (ODbL). The bridge is an "
        "invented example. Routes by Valhalla.")

    # 2. A street closed: every stretch of it is copied from the before
    # layer, with its OpenStreetMap id, and marked remove = yes.
    stretches = [f for f in existing.getFeatures() if f["name"] == CLOSED_STREET]
    closed = memory_layer("LineString", crs,
                          [(f.geometry(), str(int(f["osmid"])), "yes") for f in stretches],
                          fields=("osmid", "remove"))
    built = monaco_build("monaco-closed", closed)
    with valhalla(built["AFTER_OSM"], "monaco-closed") as route:
        drive_after = route("auto", *drive_trip)
    stops = [(drive_trip[0], "A"), (drive_trip[1], "B")]
    gone = lines(crs, [f.geometry() for f in stretches], color="#d62728", width="1.1",
                 line_style="dot")
    figure(
        "example-closed-street", f"{CLOSED_STREET} closed",
        [("Before", f"driving A to B: {drive_before}",
          monaco_map(built["BEFORE"], styling.style_before, crs, drive_before, stops)),
         ("After", f"driving A to B: {drive_after}",
          monaco_map(built["AFTER"], styling.style_after, crs, drive_after, stops,
                     extra=[gone]))],
        "Monaco. Map data \u00a9 OpenStreetMap contributors (ODbL). The closure (red dots) "
        "is an invented example. Routes by Valhalla.")
    return {"walk_before": walk_before, "walk_after": walk_after,
            "drive_before": drive_before, "drive_after": drive_after,
            "closed stretches": len(stretches)}


if __name__ == "__main__":
    only = sys.argv[1:]
    WORK.mkdir(parents=True, exist_ok=True)
    if not only or "own" in only:
        for key, value in own_network_examples().items():
            print(f"  {key}: {value}")
    if not only or "monaco" in only:
        for key, value in monaco_examples().items():
            print(f"  {key}: {value}")
