"""Build scenario network: what it asks of the engine and how it reports back."""

import pytest
from qgis import processing
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingException,
    QgsProcessingFeatureSourceDefinition,
    QgsProject,
    QgsVectorLayer,
)

from networkforge_qgis import engine
from networkforge_qgis.algorithms.common import ID_FIELD, parse_tags

ALGORITHM = "networkforge:build_network"
# West of Greenwich, so the western longitude is negative.
EXTENT = "-3.70,-3.60,40.40,40.45 [EPSG:4326]"
DONE = {"event": "done", "outputs": {}, "nodes": 1, "edges": 2, "custom_edges": 1,
        "modified_edges": 0, "removed_edges": 0}


@pytest.fixture
def lines(qgis_new_project):
    """Three lines in the project, with an "fid" field that must not be exported."""
    layer = QgsVectorLayer(
        "LineString?crs=EPSG:4326&field=highway:string&field=maxspeed:string&field=fid:integer",
        "plan", "memory",
    )
    features = []
    for i, highway in enumerate(["cycleway", "residential", None]):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY(
            [QgsPointXY(-3.69 + i / 100, 40.41), QgsPointXY(-3.68 + i / 100, 40.42)]
        ))
        feature.setAttributes([highway, None, 100 + i])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    QgsProject.instance().addMapLayer(layer)
    return layer


@pytest.fixture
def build(provider, fake_engine, lines, feedback, tmp_path):
    """Run the tool with sensible defaults; keyword arguments override them."""
    fake_engine.play([DONE])

    def run(**parameters):
        return processing.run(
            ALGORITHM,
            {"EXTENT": EXTENT, "CUSTOM": lines, "OUTPUT_FOLDER": str(tmp_path / "out"),
             **parameters},
            feedback=feedback,
        )

    return run


def exported(fake_engine):
    """The file of custom lines the engine was given, as a layer."""
    layer = QgsVectorLayer(fake_engine.value("--custom"), "exported", "ogr")
    assert layer.isValid()
    return layer


@pytest.mark.parametrize("text, expected", [
    ("", []),
    (None, []),
    ("lanes=2", ["lanes=2"]),
    (" lanes = 2 ;bicycle=no;", ["lanes=2", "bicycle=no"]),
    ("maxspeed=30 mph\nlit=yes", ["maxspeed=30 mph", "lit=yes"]),
])
def test_parse_tags(text, expected):
    assert parse_tags(text) == expected


@pytest.mark.parametrize("text", ["lanes", "=2", "lanes=", "lanes=2; oops"])
def test_parse_tags_rejects_what_is_not_key_value(text):
    with pytest.raises(ValueError):
        parse_tags(text)


def test_default_command(build, fake_engine, tmp_path):
    build()

    args = fake_engine.args
    assert args[:2] == ["build", "--json"]
    assert "--bbox=-3.7000000,40.4000000,-3.6000000,40.4500000" in args
    assert fake_engine.value("--id-field") == ID_FIELD
    assert fake_engine.value("--network-type") == "all"
    assert float(fake_engine.value("--snap-tolerance")) == 1.0
    out = tmp_path / "out"
    assert fake_engine.value("--baseline-gpkg") == str(out / "before.gpkg")
    assert fake_engine.value("--gpkg") == str(out / "after.gpkg")
    assert fake_engine.value("--baseline-out") == str(out / "before.osm.pbf")
    assert fake_engine.value("--out") == str(out / "after.osm.pbf")
    for absent in ("--preset", "--tag", "--overwrite-tags", "--osm-source", "--no-strict"):
        assert absent not in args


def test_extent_in_another_crs_is_sent_as_longitude_latitude(build, fake_engine):
    build(EXTENT="-411000,-400000,4920000,4930000 [EPSG:3857]")

    bbox = next(a for a in fake_engine.args if a.startswith("--bbox="))
    west, south, east, north = (float(v) for v in bbox.split("=")[1].split(","))
    assert -3.70 < west < east < -3.59
    assert 40.3 < south < north < 40.5


def test_results_name_the_edges_layers_and_pbf_files(build, tmp_path):
    results = build()

    out = tmp_path / "out"
    assert results["BEFORE"] == f"{out / 'before.gpkg'}|layername=edges"
    assert results["AFTER"] == f"{out / 'after.gpkg'}|layername=edges"
    assert results["BEFORE_OSM"] == str(out / "before.osm.pbf")
    assert results["AFTER_OSM"] == str(out / "after.osm.pbf")


def test_preset_tags_and_options(build, fake_engine, tmp_path):
    presets = list(engine.bundled_info()["presets"])
    network_types = engine.bundled_info()["network_types"]
    osm = tmp_path / "area.osm.pbf"
    osm.write_bytes(b"")

    build(
        PRESET=presets.index("primary_road") + 1,  # 0 is "use feature attributes"
        MAXSPEED=" 30 mph ",
        EXTRA_TAGS="lanes=2; bicycle=no",
        OVERWRITE=True,
        NETWORK_TYPE=network_types.index("drive"),
        OSM_FILE=str(osm),
        SNAP_TOLERANCE=2.5,
    )

    assert fake_engine.value("--preset") == "primary_road"
    assert fake_engine.values("--tag") == ["maxspeed=30 mph", "lanes=2", "bicycle=no"]
    assert "--overwrite-tags" in fake_engine.args
    assert fake_engine.value("--network-type") == "drive"
    assert fake_engine.value("--osm-source") == str(osm)
    assert float(fake_engine.value("--snap-tolerance")) == 2.5


def test_every_preset_in_the_form_reaches_the_engine_by_name(build, fake_engine):
    for index, name in enumerate(engine.bundled_info()["presets"], start=1):
        build(PRESET=index)
        assert fake_engine.value("--preset") == name


def test_exported_lines_carry_their_qgis_feature_ids(build, fake_engine, lines):
    build()

    layer = exported(fake_engine)
    names = [field.name() for field in layer.fields()]
    assert "highway" in names and "maxspeed" in names
    assert names.count("fid") <= 1  # only the GeoPackage's own id column
    ids = sorted(f[ID_FIELD] for f in layer.getFeatures())
    assert ids == sorted(f.id() for f in lines.getFeatures())
    by_id = {f[ID_FIELD]: f["highway"] for f in layer.getFeatures()}
    assert by_id == {f.id(): f["highway"] for f in lines.getFeatures()}
    assert layer.crs().authid() == "EPSG:4326"


def test_selected_features_only(build, fake_engine, lines):
    chosen = sorted(f.id() for f in lines.getFeatures())[1]
    lines.selectByIds([chosen])

    build(CUSTOM=QgsProcessingFeatureSourceDefinition(lines.id(), True))

    assert [f[ID_FIELD] for f in exported(fake_engine).getFeatures()] == [chosen]


def test_a_layer_with_no_features_is_refused(build, lines):
    lines.dataProvider().truncate()

    with pytest.raises(QgsProcessingException, match="no features"):
        build()


def test_other_tags_must_be_key_value(build):
    with pytest.raises(QgsProcessingException, match="should look like key=value"):
        build(EXTRA_TAGS="lanes")


def test_progress_and_warnings_reach_the_user(build, fake_engine, feedback):
    fake_engine.play([
        {"event": "progress", "step": 1, "total": 4, "message": "Checking"},
        {"event": "progress", "step": 3, "total": 4, "message": "Snapping"},
        {"event": "warning", "message": "1 custom feature(s) don't connect", "features": [2]},
        DONE,
    ])

    build()

    assert feedback.progress == [0, 50, 100]
    assert feedback.progress_texts[:2] == ["Checking", "Snapping"]
    assert feedback.warnings[0] == "1 custom feature(s) don't connect"


def test_removed_streets_are_mentioned(build, fake_engine, feedback):
    note = "Streets were removed: they are in the Before network only."
    build()
    assert note not in feedback.infos

    fake_engine.play([dict(DONE, removed_edges=2)])
    build()
    assert note in feedback.infos


def test_fields_that_change_existing_streets_are_exported(build, fake_engine, lines):
    # The engine reads these from the file: osm_id / osmid name the street
    # a feature changes, and remove=yes takes it out.
    info = engine.bundled_info()
    wanted = [*info["edit_id_fields"], info["remove_field"]]
    lines.dataProvider().addAttributes(
        [QgsField(name, lines.fields().at(0).type()) for name in wanted])
    lines.updateFields()

    build()

    names = [field.name() for field in exported(fake_engine).fields()]
    for name in wanted:
        assert name in names


def test_engine_error_lists_the_features_and_links_the_guide(build, fake_engine):
    fake_engine.play([{
        "event": "error", "type": "InvalidTagsError", "guide": "fixing-tag-errors",
        "message": "2 custom tag problem(s):\n  - feature 7: no highway tag\n"
                   "(see docs/tagging-guide.md#fixing-tag-errors)",
        "issues": [{"feature": 7, "message": "no highway tag"},
                   {"feature": None, "message": "something about the whole layer"}],
    }], exit_code=3)

    with pytest.raises(QgsProcessingException) as raised:
        build()

    text = str(raised.value)
    assert "2 custom tag problem(s):" in text
    assert text.count("no highway tag") == 1
    assert "  - feature 7: no highway tag" in text
    assert "  - something about the whole layer" in text
    assert engine.guide_url("fixing-tag-errors") in text


def test_engine_error_without_issues_keeps_the_whole_message(build, fake_engine):
    fake_engine.play([{"event": "error", "type": "OSMDownloadError",
                       "message": "The download failed.\nTry again later."}], exit_code=4)

    with pytest.raises(QgsProcessingException, match="Try again later"):
        build()


def test_engine_crash_points_at_the_log(build, fake_engine):
    fake_engine.play(exit_code=1)

    with pytest.raises(QgsProcessingException) as raised:
        build()

    assert "exit code 1" in str(raised.value)
    assert str(engine.log_path()) in str(raised.value)


def test_results_of_an_earlier_run_are_cleared_first(build, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    old = [out / name for name in
           ("before.gpkg", "after.gpkg", "before.osm.pbf", "after.osm.pbf")]
    for path in old:
        path.write_text("old")
    keep = out / "notes.txt"
    keep.write_text("mine")

    build()

    assert not any(path.exists() for path in old)
    assert keep.exists()


def test_area_over_the_download_limit_warns_unless_an_osm_file_is_given(
        build, feedback, tmp_path):
    big = "-4.5,-3.5,40.0,41.0 [EPSG:4326]"  # roughly 9,000 km2

    build(EXTENT=big)
    assert any("too big to download" in w for w in feedback.warnings)

    feedback.warnings.clear()
    osm = tmp_path / "area.osm.pbf"
    osm.write_bytes(b"")
    build(EXTENT=big, OSM_FILE=str(osm))
    assert not feedback.warnings


def test_warning_selects_the_features_it_is_about(build, fake_engine, feedback, lines):
    first, second, third = sorted(f.id() for f in lines.getFeatures())
    lines.selectByIds([first])
    fake_engine.play([
        {"event": "warning", "message": "Don't connect", "features": [third]},
        {"event": "warning", "message": "Set aside a field", "fields": ["length"]},
        {"event": "warning", "message": "Odd", "features": [second, third]},
        DONE,
    ])

    build()

    assert sorted(lines.selectedFeatureIds()) == [second, third]
    assert feedback.warnings[-1] == 'The 2 features concerned are now selected in "plan".'


def test_error_selects_the_broken_features(build, fake_engine, lines):
    first, second, third = sorted(f.id() for f in lines.getFeatures())
    fake_engine.play([
        {"event": "warning", "message": "Odd", "features": [first]},
        {"event": "error", "type": "InvalidTagsError", "guide": "fixing-tag-errors",
         "message": "1 custom tag problem(s):\n  - feature 3: no highway tag",
         "issues": [{"feature": third, "message": "no highway tag"},
                    {"feature": None, "message": "about the whole layer"}]},
    ], exit_code=3)

    with pytest.raises(QgsProcessingException) as raised:
        build()

    assert lines.selectedFeatureIds() == [third]
    assert 'The feature concerned is now selected in "plan".' in str(raised.value)


def test_selection_is_left_alone_when_nothing_is_wrong(build, lines):
    chosen = sorted(f.id() for f in lines.getFeatures())[:2]
    lines.selectByIds(chosen)

    build()

    assert sorted(lines.selectedFeatureIds()) == chosen


def test_a_layer_given_as_a_file_is_not_selected_in(build, fake_engine, feedback, tmp_path):
    path = tmp_path / "plan.geojson"
    path.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"properties":{"highway":"cycleway"},"geometry":{"type":"LineString",'
        '"coordinates":[[-3.69,40.41],[-3.68,40.42]]}}]}'
    )
    fake_engine.play([{"event": "warning", "message": "Don't connect", "features": [0]}, DONE])

    build(CUSTOM=str(path))

    assert feedback.warnings == ["Don't connect"]


def test_selection_works_when_run_in_the_background_like_the_toolbox_does(
        provider, fake_engine, lines, feedback, tmp_path, qgis_app):
    import time

    from qgis.core import QgsApplication, QgsProcessingAlgRunnerTask, QgsProcessingContext

    third = sorted(f.id() for f in lines.getFeatures())[2]
    fake_engine.play([{"event": "warning", "message": "Don't connect", "features": [third]},
                      DONE])
    algorithm = QgsApplication.processingRegistry().algorithmById(ALGORITHM)
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    task = QgsProcessingAlgRunnerTask(
        algorithm,
        {"EXTENT": EXTENT, "CUSTOM": lines, "OUTPUT_FOLDER": str(tmp_path / "out")},
        context, feedback,
    )
    finished = []
    task.executed.connect(lambda ok, results: finished.append(ok))
    QgsApplication.taskManager().addTask(task)

    deadline = time.monotonic() + 60
    while not finished and time.monotonic() < deadline:
        qgis_app.processEvents()
        time.sleep(0.01)
    qgis_app.processEvents()

    assert finished == [True]
    assert lines.selectedFeatureIds() == [third]
