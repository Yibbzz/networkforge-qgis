"""NetworkForge's PBF files in routing.earth's QGIS Network Analyst plugin.

The two plugins are meant to be used together: NetworkForge writes the
network as OSM PBF, the Network Analyst plugin routes on it with
Valhalla. These tests do that end to end, without a screen:

1. build the networks with NetworkForge's own tools (real engine);
2. build a Valhalla graph from each PBF and start Valhalla on this
   computer, with the same programs (from the `pyvalhalla` package) that
   the Network Analyst plugin runs from its settings panel - that panel
   itself can't be clicked from a test;
3. run the Network Analyst plugin's own Processing tools against it and
   compare the results.

Marked "network_analyst". The first run downloads the Network Analyst
plugin and pyvalhalla (about 100 MB) into .pytest_cache; nothing is
installed into QGIS. Port 8002 must be free: it is where the plugin
looks for a Valhalla on this computer.

    pytest -m network_analyst          only these
    pytest -m "not network_analyst"    everything else

Which versions: by default the commits and the pyvalhalla version pinned
below, so that a push here is never broken by a change over there. QGIS 3
gets the plugin's `qgis-v3` branch (its 6.x releases), QGIS 4 its
`master` branch (7.x). With the environment variable
NF_NETWORK_ANALYST=latest the newest commit of that branch and the newest
pyvalhalla are used instead, which is what a user installing today gets;
a scheduled GitHub workflow runs that every week.
"""

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from qgis import processing
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsDistanceArea,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

from networkforge_qgis import engine

pytestmark = pytest.mark.network_analyst

PLUGIN_REPO = "https://github.com/routing-earth/network-analyst-qgis-plugin"
# One commit per QGIS major version: (branch it is on, commit).
PLUGIN_COMMITS = {
    3: ("qgis-v3", "389ecda384d10c5273eb8b39de73c62fa1825afe"),  # 6.1.0
    4: ("master", "4978c30e8ef6e4c209f27eef67bf651672c8815c"),  # 7.1.0
}
# The plugin's bundled copy of routingpy (a git submodule, so it is not
# in the plugin's zip).
ROUTINGPY_REPO = "https://github.com/mthh/routingpy"
ROUTINGPY_COMMIT = "8e2758b2ccb76dec5bd55a7eb96bfd8510dfae44"
# The version the engine's own Valhalla tests are written against.
PYVALHALLA_VERSION = "3.9.0"
# Where the plugin's preconfigured "localhost" server is expected.
PORT = 8002
# Newest plugin and pyvalhalla instead of the pinned ones (see above).
LATEST = os.environ.get("NF_NETWORK_ANALYST", "").lower() == "latest"

CACHE = Path(__file__).parent.parent / ".pytest_cache" / "network-analyst"
GRID = Path(__file__).parent / "data" / "grid.osm"
EXTENT = "-3.701,-3.695,40.399,40.404 [EPSG:4326]"

# The test grid: four rows and four columns of two-way residential
# streets, 30 km/h, in blocks of about 100 m. Row 0 is OSM way 1001, drawn
# from west to east.
ROW_0 = 1001
WEST, EAST = (-3.7000, 40.4000), (-3.6964, 40.4000)   # the two ends of row 0
FAR_CORNER = (-3.6964, 40.4027)                        # diagonally opposite WEST
ALONG_ROW_0 = [WEST, EAST]
MIDDLE_BLOCK = [(-3.6988, 40.4000), (-3.6976, 40.4000)]   # of row 0, west to east
DIAGONAL = [WEST, FAR_CORNER]
# Trips along row 0 start and end half-way along its first and last
# block, not on a corner: Valhalla is unpredictable about a trip that
# starts exactly on a junction. Through the middle block is about 204 m;
# round by row 1 about 404 m.
A, B = (-3.6994, 40.4000), (-3.6970, 40.4000)
DIRECT, DETOUR = (195, 215), (390, 420)

# A network of the user's own lines: a street, a street that crosses it
# half-way, and a street that links the two ends round the block.
#
#          TOP +---------+
#              |         |
#   START -----X---------+ END
#              |
STREET = [(-3.7000, 40.4000), (-3.6960, 40.4000)]
CROSSING = [(-3.6980, 40.3990), (-3.6980, 40.4010)]
ROUND_THE_BLOCK = [(-3.6960, 40.4000), (-3.6960, 40.4010), (-3.6980, 40.4010)]
START, TOP = STREET[0], CROSSING[1]
# Left at the crossing, drawn from the street onto the crossing street.
LEFT_AT_CROSSING = [(-3.6984, 40.4000), (-3.6980, 40.4000), (-3.6980, 40.4004)]
# START to TOP: left at X is about 281 m; on to END and round, about 621 m.
VIA_CROSSING, VIA_BLOCK = (265, 295), (600, 640)


# ----------------------------------------------------------------- set-up

def _download_zip(url, target):
    """Unpack a GitHub zip of one commit into `target` (without its top folder)."""
    with urllib.request.urlopen(url, timeout=120) as reply:
        archive = zipfile.ZipFile(io.BytesIO(reply.read()))
    target.mkdir(parents=True, exist_ok=True)
    for member in archive.infolist():
        inner = member.filename.split("/", 1)[1]
        if not inner or member.is_dir():
            continue
        path = target / inner
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(archive.read(member))


def _submodule_commit(branch):
    """The routingpy commit the plugin's branch bundles (pinned one if unknown)."""
    url = ("https://api.github.com/repos/routing-earth/network-analyst-qgis-plugin/"
           f"contents/valhalla/third_party/routingpy?ref={branch}")
    try:
        with urllib.request.urlopen(url, timeout=30) as reply:
            return json.load(reply)["sha"]
    except (OSError, ValueError, KeyError):
        return ROUTINGPY_COMMIT


@pytest.fixture(scope="session")
def network_analyst(qgis_processing):
    """The Network Analyst plugin's Processing tools."""
    major = Qgis.QGIS_VERSION_INT // 10000
    branch, commit = PLUGIN_COMMITS[major]
    if LATEST:
        folder = CACHE / f"plugin-latest-{branch}"
        shutil.rmtree(folder, ignore_errors=True)
        _download_zip(f"{PLUGIN_REPO}/archive/refs/heads/{branch}.zip", folder)
        _download_zip(f"{ROUTINGPY_REPO}/archive/{_submodule_commit(branch)}.zip",
                      folder / "valhalla" / "third_party" / "routingpy")
    else:
        folder = CACHE / f"plugin-{commit[:10]}"
        if not (folder / "ready").exists():
            shutil.rmtree(folder, ignore_errors=True)
            _download_zip(f"{PLUGIN_REPO}/archive/{commit}.zip", folder)
            _download_zip(f"{ROUTINGPY_REPO}/archive/{ROUTINGPY_COMMIT}.zip",
                          folder / "valhalla" / "third_party" / "routingpy")
            (folder / "ready").write_text(branch)
    version = next((line.split("=", 1)[1] for line in
                    (folder / "valhalla" / "metadata.txt").read_text().splitlines()
                    if line.startswith("version=")), "?")
    print(f"\nNetwork Analyst plugin {version} ({branch}"
          f"{', newest commit' if LATEST else ' at ' + commit[:10]})")

    # The plugin's package is called "valhalla", as it is when QGIS loads it.
    sys.path.insert(0, str(folder))
    try:
        from valhalla.processing.provider import ValhallaProvider
    finally:
        sys.path.remove(str(folder))
    provider = ValhallaProvider()
    registry = QgsApplication.processingRegistry()
    registry.addProvider(provider)
    yield provider
    registry.removeProvider(provider)


@pytest.fixture(scope="session")
def valhalla_programs():
    """pyvalhalla in its own environment: (its Python, its folder of programs)."""
    wanted = "pyvalhalla" if LATEST else f"pyvalhalla=={PYVALHALLA_VERSION}"
    venv = CACHE / ("pyvalhalla-latest" if LATEST else f"pyvalhalla-{PYVALHALLA_VERSION}")
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    env = engine._clean_env()
    if LATEST or not (venv / "ready").exists():
        uv = engine._ensure_uv(None)
        for cmd in (
            [uv, "venv", "--python", engine.ENGINE_PYTHON,
             "--python-preference", "only-managed", venv],
            [uv, "pip", "install", "--python", python, wanted],
        ):
            subprocess.run([str(c) for c in cmd], check=True, env=env, capture_output=True)
        (venv / "ready").write_text("")
    found = subprocess.run(
        [str(python), "-c",
         "from valhalla._scripts import PYVALHALLA_BIN_DIR; print(PYVALHALLA_BIN_DIR)"],
        check=True, env=env, capture_output=True, text=True,
    )
    return python, Path(found.stdout.strip())


@contextmanager
def valhalla_serving(pbf, folder, programs):
    """Build a Valhalla graph from an OSM file and serve it on localhost."""
    python, programs_dir = programs
    env = engine._clean_env()
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            pytest.fail(f"Port {PORT} is in use: stop the Valhalla (or other "
                        "program) running there and try again.")

    (folder / "tiles").mkdir(parents=True, exist_ok=True)
    config = folder / "valhalla.json"
    subprocess.run(
        [str(python), "-c",
         "import json, sys\n"
         "from valhalla.config import get_config\n"
         "config = get_config(tile_extract='', tile_dir=sys.argv[1])\n"
         "config['mjolnir']['concurrency'] = 1\n"
         f"config['httpd']['service']['listen'] = 'tcp://127.0.0.1:{PORT}'\n"
         "json.dump(config, open(sys.argv[2], 'w'))\n",
         str(folder / "tiles"), str(config)],
        check=True, env=env, capture_output=True,
    )
    build = subprocess.run(
        [str(programs_dir / "valhalla_build_tiles"), "-c", str(config), str(pbf)],
        env=env, capture_output=True, text=True,
    )
    assert build.returncode == 0 and any((folder / "tiles").rglob("*.gph")), (
        f"Valhalla could not build a graph from {pbf}:\n"
        f"{build.stdout[-2000:]}\n{build.stderr[-2000:]}"
    )

    with open(folder / "valhalla_service.log", "w") as log:
        server = subprocess.Popen(
            [str(programs_dir / "valhalla_service"), str(config), "1"],
            env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/status", timeout=2)
                    break
                except OSError:
                    assert server.poll() is None and time.monotonic() < deadline, (
                        f"Valhalla did not start; see {folder / 'valhalla_service.log'}")
                    time.sleep(0.2)
            yield
        finally:
            # Killed, not asked to stop: Valhalla takes several seconds
            # to wind down, and nothing here needs it to.
            server.kill()
            server.wait()


# ---------------------------------------------------------------- helpers

def line_layer(*lines, fields=("highway",)):
    """A project layer of (points, *values of `fields`) lines."""
    spec = "".join(f"&field={name}:string" for name in fields)
    layer = QgsVectorLayer(f"LineString?crs=EPSG:4326{spec}", "plan", "memory")
    features = []
    for points, *values in lines:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points]))
        feature.setAttributes(values + [None] * (len(fields) - len(values)))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    QgsProject.instance().addMapLayer(layer)
    return layer


def point_layer(*points):
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "stops", "memory")
    features = []
    for x, y in points:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def run_tool(name, feedback, **parameters):
    """Run a Network Analyst tool against the server on localhost."""
    tool = f"valhalla:{name}"
    algorithm = QgsApplication.processingRegistry().createAlgorithmById(tool)
    assert algorithm is not None, f"The Network Analyst plugin has no tool {tool}"
    # The plugin's defaults for its drop-down settings are the choices'
    # names, which QGIS refuses when a tool is run from Python ("Incorrect
    # parameter value for INPUT_MODE"): give each default by its position.
    defaults = {}
    for definition in algorithm.parameterDefinitions():
        if definition.type() != "enum":
            continue
        default = definition.defaultValue()
        names = [str(option) for option in definition.options()]
        wanted = str(getattr(default, "value", default))
        defaults[definition.name()] = names.index(wanted) if wanted in names else 0
    servers = algorithm.parameterDefinition("INPUT_PROVIDER").options()
    defaults["INPUT_PROVIDER"] = servers.index("localhost")
    results = processing.run(tool, {
        **defaults, "OUTPUT": "TEMPORARY_OUTPUT", **parameters,
    }, feedback=feedback)
    return list(results["OUTPUT"].getFeatures())


class Route:
    """A route from the Network Analyst plugin: its length and travel time."""

    def __init__(self, feature):
        measure = QgsDistanceArea()
        measure.setSourceCrs(QgsCoordinateReferenceSystem("EPSG:4326"),
                             QgsProject.instance().transformContext())
        measure.setEllipsoid("WGS84")
        self.metres = measure.measureLength(feature.geometry())
        self.seconds = feature["duration"]

    def __repr__(self):
        return f"Route({self.metres:.0f} m, {self.seconds} s)"


def route(profile, start, end, feedback):
    """The Network Analyst plugin's route between two points (profile: auto, ...)."""
    routes = run_tool(f"valhalla_directions_{profile}", feedback,
                      INPUT_LAYER_1=point_layer(start, end))
    assert len(routes) == 1
    return Route(routes[0])


def between(route, limits):
    low, high = limits
    return low < route.metres < high


@pytest.fixture
def scenario(provider, real_engine, network_analyst, valhalla_programs, feedback,
             tmp_path, qgis_new_project):
    """Builds networks with NetworkForge and routes on them with Network Analyst.

    scenario.build(layer) and scenario.standalone(layer) return the
    tools' results; `with scenario.valhalla(pbf):` serves that file, and
    scenario.route(profile, start, end) asks the Network Analyst plugin.
    """

    class Scenario:
        feedback_ = feedback
        _graphs = 0

        def build(self, layer):
            return processing.run("networkforge:build_network", {
                "EXTENT": EXTENT, "CUSTOM": layer, "OSM_FILE": str(GRID),
                "OUTPUT_FOLDER": str(tmp_path / "out"),
            }, feedback=feedback)

        def standalone(self, layer, **parameters):
            return processing.run("networkforge:standalone_network", {
                "CUSTOM": layer, "OUTPUT_FOLDER": str(tmp_path / "out"), **parameters,
            }, feedback=feedback)

        def valhalla(self, pbf):
            Scenario._graphs += 1
            return valhalla_serving(pbf, tmp_path / f"graph{Scenario._graphs}",
                                    valhalla_programs)

        def route(self, profile, start, end):
            return route(profile, start, end, feedback)

        def before_and_after(self, built, *trips):
            """Each (profile, start, end) trip on the before and the after network."""
            results = []
            for network in ("BEFORE_OSM", "AFTER_OSM"):
                with self.valhalla(built[network]):
                    results.append([self.route(*trip) for trip in trips])
            return list(zip(*results))  # [(before, after), ...] per trip

    return Scenario()


# ----------------------------------------------- adding to OpenStreetMap

def test_a_new_cycleway_shortens_the_cycling_route_only(scenario):
    built = scenario.build(line_layer((DIAGONAL, "cycleway")))

    cycling, driving = scenario.before_and_after(
        built, ("bicycle", WEST, FAR_CORNER), ("auto", WEST, FAR_CORNER))

    # Round the blocks is about 606 m, straight across about 429 m.
    assert 580 < cycling[0].metres < 630
    assert 410 < cycling[1].metres < 450
    # Cars may not use a cycleway: their route stays the same.
    assert 580 < driving[0].metres < 630
    assert driving[1].metres == pytest.approx(driving[0].metres, abs=1)


def test_a_new_road_is_used_by_cars_too(scenario):
    built = scenario.build(line_layer((DIAGONAL, "tertiary")))

    (before, after), = scenario.before_and_after(built, ("auto", WEST, FAR_CORNER))

    assert 580 < before.metres < 630
    assert 410 < after.metres < 450
    assert after.seconds < before.seconds


def test_isochrones_run_on_the_after_network(scenario, feedback):
    built = scenario.build(line_layer((DIAGONAL, "cycleway")))

    with scenario.valhalla(built["AFTER_OSM"]):
        reach = run_tool("valhalla_isochrones_pedestrian", feedback,
                         INPUT_LAYER_1=point_layer(WEST), INPUT_INTERVALS="120",
                         INPUT_DENOISE=1, INPUT_GENERALIZE=0)

    assert len(reach) == 1
    polygon = reach[0].geometry()
    assert not polygon.isEmpty()
    # Two minutes on foot is well inside the grid, and starts at the corner.
    assert polygon.boundingBox().width() < 0.0036
    assert polygon.distance(QgsGeometry.fromPointXY(QgsPointXY(*WEST))) < 0.0002


# ------------------------------------------- changing existing streets

def edit_layer(points=MIDDLE_BLOCK, **tags):
    """A layer with one feature that changes a stretch of row 0 of the grid."""
    return line_layer((points, str(ROW_0), *tags.values()), fields=("osm_id", *tags))


def test_a_removed_street_sends_everyone_round(scenario):
    built = scenario.build(edit_layer(remove="yes"))

    driving, walking = scenario.before_and_after(
        built, ("auto", A, B), ("pedestrian", A, B))

    for before, after in (driving, walking):
        assert between(before, DIRECT)
        assert between(after, DETOUR)


def test_a_street_closed_to_motor_traffic_still_takes_bikes_and_walkers(scenario):
    built = scenario.build(edit_layer(motor_vehicle="no"))

    driving, cycling, walking = scenario.before_and_after(
        built, ("auto", A, B), ("bicycle", A, B), ("pedestrian", A, B))

    assert between(driving[0], DIRECT) and between(driving[1], DETOUR)
    for before, after in (cycling, walking):
        assert between(before, DIRECT) and between(after, DIRECT)


def test_a_street_closed_to_everyone(scenario):
    built = scenario.build(edit_layer(access="no"))

    driving, walking = scenario.before_and_after(
        built, ("auto", A, B), ("pedestrian", A, B))

    for before, after in (driving, walking):
        assert between(before, DIRECT) and between(after, DETOUR)


def test_a_street_made_one_way_runs_the_way_the_line_is_drawn(scenario):
    # OpenStreetMap has row 0 from west to east; the feature is drawn the
    # other way, from east to west, and that is the way traffic may go.
    westward = list(reversed(MIDDLE_BLOCK))
    built = scenario.build(edit_layer(westward, oneway="yes"))

    westbound, eastbound, walking_east = scenario.before_and_after(
        built, ("auto", B, A), ("auto", A, B), ("pedestrian", A, B))

    assert between(westbound[0], DIRECT) and between(westbound[1], DIRECT)
    assert between(eastbound[0], DIRECT) and between(eastbound[1], DETOUR)
    # One-way streets don't bind walkers.
    assert between(walking_east[1], DIRECT)


def test_a_lower_speed_limit_makes_the_drive_slower_not_longer(scenario):
    built = scenario.build(edit_layer(ALONG_ROW_0, maxspeed="20"))

    (before, after), = scenario.before_and_after(built, ("auto", A, B))

    assert between(before, DIRECT) and between(after, DIRECT)
    assert after.seconds > before.seconds * 1.2


def test_a_banned_turn_is_obeyed_by_cars_not_walkers(scenario):
    # From row 1 heading east, left into the second column heading north.
    corner = (-3.6988, 40.4009)
    left_turn = [(-3.6992, 40.4009), corner, (-3.6988, 40.4012)]
    start, end = (-3.6994, 40.4009), (-3.6988, 40.4014)   # just before, just after
    built = scenario.build(line_layer((left_turn, "no_left_turn"), fields=("restriction",)))

    driving, walking = scenario.before_and_after(
        built, ("auto", start, end), ("pedestrian", start, end))

    # About 51 m to the corner and 56 m up the street.
    assert 95 < driving[0].metres < 120
    assert driving[1].metres > driving[0].metres + 150   # round a block instead
    assert walking[1].metres == pytest.approx(walking[0].metres, abs=1)


# --------------------------------------------- a network of your own lines

def own_streets(*extra, fields=("highway",)):
    return line_layer((STREET, "residential"), (CROSSING, "residential"),
                      (ROUND_THE_BLOCK, "residential"), *extra, fields=fields)


def test_a_standalone_network_joins_lines_where_they_cross(scenario):
    built = scenario.standalone(own_streets())

    with scenario.valhalla(built["NETWORK_OSM"]):
        # The street and the crossing street share no vertex: this route
        # exists only because NetworkForge joined them where they cross.
        for profile in ("auto", "bicycle", "pedestrian"):
            assert between(scenario.route(profile, START, TOP), VIA_CROSSING), profile


def test_a_standalone_network_joined_at_vertices_only_keeps_crossings_apart(
        scenario, real_engine):
    join_at = real_engine.bundled_info()["join_at"]
    built = scenario.standalone(own_streets(), JOIN_AT=join_at.index("vertices"))

    with scenario.valhalla(built["NETWORK_OSM"]):
        assert between(scenario.route("pedestrian", START, TOP), VIA_BLOCK)


def test_a_bridge_in_a_standalone_network_is_not_a_junction(scenario):
    streets = line_layer(
        (STREET, "residential"), (CROSSING, "residential", "yes", "1"),
        (ROUND_THE_BLOCK, "residential"), fields=("highway", "bridge", "layer"))
    built = scenario.standalone(streets)

    with scenario.valhalla(built["NETWORK_OSM"]):
        assert between(scenario.route("pedestrian", START, TOP), VIA_BLOCK)


def test_a_one_way_street_in_a_standalone_network(scenario):
    # The crossing street is drawn from south to north: one-way northbound.
    streets = line_layer(
        (STREET, "residential"), (CROSSING, "residential", "yes"),
        (ROUND_THE_BLOCK, "residential"), fields=("highway", "oneway"))
    built = scenario.standalone(streets)

    with scenario.valhalla(built["NETWORK_OSM"]):
        assert between(scenario.route("auto", START, TOP), VIA_CROSSING)
        assert between(scenario.route("auto", TOP, START), VIA_BLOCK)
        assert between(scenario.route("pedestrian", TOP, START), VIA_CROSSING)


def test_a_banned_turn_in_a_standalone_network(scenario):
    built = scenario.standalone(own_streets(
        (LEFT_AT_CROSSING, None, "no_left_turn"), fields=("highway", "restriction")))

    with scenario.valhalla(built["NETWORK_OSM"]):
        assert between(scenario.route("auto", START, TOP), VIA_BLOCK)
        assert between(scenario.route("pedestrian", START, TOP), VIA_CROSSING)
