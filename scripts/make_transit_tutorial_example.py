"""Makes the worked example for the public transport tutorial (docs/tutorial-transit.md).

Esri's ArcGIS Pro tutorial "Create and use a network dataset with public
transit data" builds a network for Cincinnati from streets and two bus
companies' GTFS feeds (Metro in Ohio, TANK in Kentucky), then draws
30-minute transit service areas from downtown at 5:15 pm and at 2:00 pm.
This does the same with QGIS plugins: NetworkForge makes the street
network (the PBF), GISBoost's Easy-R5 (Conveyal R5) adds the feeds and
draws the service areas.

Esri's tutorial also sets up a wheelchair travel mode, which Easy-R5
can't do. In its place: two of Cincinnati's public stairways, closed in
OpenStreetMap (foot=no), reopened with NetworkForge. They join Klotter
Avenue, on the hill above Brighton, to the buses on Central Parkway at
the bottom. The 30-minute service area from Klotter Avenue is compared
before and after.

It writes docs/tutorial-data/cincinnati-transit.gpkg (every layer a reader
needs) and prints the numbers the tutorial quotes.

    QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/make_transit_tutorial_example.py

Needs an internet connection (the engine downloads the streets from
OpenStreetMap, about 240 km2, which takes about 8 minutes and 4 GB of
memory; the stairways' shapes come from the Overpass API; the feeds from
the two bus companies) and Easy-R5 in .pytest_cache (run
`pytest -m easy_r5` once). The feeds are kept in .pytest_cache/transit:
delete them to fetch new ones. Feeds run out: if the date below is no
longer in them, pick a new weekday (Easy-R5's "Check transit data" lists
the days with service) and change DATE here and in the tutorial.
"""

import json
import sys
import time
import urllib.parse
import urllib.request

import make_examples as m
from qgis.core import (
    QgsApplication,
    QgsCoordinateTransformContext,
    QgsDistanceArea,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

import processing

WORK = m.CACHE / "transit"
DATA = m.ROOT / "docs" / "tutorial-data" / "cincinnati-transit.gpkg"
GTFS = WORK / "gtfs"
EASY_R5 = m.CACHE / "easy-r5"

# West, south, east, north: downtown Cincinnati, Covington and Newport
# across the river, and the hills to the north as far as a 30-minute
# trip from Brighton reaches.
AREA = (-84.585, 39.055, -84.415, 39.200)
EXTENT = f"{AREA[0]},{AREA[2]},{AREA[1]},{AREA[3]} [EPSG:4326]"

# Esri's facility is "in downtown, near many transit stops".
FOUNTAIN_SQUARE = (-84.5125, 39.1015)
# A home on Klotter Avenue, on the hill above Brighton.
KLOTTER_AVENUE = (-84.5290, 39.1228)

# The two stairways from West McMicken Avenue up towards Klotter Avenue,
# closed in OpenStreetMap (access=no, foot=no).
CLOSED_STEPS = {"197716033": "Freeman Avenue steps", "197715354": "Kress Alley steps"}

# Section 8: a new tram line up Vine Street from Fountain Square to
# Uptown, which Cincinnati has studied since 2007 but never chosen a
# route for. Invented: each point is a stop (Easy-R5 draws a line's
# vertices as its stops). It runs every 10 minutes, all day.
TRAM_STOPS = [
    (-84.5128, 39.1013),   # Vine & 5th, Fountain Square
    (-84.5142, 39.1060),   # Vine & Central Parkway
    (-84.5157, 39.1118),   # Vine & Liberty
    (-84.5172, 39.1175),   # Vine & McMicken
    (-84.5158, 39.1210),   # up the hill
    (-84.5122, 39.1265),   # Vine & McMillan
    (-84.5094, 39.1315),   # Corryville, Short Vine
    (-84.5091, 39.1365),   # Vine & Martin Luther King Drive, the University
]
TRAM = {"name": "Uptown tram", "speed_kmh": 18, "headway": 10}
TRAM_WINDOW = 60             # minutes: compare the tram over 2:00-3:00 pm

# Both companies' current feeds (the Mobility Database lists them as
# mdb-307 and mdb-2068).
FEEDS = {
    "metro.zip": "https://www.go-metro.com/uploads/GTFS/google_transit_info.zip",
    "tank.zip": "https://tank.rideralerts.com/InfoPoint/GTFS-Zip.ashx",
}
DATE = "2026-10-20"          # a Tuesday with service in both feeds
PEAK, OFF_PEAK = "17:15", "14:00"
CUTOFF = 30
GRID = 100                   # metres between Easy-R5's destination points

OVERPASS = ("https://overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
AGENT = {"User-Agent": "networkforge-qgis docs example"}


def download(url, path):
    request = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(request, timeout=300) as reply:
        path.write_bytes(reply.read())


def feeds():
    GTFS.mkdir(parents=True, exist_ok=True)
    for name, url in FEEDS.items():
        if not (GTFS / name).exists():
            print("downloading", url)
            download(url, GTFS / name)
    return GTFS


def closed_steps():
    """The stairways' shapes from OpenStreetMap, as lon/lat lines."""
    cache = WORK / "steps.json"
    if not cache.exists():
        query = f"[out:json][timeout:60];way(id:{','.join(CLOSED_STEPS)});out tags geom;"
        for url in OVERPASS * 2:
            try:
                request = urllib.request.Request(
                    url, data=urllib.parse.urlencode({"data": query}).encode(), headers=AGENT)
                with urllib.request.urlopen(request, timeout=90) as reply:
                    cache.write_text(json.dumps(json.load(reply)), encoding="utf-8")
                break
            except (OSError, ValueError) as err:
                print("  no stairways from", url, "-", err)
                time.sleep(10)
        else:
            raise SystemExit("Could not download the stairways; try again later.")
    ways = json.loads(cache.read_text(encoding="utf-8"))["elements"]
    for way in ways:
        assert way["tags"].get("foot") == "no", (
            f"way {way['id']} is no longer closed in OpenStreetMap: {way['tags']}")
    return {str(way["id"]): [(p["lon"], p["lat"]) for p in way["geometry"]] for way in ways}


def point_layer(name, point, label):
    layer = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string", name, "memory")
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*point)))
    feature.setAttributes([label])
    layer.dataProvider().addFeatures([feature])
    return layer


def save_data():
    """The layers a reader needs, in one GeoPackage."""
    west, south, east, north = AREA
    area = QgsVectorLayer("Polygon?crs=EPSG:4326&field=name:string", "study_area", "memory")
    feature = QgsFeature(area.fields())
    feature.setGeometry(QgsGeometry.fromRect(QgsRectangle(west, south, east, north)))
    feature.setAttributes(["Cincinnati, Covington and Newport"])
    area.dataProvider().addFeatures([feature])

    steps = QgsVectorLayer(
        "LineString?crs=EPSG:4326&field=name:string&field=highway:string"
        "&field=osmid:string&field=access:string&field=foot:string", "steps_reopened", "memory")
    rows = []
    for way_id, points in closed_steps().items():
        feature = QgsFeature(steps.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in points]))
        feature.setAttributes([CLOSED_STEPS[way_id], "steps", way_id, "yes", "yes"])
        rows.append(feature)
    steps.dataProvider().addFeatures(rows)

    tram = QgsVectorLayer("LineString?crs=EPSG:4326&field=name:string", "uptown_tram", "memory")
    feature = QgsFeature(tram.fields())
    feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in TRAM_STOPS]))
    feature.setAttributes([TRAM["name"]])
    tram.dataProvider().addFeatures([feature])

    layers = {
        "study_area": area,
        "fountain_square": point_layer("fountain_square", FOUNTAIN_SQUARE, "Fountain Square"),
        "klotter_avenue": point_layer("klotter_avenue", KLOTTER_AVENUE, "Klotter Avenue"),
        "steps_reopened": steps,
        "uptown_tram": tram,
    }
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.unlink(missing_ok=True)
    for name, layer in layers.items():
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = name
        if DATA.exists():
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, str(DATA), QgsCoordinateTransformContext(), options)
    print("wrote", DATA)
    return layers


def easy_r5():
    """Easy-R5's Processing tools, from the copy the tests downloaded."""
    folders = sorted(EASY_R5.glob("plugin-*"))
    if not folders or not (EASY_R5 / "r5").exists():
        raise SystemExit("Easy-R5 isn't in .pytest_cache yet: run pytest -m easy_r5 once.")
    sys.path.insert(0, str(folders[0]))
    from easy_r5.provider import EasyR5Provider
    provider = EasyR5Provider()
    QgsApplication.processingRegistry().addProvider(provider)
    processing.run("easyr5:downloadr5", {"TARGET_FOLDER": str(EASY_R5 / "r5")})
    return provider


def r5(tool, **parameters):
    return processing.run(f"easyr5:{tool}", parameters, feedback=m.Notes())


def km2(path):
    layer = QgsVectorLayer(str(path), "area", "ogr")
    measure = QgsDistanceArea()
    measure.setEllipsoid("WGS84")
    measure.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
    return sum(measure.measureArea(f.geometry()) for f in layer.getFeatures()) / 1e6


def service_area(network, origin, departure, name, scenario=None, window=1):
    path = WORK / f"service-area-{name}.gpkg"
    r5("generateisochrones", NETWORK=network, ORIGINS=origin, ORIGIN_ID_FIELD="name",
       DATE=DATE, DEPARTURE_TIME=departure, TIME_WINDOW=window, MAX_TRIP_DURATION=CUTOFF,
       MODE=0, CUTOFFS=str(CUTOFF), GRID_SPACING=GRID, ESTIMATE_FIRST=False,
       OUTPUT_LAYER=str(path), JAVA_HEAP_GB=3,
       **({"SCENARIO": scenario} if scenario else {}))
    return km2(path)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    layers = save_data()
    gtfs = feeds()
    keep = easy_r5()  # noqa: F841 - Processing drops a provider that is garbage-collected

    report = r5("checktransitdata", GTFS=str(gtfs / "metro.zip"), WHOLE_FOLDER=True,
                DATE=DATE, EXTENT=EXTENT, OUTPUT_REPORT=str(WORK / "gtfs-report.html"))
    print("GTFS check:", report)

    # The street networks, before and after: kept, since the build takes 8
    # minutes. Delete .pytest_cache/transit/network to build them again.
    folder = WORK / "network"
    if not (folder / "after.osm.pbf").exists():
        m.run("build_network", EXTENT=EXTENT, CUSTOM=layers["steps_reopened"],
              OUTPUT_FOLDER=str(folder))
    networks = {
        which: r5("buildnetwork", OSM_PBF=str(folder / f"{which}.osm.pbf"), GTFS_FOLDER=str(gtfs),
                  CACHE_FOLDER=str(WORK / "r5"))["NETWORK_DAT"]
        for which in ("before", "after")
    }

    tram = r5("buildscenario", NEW_LINES=layers["uptown_tram"], LINE_NAME_FIELD="name",
              NEW_LINE_MODE=0, SPEED_KMH=TRAM["speed_kmh"], HEADWAY_MINUTES=TRAM["headway"],
              SERVICE_START="05:00", SERVICE_END="23:00",
              OUTPUT_SCENARIO=str(WORK / "uptown-tram.json"))["OUTPUT_SCENARIO"]

    numbers = {
        "Fountain Square, 5:15 pm": service_area(
            networks["before"], layers["fountain_square"], PEAK, "downtown-peak"),
        "Fountain Square, 2:00 pm": service_area(
            networks["before"], layers["fountain_square"], OFF_PEAK, "downtown-off-peak"),
        "Klotter Avenue, 5:15 pm, steps closed": service_area(
            networks["before"], layers["klotter_avenue"], PEAK, "klotter-before"),
        "Klotter Avenue, 5:15 pm, steps open": service_area(
            networks["after"], layers["klotter_avenue"], PEAK, "klotter-after"),
        # A new line has a frequency, not a timetable: R5 tries random
        # departure times for it, so a one-minute window gives a different
        # answer each run. Over an hour (the median trip) it is steady.
        "Fountain Square, 2:00-3:00 pm, today": service_area(
            networks["before"], layers["fountain_square"], OFF_PEAK, "downtown-hour",
            window=TRAM_WINDOW),
        "Fountain Square, 2:00-3:00 pm, with the Uptown tram": service_area(
            networks["before"], layers["fountain_square"], OFF_PEAK, "downtown-tram", tram,
            window=TRAM_WINDOW),
    }
    print("\n30-minute transit service areas on", DATE)
    for name, value in numbers.items():
        print(f"  {name}: {value:.1f} km2")


if __name__ == "__main__":
    main()
