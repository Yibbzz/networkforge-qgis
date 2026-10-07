"""The tools against the real engine, on a tiny hand-made street grid.

Marked "engine": the first run installs the pinned engine (needs an
internet connection, takes a minute or two). Nothing is downloaded from
OpenStreetMap: the network comes from tests/data/grid.osm.

    pytest -m engine          only these
    pytest -m "not engine"    everything else
"""

from pathlib import Path

import pytest
from qgis import processing
from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingException,
    QgsProject,
    QgsVectorLayer,
)

pytestmark = pytest.mark.engine

GRID = Path(__file__).parent / "data" / "grid.osm"
EXTENT = "-3.701,-3.695,40.399,40.404 [EPSG:4326]"
# Corner to corner across the grid, and a line out in the fields.
DIAGONAL = [(-3.7000, 40.4000), (-3.6964, 40.4027)]
FAR_AWAY = [(-3.6952, 40.4035), (-3.6951, 40.4038)]


def line_layer(*lines, extra_fields=()):
    """A project layer of (highway, maxspeed, points, *extra values) lines."""
    fields = "".join(f"&field={name}:string" for name in ("highway", "maxspeed", *extra_fields))
    layer = QgsVectorLayer(f"LineString?crs=EPSG:4326{fields}", "plan", "memory")
    features = []
    for highway, maxspeed, points, *extra in lines:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points]))
        feature.setAttributes([highway, maxspeed, *extra])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    QgsProject.instance().addMapLayer(layer)
    return layer


def test_saved_info_matches_the_engine(real_engine):
    # If this fails, regenerate networkforge_qgis/engine_info.json from
    # `networkforge info --json` of the pinned version.
    assert real_engine.info() == real_engine.bundled_info()


def test_build_gives_before_and_after_networks(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    plan = line_layer(("cycleway", "20", DIAGONAL))

    results = processing.run("networkforge:build_network", {
        "EXTENT": EXTENT, "CUSTOM": plan, "OSM_FILE": str(GRID),
        "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)

    before = QgsVectorLayer(results["BEFORE"], "before", "ogr")
    after = QgsVectorLayer(results["AFTER"], "after", "ogr")
    assert before.isValid() and after.isValid()
    assert before.featureCount() == 24  # 4 rows and 4 columns of 3 blocks each
    assert after.featureCount() > before.featureCount()

    names = [field.name() for field in after.fields()]
    for column in ["custom", *real_engine.bundled_info()["gpkg_edge_columns"]]:
        assert column in names
    custom = [f for f in after.getFeatures() if f["custom"] == "yes"]
    assert custom
    assert {f["highway"] for f in custom} == {"cycleway"}
    assert all(f["bike"] and not f["car"] for f in custom)
    # The before network has nothing custom, so the engine leaves the column out.
    assert "custom" not in [field.name() for field in before.fields()]

    for output in ("BEFORE_OSM", "AFTER_OSM"):
        assert Path(results[output]).stat().st_size > 0
    assert not feedback.warnings
    assert feedback.progress[-1] == 100


def test_build_warns_about_and_selects_a_line_that_does_not_connect(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    plan = line_layer(("cycleway", None, DIAGONAL), ("cycleway", None, FAR_AWAY))
    connected, stray = sorted(f.id() for f in plan.getFeatures())

    processing.run("networkforge:build_network", {
        "EXTENT": EXTENT, "CUSTOM": plan, "OSM_FILE": str(GRID),
        "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)

    assert any("don't connect" in warning for warning in feedback.warnings)
    assert plan.selectedFeatureIds() == [stray]


def test_build_stops_on_a_bad_attribute_and_selects_the_feature(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    plan = line_layer(("cycleway", None, DIAGONAL), ("cycleway", "fast", FAR_AWAY))
    good, bad = sorted(f.id() for f in plan.getFeatures())

    with pytest.raises(QgsProcessingException) as raised:
        processing.run("networkforge:build_network", {
            "EXTENT": EXTENT, "CUSTOM": plan, "OSM_FILE": str(GRID),
            "OUTPUT_FOLDER": str(tmp_path / "out"),
        }, feedback=feedback)

    assert f"feature {bad}: maxspeed='fast'" in str(raised.value)
    assert real_engine.guide_url("fixing-tag-errors") in str(raised.value)
    assert plan.selectedFeatureIds() == [bad]
    assert not (tmp_path / "out" / "after.gpkg").exists()


def test_check_passes_good_lines_and_explains_bad_ones(
        provider, real_engine, feedback, qgis_new_project):
    plan = line_layer(("cycleway", "20", DIAGONAL), (None, None, FAR_AWAY))
    with_highway, without = sorted(f.id() for f in plan.getFeatures())

    with pytest.raises(QgsProcessingException, match=f"feature {without}: no highway tag"):
        processing.run("networkforge:check_layer", {"CUSTOM": plan}, feedback=feedback)
    assert plan.selectedFeatureIds() == [without]

    presets = list(real_engine.bundled_info()["presets"])
    results = processing.run("networkforge:check_layer", {
        "CUSTOM": plan, "PRESET": presets.index("footpath") + 1,
    }, feedback=feedback)
    assert results["FEATURES"] == 2


def test_build_changes_and_removes_existing_streets(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    # Row 0 (OSM way 1001) becomes one-way; row 1 (way 1002) is taken out.
    row_0 = [(-3.7000, 40.4000), (-3.6964, 40.4000)]
    row_1 = [(-3.7000, 40.4009), (-3.6964, 40.4009)]
    plan = line_layer(
        ("cycleway", None, DIAGONAL, None, None, None),
        (None, None, row_0, "1001", "yes", None),
        (None, None, row_1, "1002", None, "yes"),
        extra_fields=("osm_id", "oneway", "remove"),
    )

    results = processing.run("networkforge:build_network", {
        "EXTENT": EXTENT, "CUSTOM": plan, "OSM_FILE": str(GRID),
        "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)

    before = QgsVectorLayer(results["BEFORE"], "before", "ogr")
    after = QgsVectorLayer(results["AFTER"], "after", "ogr")
    changed = [f for f in after.getFeatures() if f["modified"] == "yes"]
    assert changed
    assert {f["osmid"] for f in changed} == {1001}
    assert {f["car_direction"] for f in changed} == {"forward"}
    assert {f["car_direction"] for f in before.getFeatures()} == {"both"}
    assert 1002 in {f["osmid"] for f in before.getFeatures()}
    assert 1002 not in {f["osmid"] for f in after.getFeatures()}
    # The engine's counts are rows of the layer: one per street segment.
    assert (f"After network: {after.featureCount()} street segments, of which "
            f"3 new and {len(changed)} changed.") in feedback.infos
    removed = sum(1 for f in before.getFeatures() if f["osmid"] == 1002)
    assert (f"Street segments removed: {removed}. They are in the Before network "
            "only.") in feedback.infos
    # OSM text on existing and changed streets alike (empty on a new line
    # that has no oneway attribute), never true/false.
    assert {f["oneway"] for f in changed} == {"yes"}
    assert {f["oneway"] for f in after.getFeatures() if f["oneway"]} == {"yes", "no"}


# Two streets that cross mid-way without a shared vertex, and one apart.
STREET = [(-3.7000, 40.4000), (-3.6960, 40.4000)]
CROSSING = [(-3.6980, 40.3990), (-3.6980, 40.4010)]


def test_standalone_network_joins_lines_where_they_cross(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    streets = line_layer(("residential", "30", STREET), ("residential", None, CROSSING))

    results = processing.run("networkforge:standalone_network", {
        "CUSTOM": streets, "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)

    network = QgsVectorLayer(results["NETWORK"], "network", "ogr")
    assert network.isValid()
    assert network.featureCount() == 4  # each street cut in two at the crossing
    assert "Network: 4 street segments." in feedback.infos
    names = [field.name() for field in network.fields()]
    for column in real_engine.bundled_info()["gpkg_edge_columns"]:
        assert column in names
    assert all(f["car"] and f["walk"] for f in network.getFeatures())
    assert Path(results["NETWORK_OSM"]).stat().st_size > 0
    assert not (tmp_path / "out" / "before.gpkg").exists()
    assert not feedback.warnings
    assert feedback.progress[-1] == 100


def test_standalone_network_joining_at_vertices_leaves_crossing_lines_apart(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    streets = line_layer(("residential", None, STREET), ("residential", None, CROSSING))
    join_at = real_engine.bundled_info()["join_at"]

    results = processing.run("networkforge:standalone_network", {
        "CUSTOM": streets, "JOIN_AT": join_at.index("vertices"),
        "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)

    assert QgsVectorLayer(results["NETWORK"], "network", "ogr").featureCount() == 2
    assert any("separate pieces" in warning for warning in feedback.warnings)
    assert len(streets.selectedFeatureIds()) == 1


def test_standalone_network_needs_a_kind_of_street_for_every_line(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    streets = line_layer(("residential", None, STREET), (None, None, CROSSING))
    with_highway, without = sorted(f.id() for f in streets.getFeatures())

    with pytest.raises(QgsProcessingException, match=f"feature {without}: no highway tag"):
        processing.run("networkforge:standalone_network", {
            "CUSTOM": streets, "OUTPUT_FOLDER": str(tmp_path / "out"),
        }, feedback=feedback)
    assert streets.selectedFeatureIds() == [without]

    presets = list(real_engine.bundled_info()["presets"])
    results = processing.run("networkforge:standalone_network", {
        "CUSTOM": streets, "PRESET": presets.index("residential_street") + 1,
        "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)
    assert QgsVectorLayer(results["NETWORK"], "network", "ogr").featureCount() == 4


# From row 1 heading east, left into the second column heading north, at
# the four-way junction of the two; and a line that crosses no junction.
LEFT_TURN = [(-3.6992, 40.4009), (-3.6988, 40.4009), (-3.6988, 40.4012)]
MID_BLOCK = [(-3.6996, 40.4009), (-3.6992, 40.4009)]


def test_build_adds_a_turn_restriction_drawn_through_a_junction(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    plan = line_layer((None, None, LEFT_TURN, "no_left_turn"),
                      extra_fields=("restriction",))

    results = processing.run("networkforge:build_network", {
        "EXTENT": EXTENT, "CUSTOM": plan, "OSM_FILE": str(GRID),
        "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)

    assert ("Turn restrictions added: 1. They are in after.osm.pbf for routers; "
            "the QGIS layers can't show them.") in feedback.infos
    assert not feedback.warnings
    # The restriction is in the router's file, not a line of the network.
    after = QgsVectorLayer(results["AFTER"], "after", "ogr")
    assert after.featureCount() == 24
    assert Path(results["AFTER_OSM"]).stat().st_size > Path(results["BEFORE_OSM"]).stat().st_size


def test_build_refuses_a_turn_restriction_that_is_on_no_junction(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    plan = line_layer((None, None, LEFT_TURN, "no_left_turn"),
                      (None, None, MID_BLOCK, "no_left_turn"),
                      extra_fields=("restriction",))
    good, bad = sorted(f.id() for f in plan.getFeatures())

    with pytest.raises(QgsProcessingException) as raised:
        processing.run("networkforge:build_network", {
            "EXTENT": EXTENT, "CUSTOM": plan, "OSM_FILE": str(GRID),
            "OUTPUT_FOLDER": str(tmp_path / "out"),
        }, feedback=feedback)

    assert "doesn't pass through a junction" in str(raised.value)
    assert real_engine.guide_url("turn-restrictions") in str(raised.value)
    assert plan.selectedFeatureIds() == [bad]


def test_standalone_network_takes_turn_restrictions_and_check_counts_them(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    turn = [(-3.6984, 40.4000), (-3.6980, 40.4000), (-3.6980, 40.4004)]
    streets = line_layer(("residential", None, STREET, None),
                         ("residential", None, CROSSING, None),
                         (None, None, turn, "no_left_turn"),
                         extra_fields=("restriction",))

    processing.run("networkforge:check_layer", {"CUSTOM": streets}, feedback=feedback)
    assert "  1 turn restriction(s)" in feedback.infos

    results = processing.run("networkforge:standalone_network", {
        "CUSTOM": streets, "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)

    assert any(info.startswith("Turn restrictions added: 1. They are in network.osm.pbf")
               for info in feedback.infos)
    assert QgsVectorLayer(results["NETWORK"], "network", "ogr").featureCount() == 4


def point_layer(*points, fields=("barrier",)):
    """A project layer of (x, y, *values of `fields`) points."""
    spec = "".join(f"&field={name}:string" for name in fields)
    layer = QgsVectorLayer(f"Point?crs=EPSG:4326{spec}", "points", "memory")
    features = []
    for x, y, *values in points:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        feature.setAttributes(values)
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    QgsProject.instance().addMapLayer(layer)
    return layer


def test_build_puts_points_on_the_network_without_any_lines(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    # A bollard half-way along a block, and signals on a junction.
    points = point_layer((-3.6982, 40.4000, "bollard", None),
                         (-3.6988, 40.4009, None, "traffic_signals"),
                         fields=("barrier", "highway"))

    results = processing.run("networkforge:build_network", {
        "EXTENT": EXTENT, "POINTS": points, "OSM_FILE": str(GRID),
        "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)

    assert any(info.startswith("Points put on the network: 2.") for info in feedback.infos)
    nodes = QgsVectorLayer(results["AFTER"].replace("layername=edges", "layername=nodes"),
                           "nodes", "ogr")
    assert nodes.isValid()
    assert "bollard" in {f["barrier"] for f in nodes.getFeatures()}
    # The bollard cut its block in two.
    assert QgsVectorLayer(results["AFTER"], "after", "ogr").featureCount() == 25
    assert not feedback.warnings


def test_a_point_that_is_not_on_a_street_is_named_and_selected(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    plan = line_layer(("cycleway", None, DIAGONAL))
    points = point_layer((-3.6982, 40.4000, "bollard"), (-3.6952, 40.4040, "bollard"))
    on_street, in_the_fields = sorted(f.id() for f in points.getFeatures())

    try:
        processing.run("networkforge:build_network", {
            "EXTENT": EXTENT, "CUSTOM": plan, "POINTS": points, "OSM_FILE": str(GRID),
            "OUTPUT_FOLDER": str(tmp_path / "out"),
        }, feedback=feedback)
        said = "\n".join(feedback.warnings)
    except QgsProcessingException as error:
        said = str(error)

    assert points.selectedFeatureIds() == [in_the_fields]
    assert f'The point concerned is now selected in "{points.name()}".' in said
    assert not plan.selectedFeatureIds()


def test_check_and_build_accept_a_ferry_and_a_deleted_tag(
        provider, real_engine, feedback, tmp_path, qgis_new_project):
    # A ferry corner to corner, and row 0 (way 1001) loses its speed limit.
    plan = line_layer(
        (None, None, DIAGONAL, "ferry", "00:05", None, None),
        (None, None, [(-3.7000, 40.4000), (-3.6964, 40.4000)], None, None, "1001", "maxspeed"),
        extra_fields=("route", "duration", "osm_id", "remove_tags"),
    )

    checked = processing.run("networkforge:check_layer", {"CUSTOM": plan}, feedback=feedback)
    assert checked["FEATURES"] == 2

    results = processing.run("networkforge:build_network", {
        "EXTENT": EXTENT, "CUSTOM": plan, "OSM_FILE": str(GRID),
        "OUTPUT_FOLDER": str(tmp_path / "out"),
    }, feedback=feedback)

    after = QgsVectorLayer(results["AFTER"], "after", "ogr")
    ferries = [f for f in after.getFeatures() if f["route"] == "ferry"]
    assert len(ferries) == 1 and ferries[0]["custom"] == "yes"
    row_0 = [f for f in after.getFeatures() if f["osmid"] == 1001]
    assert row_0 and all(f["modified"] == "yes" and not f["maxspeed"] for f in row_0)
