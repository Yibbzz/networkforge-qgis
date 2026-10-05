"""Build standalone network: what it asks of the engine and how it reports back."""

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

from networkforge_qgis import engine
from networkforge_qgis.algorithms.common import ID_FIELD

ALGORITHM = "networkforge:standalone_network"
DONE = {"event": "done", "outputs": {}, "nodes": 4, "edges": 3, "custom_edges": 3,
        "modified_edges": 0, "removed_edges": 0}


@pytest.fixture
def lines(qgis_new_project):
    """Three streets in the project."""
    layer = QgsVectorLayer(
        "LineString?crs=EPSG:4326&field=highway:string&field=maxspeed:string",
        "streets", "memory",
    )
    features = []
    for i in range(3):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY(
            [QgsPointXY(-3.69 + i / 100, 40.41), QgsPointXY(-3.68 + i / 100, 40.42)]
        ))
        feature.setAttributes(["residential", None])
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
            {"CUSTOM": lines, "OUTPUT_FOLDER": str(tmp_path / "out"), **parameters},
            feedback=feedback,
        )

    return run


def test_default_command(build, fake_engine, tmp_path):
    build()

    args = fake_engine.args
    assert args[:3] == ["build", "--json", "--no-osm"]
    assert fake_engine.value("--join-at") == "crossings"
    assert fake_engine.value("--id-field") == ID_FIELD
    assert float(fake_engine.value("--snap-tolerance")) == 1.0
    out = tmp_path / "out"
    assert fake_engine.value("--gpkg") == str(out / "network.gpkg")
    assert fake_engine.value("--out") == str(out / "network.osm.pbf")
    # The engine refuses these with --no-osm (exit code 2).
    for absent in ("--extent", "--osm-source", "--baseline-out", "--baseline-gpkg",
                   "--network-type", "--preset", "--tag", "--overwrite-tags"):
        assert absent not in args
    assert not [a for a in args if a.startswith("--bbox")]


def test_results_name_the_edges_layer_and_pbf_file(build, tmp_path):
    results = build()

    out = tmp_path / "out"
    assert results["NETWORK"] == f"{out / 'network.gpkg'}|layername=edges"
    assert results["NETWORK_OSM"] == str(out / "network.osm.pbf")


def test_every_way_of_joining_in_the_form_reaches_the_engine_by_name(build, fake_engine):
    for index, name in enumerate(engine.bundled_info()["join_at"]):
        build(JOIN_AT=index)
        assert fake_engine.value("--join-at") == name


def test_preset_tags_and_options(build, fake_engine):
    presets = list(engine.bundled_info()["presets"])

    build(
        PRESET=presets.index("residential_street") + 1,  # 0 is "use feature attributes"
        MAXSPEED="20 mph",
        EXTRA_TAGS="lit=yes",
        OVERWRITE=True,
        SNAP_TOLERANCE=5,
    )

    assert fake_engine.value("--preset") == "residential_street"
    assert fake_engine.values("--tag") == ["maxspeed=20 mph", "lit=yes"]
    assert "--overwrite-tags" in fake_engine.args
    assert float(fake_engine.value("--snap-tolerance")) == 5.0


def test_the_form_has_no_area_or_openstreetmap_settings(provider):
    from qgis.core import QgsApplication

    algorithm = QgsApplication.processingRegistry().algorithmById(ALGORITHM)
    names = [definition.name() for definition in algorithm.parameterDefinitions()]
    for absent in ("EXTENT", "OSM_FILE", "NETWORK_TYPE"):
        assert absent not in names


def test_results_of_an_earlier_run_are_cleared_first(build, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    old = [out / "network.gpkg", out / "network.osm.pbf"]
    for path in old:
        path.write_text("old")
    scenario = out / "after.gpkg"
    scenario.write_text("another tool's")

    build()

    assert not any(path.exists() for path in old)
    assert scenario.exists()


def test_separate_pieces_warn_and_select_the_lines_outside_the_largest(
        build, fake_engine, feedback, lines):
    stray = sorted(f.id() for f in lines.getFeatures())[2]
    fake_engine.play([
        {"event": "warning", "message": "The network is in 2 separate pieces.",
         "features": [stray]},
        DONE,
    ])

    build()

    assert feedback.warnings[0] == "The network is in 2 separate pieces."
    assert lines.selectedFeatureIds() == [stray]


def test_engine_error_links_the_guide_and_selects_the_feature(build, fake_engine, lines):
    first = sorted(f.id() for f in lines.getFeatures())[0]
    fake_engine.play([{
        "event": "error", "type": "InvalidTagsError", "guide": "fixing-tag-errors",
        "message": "1 custom tag problem(s):\n  - feature 1: no highway tag",
        "issues": [{"feature": first, "message": "no highway tag"}],
    }], exit_code=3)

    with pytest.raises(QgsProcessingException) as raised:
        build()

    assert engine.guide_url("fixing-tag-errors") in str(raised.value)
    assert lines.selectedFeatureIds() == [first]
