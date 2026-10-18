"""Esri's public transit tutorial, done with NetworkForge and Easy-R5.

ArcGIS Pro's tutorial "Create and use a network dataset with public
transit data" builds a network from streets and two agencies' GTFS
feeds, then compares 30-minute transit service areas from downtown at
5:15 pm and at 2:00 pm on a weekday: off-peak service is sparser, so
the 2:00 pm area is smaller. This test does the same in miniature with
QGIS tools: NetworkForge makes the street network (the PBF), GISBoost's
Easy-R5 plugin (Conveyal R5) builds the transit network from it and two
GTFS feeds and draws the service areas.

What the tutorial has that this can't do: its "with wheelchair" travel
mode. Easy-R5 has no wheelchair setting, and R5's analysis ignores the
GTFS wheelchair fields. Its pedestrian restriction is a street tagged
foot=no, tested in the engine (tests/r5/test_edits.py).

Marked "easy_r5". The first run downloads Easy-R5, a Java runtime and
R5 (about 250 MB) into .pytest_cache; nothing is installed into QGIS.
Easy-R5 says it supports QGIS 3 only (qgisMaximumVersion=3.99), so the
test is skipped on QGIS 4.

    pytest -m easy_r5          only this
    pytest -m "not easy_r5"    everything else

The town is a grid of 8 x 8 junctions 100 m apart (R5 drops connected
pieces of fewer than about 40 streets, so not tests/data's 4 x 4 grid),
small enough that the service areas are 15 minutes, not 30.
"""

import io
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

import pytest
from qgis import processing
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

pytestmark = [
    pytest.mark.easy_r5,
    pytest.mark.skipif(Qgis.QGIS_VERSION_INT >= 40000,
                       reason="Easy-R5 supports QGIS 3 only (qgisMaximumVersion=3.99)"),
]

EASY_R5_REPO = "https://github.com/GISBoost/easy-R5"
EASY_R5_COMMIT = "63d3f42140d0de9842de87a55e71750afc53d160"  # 0.3.0, 2026-10-13
CACHE = Path(__file__).parent.parent / ".pytest_cache" / "easy-r5"

# The grid: N x N junctions 100 m apart, origin at (-3.7, 40.4). Row r is
# OSM way 2000 + r (drawn west to east), column c is way 3000 + c.
N = 8
DLON, DLAT = 0.0011779, 0.0009   # about 100 m each at 40.4 degrees north
DATE = "2026-10-19"              # a Monday, in the feeds' calendars


def at(col, row):
    """The point `col` blocks east and `row` blocks north of the grid's corner."""
    return (-3.7 + col * DLON, 40.4 + row * DLAT)


WEST, FAR_CORNER = at(0, 0), at(N - 1, N - 1)
EXTENT = (f"{WEST[0] - 0.0001},{FAR_CORNER[0] + 0.0001},"
          f"{WEST[1] - 0.0001},{FAR_CORNER[1] + 0.0001} [EPSG:4326]")


def grid_osm(path):
    """Write the grid of residential streets as an OSM XML file."""
    def node_id(row, col):
        return 1 + row * N + col

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<osm version="0.6" generator="networkforge-qgis tests">']
    for row in range(N):
        for col in range(N):
            lon, lat = at(col, row)
            lines.append(f'  <node id="{node_id(row, col)}" version="1" '
                         f'timestamp="2026-01-01T00:00:00Z" lat="{lat:.7f}" lon="{lon:.7f}"/>')
    streets = [(2000 + r, [node_id(r, c) for c in range(N)]) for r in range(N)]
    streets += [(3000 + c, [node_id(r, c) for r in range(N)]) for c in range(N)]
    for way_id, nodes in streets:
        lines.append(f'  <way id="{way_id}" version="1" timestamp="2026-01-01T00:00:00Z">')
        lines += [f'    <nd ref="{n}"/>' for n in nodes]
        lines += ['    <tag k="highway" v="residential"/>', "  </way>"]
    lines.append("</osm>")
    path.write_text("\n".join(lines), encoding="utf-8")


# The two agencies, like the tutorial's SORTA and TANK. The city bus runs
# up column 1 from downtown (row 0) to row 7; the suburban bus carries on
# along row 7 to the far corner; each takes 2 minutes. At peak (4:30 to
# 6:30 pm) the city bus runs every 5 minutes and the suburban bus leaves
# uptown 3 minutes after it gets there. Off-peak (1 to 4 pm) the city bus
# runs every 30 minutes, at 5 and 35 past, and the suburban bus leaves 8
# minutes after it gets there: sparser service, as in the tutorial.
DOWNTOWN, UPTOWN, FAR_END = at(1, 0), at(1, N - 1), at(N - 1, N - 1)
PEAK = range(16 * 60 + 30, 18 * 60 + 30, 5)
OFF_PEAK = range(13 * 60 + 5, 16 * 60, 30)


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


def gtfs_feed(path, agency, stops, times):
    """One agency's feed: one route between two stops, 2 minutes, leaving at `times`."""
    (a_id, a), (b_id, b) = stops
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n"
                      f"{agency},{agency} buses,https://example.org,Europe/Madrid\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n"
                     f"{a_id},{a_id},{a[1]:.7f},{a[0]:.7f}\n{b_id},{b_id},{b[1]:.7f},{b[0]:.7f}\n",
        "routes.txt": f"route_id,agency_id,route_short_name,route_type\n{agency}1,{agency},1,3\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
                        f"start_date,end_date\n{agency}_WEEKDAYS,1,1,1,1,1,0,0,20260101,20271231\n",
        "trips.txt": "route_id,service_id,trip_id\n"
                     + "".join(f"{agency}1,{agency}_WEEKDAYS,{agency}_{t}\n" for t in times),
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" + "".join(
            f"{agency}_{t},{_hhmm(t)},{_hhmm(t)},{a_id},1\n"
            f"{agency}_{t},{_hhmm(t + 2)},{_hhmm(t + 2)},{b_id},2\n"
            for t in times),
    }
    with zipfile.ZipFile(path, "w") as feed:
        for name, text in files.items():
            feed.writestr(name, text)


def gtfs_folder(folder):
    """The two agencies' feeds, in one folder, as Easy-R5 takes them."""
    folder.mkdir(parents=True, exist_ok=True)
    gtfs_feed(folder / "city.zip", "CITY", [("DOWNTOWN", DOWNTOWN), ("UPTOWN", UPTOWN)],
              [*OFF_PEAK, *PEAK])
    # The suburban bus stops 30 m along the street from the city bus's
    # stop: R5 doesn't change buses between two stops in exactly the same
    # place (checked with Easy-R5 0.3.0, R5 7.6).
    gtfs_feed(folder / "suburban.zip", "SUBURBAN",
              [("UPTOWN_S", at(1.3, N - 1)), ("FAR_END", FAR_END)],
              [t + 10 for t in OFF_PEAK] + [t + 5 for t in PEAK])
    return folder


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


def _work_round_tar_links(downloads):
    """Let Easy-R5 unpack its Java runtime where Python's tarfile can't.

    Python 3.10.12 (Ubuntu 22.04's) has an early tarfile "data" filter
    that judges a relative link from the wrong folder (CPython gh-107845)
    and refuses the links inside the Temurin JDK archive, so Easy-R5's
    own set-up fails there. Easy-R5 checks the archive's SHA-256 before
    unpacking it, so it is safe to unpack it again without the filter.
    """
    original = downloads.safe_extract_tar

    def safe_extract_tar(tar_path, dest_dir):
        try:
            original(tar_path, dest_dir)
        except tarfile.LinkOutsideDestinationError:
            with tarfile.open(tar_path) as archive:
                archive.extractall(dest_dir, filter="tar")

    downloads.safe_extract_tar = safe_extract_tar


@pytest.fixture(scope="session")
def easy_r5(qgis_processing):
    """Easy-R5's Processing tools, with R5 and Java downloaded."""
    folder = CACHE / f"plugin-{EASY_R5_COMMIT[:10]}"
    if not (folder / "ready").exists():
        shutil.rmtree(folder, ignore_errors=True)
        _download_zip(f"{EASY_R5_REPO}/archive/{EASY_R5_COMMIT}.zip", folder)
        (folder / "ready").write_text(EASY_R5_COMMIT)
    sys.path.insert(0, str(folder))
    try:
        from easy_r5.core import downloads
        from easy_r5.provider import EasyR5Provider
    finally:
        sys.path.remove(str(folder))
    _work_round_tar_links(downloads)
    provider = EasyR5Provider()
    registry = QgsApplication.processingRegistry()
    registry.addProvider(provider)
    processing.run("easyr5:downloadr5", {"TARGET_FOLDER": str(CACHE / "r5")})
    yield provider
    registry.removeProvider(provider)


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


def point_layer(*points, fields=("id",)):
    """A layer of (x, y, *values of `fields`) points."""
    spec = "".join(f"&field={name}:string" for name in fields)
    layer = QgsVectorLayer(f"Point?crs=EPSG:4326{spec}", "points", "memory")
    features = []
    for x, y, *values in points:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        feature.setAttributes(values)
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


MODES = {"transit": 0, "walk": 1, "bike": 2, "car": 3}   # Easy-R5's MODE choices


# ----------------------------------------------------------- the tutorial

def service_area(network, departure, minutes, folder, feedback):
    """Easy-R5's transit service area (polygon) from just north of downtown."""
    start = at(1, 0.2)   # 20 m from the city bus's first stop
    output = folder / f"service-area-{departure.replace(':', '')}.gpkg"
    processing.run("easyr5:generateisochrones", {
        "NETWORK": network, "ORIGINS": point_layer((*start, "downtown")), "ORIGIN_ID_FIELD": "id",
        "MODE": 0,                         # transit and walking
        "DATE": DATE, "DEPARTURE_TIME": departure,
        "TIME_WINDOW": 1,                  # leave at that time, as in the tutorial
        "CUTOFFS": str(minutes), "ESTIMATE_FIRST": False,
        # Easy-R5 sizes its grid of destinations from the longest trip.
        "MAX_TRIP_DURATION": minutes + 1, "GRID_SPACING": 50,
        "OUTPUT_LAYER": str(output),
    }, feedback=feedback)
    polygons = [f.geometry() for f in QgsVectorLayer(str(output), "area", "ogr").getFeatures()]
    said = "\n".join(feedback.warnings[-10:] + feedback.errors[-10:] + feedback.infos[-15:])
    assert polygons, f"Easy-R5 drew no service area for {departure}. It said:\n{said}"
    return QgsGeometry.unaryUnion(polygons)


def test_esri_public_transit_tutorial_peak_and_off_peak_service_areas(
        provider, real_engine, easy_r5, feedback, tmp_path, qgis_new_project):
    # 1. The street network, made by NetworkForge: the town's grid plus a
    #    new footpath (any change would do; the after PBF is what counts).
    grid = tmp_path / "grid.osm"
    grid_osm(grid)
    plan = line_layer(([at(4.5, 2), at(4.5, 3)], "footway"))
    built = processing.run("networkforge:build_network", {
        "EXTENT": EXTENT, "CUSTOM": plan, "OSM_FILE": str(grid),
        "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)

    # 2. The transit network: the PBF and both agencies' GTFS feeds.
    network = processing.run("easyr5:buildnetwork", {
        "OSM_PBF": built["AFTER_OSM"], "GTFS_FOLDER": str(gtfs_folder(tmp_path / "gtfs")),
        "CACHE_FOLDER": str(tmp_path / "r5-networks"),
    }, feedback=feedback)["NETWORK_DAT"]

    # 3. Service areas at 5:15 pm and at 2:00 pm.
    peak = service_area(network, "17:15", 15, tmp_path, feedback)
    off_peak = service_area(network, "14:00", 15, tmp_path, feedback)

    def reaches(area, col, row):
        return area.contains(QgsGeometry.fromPointXY(QgsPointXY(*at(col, row))))

    # At 5:15 pm: the city bus up column 1 (17:20, uptown 17:22), then the
    # suburban bus along row 7 (17:25, far end 17:27): about 12 minutes.
    # On foot the far end is 1,260 m away, 21 minutes.
    assert reaches(peak, N - 1.2, N - 1)
    # At 2:00 pm: the city bus at 2:05 (uptown 2:07), the suburban bus at
    # 2:15 (far end 2:17): 17 minutes, outside the area.
    assert not reaches(off_peak, N - 1.2, N - 1)
    # Both include the streets round downtown, and the peak area is bigger.
    # (Not by much: Easy-R5 smooths travel times over a grid, and its
    # polygons reach well past the streets on every side.)
    assert reaches(peak, 1.5, 0.5) and reaches(off_peak, 1.5, 0.5)
    assert peak.area() > off_peak.area()
