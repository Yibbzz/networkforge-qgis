"""Makes the worked example for the tutorial: getting to work over a new bridge.

East of Reading the Thames has two road bridges in the town and a narrow
one at Sonning. A third bridge has been proposed for decades. This
script builds one in three stages, each with the plugin's own tools, and
routes on every network with Valhalla:

1. A new bridge with a cycle track, from the Playhatch roundabout to the
   Thames Valley Park business park (one new line).
2. The park's own road opened to through traffic: its two security
   barriers taken out (points) and its 15 mph limit raised to 30 mph
   (changes to existing streets).
3. A bollard on Sonning Bridge, now that drivers have another way
   (a new point).

The bridge is an invented line, not the official design. It writes:

    docs/images/tutorial-bridge-area.webp     the place, and today's drive to work
    docs/images/tutorial-bridge-draw.png      the one line you draw
    docs/images/tutorial-bridge-stage1.png    to work, before and after the bridge
    docs/images/tutorial-bridge-stage2.png    a trip past the park, as the road is opened
    docs/images/tutorial-bridge-stage3.png    from Sonning, with the old bridge closed to cars
    docs/tutorial-data/reading-bridge.gpkg    every layer a reader needs

    QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/make_tutorial_example.py

It needs what scripts/make_examples.py needs, and an internet connection:
the engine downloads the streets from OpenStreetMap (about 35 km2), and
the rivers come from the Overpass API (kept in .pytest_cache/tutorial).
The numbers for the tutorial are printed at the end.
"""

import json
import time
import urllib.parse
import urllib.request

import make_examples as m
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QSize

from networkforge_qgis import styling

WORK = m.CACHE / "tutorial"
DATA = m.ROOT / "docs" / "tutorial-data" / "reading-bridge.gpkg"
MAP_CRS = QgsCoordinateReferenceSystem("EPSG:32630")   # metres; Reading is in UTM zone 30

# West, south, east, north.
AREA = (-0.990, 51.440, -0.895, 51.495)
EXTENT = f"{AREA[0]},{AREA[2]},{AREA[1]},{AREA[3]} [EPSG:4326]"

# The line: from the roundabout on the A4155 at Playhatch, over the
# meadows and the river, to the roundabout at the entrance of Thames
# Valley Park. Its two ends are points of those roundabouts.
PLAYHATCH, PARK_ROUNDABOUT = (-0.93267, 51.47863), (-0.92972, 51.46165)
BRIDGE = [PLAYHATCH, (-0.9305, 51.4690), PARK_ROUNDABOUT]
LINE_FIELDS = ("name", "highway", "maxspeed", "bridge", "layer", "cycleway", "osmid")
BRIDGE_VALUES = ("Thames bridge (proposed)", "primary", "40 mph", "yes", "1", "track", None)

# The park's road between that roundabout and the A3290, as OpenStreetMap
# has it: 15 mph, with a security barrier on each carriageway.
PARK_ROAD_WAYS = {"2978474", "6647481", "1355135803", "1208357738", "1208357739",
                  "1208357740", "22817684", "22817687"}
PARK_ROAD_SPEED = "30 mph"
SONNING_BRIDGE_WAY = "10040523"

# The trips: from a home in Caversham Park Village to work in the park,
# and on to Earley; and from Sonning Eye, by the old bridge, to Earley.
HOME, WORKPLACE, EARLEY, SONNING_EYE = (
    (-0.9480, 51.4800), (-0.9280, 51.4627), (-0.9300, 51.4440), (-0.9190, 51.4790))

OVERPASS = ("https://overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
RIVER = {"color": "#bcd9ee", "width": "70", "width_unit": "MapUnit"}
STREAM = {"color": "#bcd9ee", "width": "22", "width_unit": "MapUnit"}
DRAWN = {"color": "#e6007e", "width": "1.4"}
PANEL = QSize(760, 640)


def rivers():
    """The rivers of the area as lon/lat lines: (the Thames, the others)."""
    cache = WORK / "rivers.json"
    if not cache.exists():
        south, west, north, east = AREA[1], AREA[0], AREA[3], AREA[2]
        query = (f'[out:json][timeout:60];way["waterway"="river"]'
                 f"({south},{west},{north},{east});out tags geom;")
        for url in OVERPASS * 2:
            try:
                request = urllib.request.Request(
                    url, data=urllib.parse.urlencode({"data": query}).encode(),
                    headers={"User-Agent": "networkforge-qgis docs example"})
                with urllib.request.urlopen(request, timeout=90) as reply:
                    cache.write_text(json.dumps(json.load(reply)), encoding="utf-8")
                break
            except (OSError, ValueError) as err:
                print("  no rivers from", url, "-", err)
                time.sleep(5)
        else:
            raise SystemExit("Could not download the rivers; try again later.")
    thames, others = [], []
    for way in json.loads(cache.read_text(encoding="utf-8"))["elements"]:
        line = QgsGeometry.fromPolylineXY(
            [QgsPointXY(p["lon"], p["lat"]) for p in way["geometry"]])
        (thames if "Thames" in way["tags"].get("name", "") else others).append(line)
    return thames, others


def drivable(source, style):
    """A result layer showing only the streets a car may use, styled as the plugin does."""
    layer = QgsVectorLayer(source, "network", "ogr")
    assert layer.isValid(), source
    if not layer.crs().isValid():
        layer.setCrs(MAP_CRS)
    layer.setSubsetString('"car" = 1')
    assert layer.featureCount() > 0
    style(layer)
    return layer


def box(west, south, east, north):
    return QgsCoordinateTransform(m.WGS84, MAP_CRS, QgsProject.instance()).transformBoundingBox(
        QgsRectangle(west, south, east, north))


def picture(network, extent, route=None, stops=(), labels=(), extra=()):
    thames, others = rivers()
    layers = [
        m.markers(m.WGS84, [p for p, _ in stops], **m.STOP),
        *extra,
        m.lines(m.WGS84, [route.line] if route else [], **m.ROUTE),
        network,
        m.lines(m.WGS84, thames, **RIVER),
        m.lines(m.WGS84, others, **STREAM),
    ]
    to_map = QgsCoordinateTransform(m.WGS84, MAP_CRS, QgsProject.instance())
    placed = [(*to_map.transform(QgsPointXY(*p)), text) for p, text in [*stops, *labels]]
    return m.render(layers, extent, MAP_CRS, labels=placed, size=PANEL)


def save_data(layers):
    """The layers a reader needs to follow the tutorial, in one GeoPackage."""
    west, south, east, north = AREA
    area = QgsVectorLayer("Polygon?crs=EPSG:4326&field=name:string", "study_area", "memory")
    feature = QgsFeature(area.fields())
    feature.setGeometry(QgsGeometry.fromRect(QgsRectangle(west, south, east, north)))
    feature.setAttributes(["Reading east"])
    area.dataProvider().addFeatures([feature])
    layers = {
        "study_area": area,
        "trips": m.memory_layer("Point", m.WGS84, [
            (HOME, "A", "Home, Caversham Park Village"),
            (WORKPLACE, "B", "Work, Thames Valley Park"),
            (EARLEY, "C", "Earley"),
            (SONNING_EYE, "D", "Sonning Eye")], fields=("label", "place")),
        **layers,
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


def build(name, **layers):
    return m.run("build_network", EXTENT=EXTENT, OUTPUT_FOLDER=str(WORK / name), **layers)


def routes(pbf, name, **trips):
    """Valhalla's route for each trip = (costing, start, end) on one network."""
    with m.valhalla(pbf, name) as route:
        return {key: route(*trip) for key, trip in trips.items()}


def saved(before, after):
    return f"{(before.seconds - after.seconds) / 60:.1f} min"


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    bridge_line = m.from_lonlat(MAP_CRS, QgsGeometry.fromPolylineXY(
        [QgsPointXY(*p) for p in BRIDGE]))
    bridge_row = (bridge_line, *BRIDGE_VALUES)

    def lines(rows):
        return m.memory_layer("LineString", MAP_CRS, rows, fields=LINE_FIELDS)

    # Stage 1: the bridge alone. Its build also gives the streets as they are.
    stage1 = build("reading-1-bridge", CUSTOM=lines([bridge_row]))
    existing = QgsVectorLayer(stage1["BEFORE"], "before", "ogr")
    existing.setCrs(MAP_CRS)
    nodes = QgsVectorLayer(stage1["BEFORE"].replace("layername=edges", "layername=nodes"),
                           "nodes", "ogr")

    # Stage 2: every stretch of the park's road is copied from the before
    # layer with its OpenStreetMap id and given the new limit; a point on
    # each security barrier takes the barrier out.
    park_road = [f for f in existing.getFeatures() if str(int(f["osmid"])) in PARK_ROAD_WAYS]
    speed_rows = [(f.geometry(), None, None, PARK_ROAD_SPEED, None, None, None,
                   str(int(f["osmid"]))) for f in park_road]
    barriers = [(f["x"], f["y"]) for f in nodes.getFeatures()
                if str(f["barrier"]) == "sliding_beam"]
    assert len(park_road) > 5 and len(barriers) == 2, (len(park_road), barriers)

    def points(rows):
        return m.memory_layer("Point", m.WGS84, rows, fields=("remove_tags", "barrier"))

    barrier_rows = [(point, "barrier", None) for point in barriers]
    stage2 = build("reading-2-park-road", CUSTOM=lines([bridge_row, *speed_rows]),
                   POINTS=points(barrier_rows))

    # Stage 3: a bollard half-way along Sonning Bridge.
    span = next(f for f in existing.getFeatures()
                if str(int(f["osmid"])) == SONNING_BRIDGE_WAY)
    middle = span.geometry().interpolate(span.geometry().length() / 2)
    middle.transform(QgsCoordinateTransform(MAP_CRS, m.WGS84, QgsProject.instance()))
    bollard = tuple(middle.asPoint())
    stage3 = build("reading-3-sonning", CUSTOM=lines([bridge_row, *speed_rows]),
                   POINTS=points([*barrier_rows, (bollard, None, "bollard")]))

    save_data({
        "1_bridge": lines([bridge_row]),
        "2_bridge_and_park_road": lines([bridge_row, *speed_rows]),
        "2_barriers_removed": points(barrier_rows),
        "3_barriers_removed_and_bollard": points([*barrier_rows, (bollard, None, "bollard")]),
    })

    to_work = {mode: (mode, HOME, WORKPLACE) for mode in ("auto", "bicycle", "pedestrian")}
    trips = {**to_work, "earley": ("auto", HOME, EARLEY),
             "sonning": ("auto", SONNING_EYE, EARLEY),
             "sonning_bicycle": ("bicycle", SONNING_EYE, EARLEY)}
    today = routes(stage1["BEFORE_OSM"], "reading-before", **trips)
    one = routes(stage1["AFTER_OSM"], "reading-1", **trips)
    two = routes(stage2["AFTER_OSM"], "reading-2", **trips)
    three = routes(stage3["AFTER_OSM"], "reading-3", **trips)

    whole = box(-0.988, 51.4385, -0.897, 51.4935)
    places = [((-0.9772, 51.4662), "Caversham Bridge"), ((-0.9672, 51.4612), "Reading Bridge"),
              ((-0.9135, 51.4757), "Sonning Bridge"), ((-0.9870, 51.4530), "Reading")]
    credit = ("Reading, England. Map data \u00a9 OpenStreetMap contributors (ODbL). "
              "Streets a car may use; routes by Valhalla.")
    invented = " The scheme is an invented example."
    work_stops = [(HOME, "A"), (WORKPLACE, "B")]
    earley_stops = [(HOME, "A"), (EARLEY, "C")]
    sonning_stops = [(SONNING_EYE, "D"), (EARLEY, "C")]
    new_bridge = [((-0.9300, 51.4700), "New bridge")]

    def before_map(route=None, stops=(), labels=()):
        return picture(drivable(stage1["BEFORE"], styling.style_before), whole, route,
                       stops, labels)

    def after_map(stage, route, stops, labels=(), extra=()):
        return picture(drivable(stage["AFTER"], styling.style_after), whole, route,
                       stops, labels, extra)

    m.figure(
        "tutorial-bridge-area", "",
        [("Today", f"driving A to B: {today['auto']}",
          before_map(today["auto"], work_stops, places))],
        credit, extension="webp")

    close = box(-0.9520, 51.4545, -0.9110, 51.4835)
    drawn = m.lines(m.WGS84, [QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in BRIDGE])],
                    **DRAWN)
    ends = m.markers(m.WGS84, [BRIDGE[0], BRIDGE[-1]], name="circle", color="#e6007e",
                     outline_color="#ffffff", outline_width="0.4", size="3")
    m.figure(
        "tutorial-bridge-draw", "The one line you draw",
        [("A line with six attributes", "its ends are on the two roundabouts",
          picture(drivable(stage1["BEFORE"], styling.style_before), close,
                  labels=[(PLAYHATCH, "Playhatch roundabout"),
                          (PARK_ROUNDABOUT, "Thames Valley Park"),
                          ((-0.9300, 51.4668), "River Thames")],
                  extra=[ends, drawn]))],
        "highway = primary, maxspeed = 40 mph, bridge = yes, layer = 1, cycleway = track, "
        "and a name." + invented)

    m.figure(
        "tutorial-bridge-stage1", "Stage 1: a new bridge, with a cycle track",
        [("Before", f"driving A to B: {today['auto']}",
          before_map(today["auto"], work_stops)),
         ("After", f"driving A to B: {one['auto']}",
          after_map(stage1, one["auto"], work_stops, new_bridge))],
        credit + invented)

    barrier_marks = m.markers(m.WGS84, barriers, **m.BOLLARD)
    m.figure(
        "tutorial-bridge-stage2", "Stage 2: the park's road opened to through traffic",
        [("With the bridge only", f"driving A to C: {one['earley']}",
          after_map(stage1, one["earley"], earley_stops, new_bridge)),
         ("Barriers out, 30 mph", f"driving A to C: {two['earley']}",
          after_map(stage2, two["earley"], earley_stops,
                    [(barriers[0], "Barriers removed")], [barrier_marks]))],
        credit + " Orange: streets changed." + invented)

    bollard_mark = m.markers(m.WGS84, [bollard], **m.BOLLARD)
    m.figure(
        "tutorial-bridge-stage3", "Stage 3: Sonning Bridge closed to cars",
        [("Stage 2", f"driving D to C: {two['sonning']}",
          after_map(stage2, two["sonning"], sonning_stops)),
         ("With a bollard on the bridge", f"driving D to C: {three['sonning']}",
          after_map(stage3, three["sonning"], sonning_stops, [(bollard, "Bollard")],
                    [bollard_mark]))],
        credit + invented)

    print("Numbers for the tutorial:")
    print(f"  park road: {len(park_road)} stretches of {len(PARK_ROAD_WAYS)} streets; "
          f"barriers at {barriers}; bollard at {bollard}")
    names = {"auto": "A to B, driving", "bicycle": "A to B, cycling",
             "pedestrian": "A to B, walking", "earley": "A to C, driving",
             "sonning": "D to C, driving", "sonning_bicycle": "D to C, cycling"}
    for key, name in names.items():
        print(f"  {name}")
        for label, result in (("today", today), ("stage 1", one), ("stage 2", two),
                              ("stage 3", three)):
            print(f"    {label:8} {result[key]}   (saves {saved(today[key], result[key])})")


if __name__ == "__main__":
    main()
