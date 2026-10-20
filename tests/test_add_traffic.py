"""Add traffic: what it asks of the engine and how it reports back."""

import json
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

from networkforge_qgis.algorithms.add_traffic import EXAMPLE_BANDS, bands_from_table
from networkforge_qgis.algorithms.common import ID_FIELD

ALGORITHM = "networkforge:add_traffic"
DONE = {"event": "done", "outputs": {"tar": "x.tar"}, "streets": 12, "segments": 30,
        "by_road": {"primary": 8, "secondary": 4}, "bands": ["Morning peak", "Evening peak"],
        "streets_not_found": [], "single_streets": 0, "single_segments": 0, "unmatched": []}


@pytest.fixture
def network(tmp_path):
    pbf = tmp_path / "after.osm.pbf"
    pbf.write_bytes(b"not read by the fake engine")
    return pbf


@pytest.fixture
def streets(qgis_new_project):
    """Two single streets in the project."""
    layer = QgsVectorLayer(
        "LineString?crs=EPSG:4326&field=days:string&field=time:string&field=factor:double"
        "&field=direction:string&field=osmid:integer&field=fid:integer",
        "busy streets", "memory",
    )
    features = []
    for i, (days, factor) in enumerate((("Mo-Fr", 0.5), ("Sa", 0.8))):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY(
            [QgsPointXY(-0.97 + i / 100, 51.45), QgsPointXY(-0.96 + i / 100, 51.45)]))
        feature.setAttributes([days, "07:00-09:30", factor, "forward", None, 99])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    QgsProject.instance().addMapLayer(layer)
    return layer


@pytest.fixture
def run(provider, fake_engine, network, feedback, tmp_path):
    fake_engine.play([DONE])

    def _run(**parameters):
        return processing.run(
            ALGORITHM,
            {"NETWORK_FILE": str(network), "OUTPUT": str(tmp_path / "after.tar"),
             **parameters},
            feedback=feedback,
        )
    return _run


def settings_sent(fake_engine):
    return json.loads(Path(fake_engine.value("--settings")).read_text(encoding="utf-8"))


def test_default_command_and_the_example_bands(run, fake_engine, network, tmp_path):
    results = run()

    assert fake_engine.args[:2] == ["traffic", "--json"]
    assert fake_engine.value("--pbf") == str(network)
    assert fake_engine.value("--out") == str(tmp_path / "after.tar")
    assert "--streets" not in fake_engine.args
    assert settings_sent(fake_engine) == {"band": [
        {"name": "Morning peak", "days": "Mo-Fr", "time": "07:00-09:30",
         "roads": ["motorway", "trunk", "primary", "secondary"], "factor": 0.6},
        {"name": "Evening peak", "days": "Mo-Fr", "time": "16:00-18:30",
         "roads": ["motorway", "trunk", "primary", "secondary"], "factor": 0.6},
    ]}
    assert results["OUTPUT"] == str(tmp_path / "after.tar")


def test_the_log_says_what_was_done_and_how_to_use_it(run, feedback):
    run()
    log = "\n".join(feedback.infos)
    assert "Streets with traffic: 12 (30 road segments)." in log
    assert "By road class: 8 primary, 4 secondary." in log
    assert "From Tar" in log


def test_an_output_without_tar_gets_it(run, fake_engine, tmp_path):
    run(OUTPUT=str(tmp_path / "after"))
    assert fake_engine.value("--out") == str(tmp_path / "after.tar")


def test_single_streets_are_exported_with_their_qgis_ids(run, fake_engine, streets):
    run(STREETS=streets)

    assert fake_engine.value("--id-field") == ID_FIELD
    exported = QgsVectorLayer(fake_engine.value("--streets"), "exported", "ogr")
    rows = sorted((f[ID_FIELD], f["days"], f["factor"], f["direction"])
                  for f in exported.getFeatures())
    assert rows == [(1, "Mo-Fr", 0.5, "forward"), (2, "Sa", 0.8, "forward")]
    # The layer's own "fid" field isn't copied: it would clash with the
    # GeoPackage's ids.
    assert [f.name() for f in exported.fields()].count("fid") == 1


def test_streets_alone_need_no_bands(run, fake_engine, streets):
    run(BANDS=[], STREETS=streets)
    assert "--settings" not in fake_engine.args
    assert "--streets" in fake_engine.args


def test_nothing_to_add_is_refused_before_running(run, fake_engine):
    with pytest.raises(QgsProcessingException, match="at least one time band"):
        run(BANDS=[])


def test_streets_a_warning_names_are_selected(run, fake_engine, streets, feedback):
    fake_engine.play([
        {"event": "warning", "message": "1 single street(s) run along no road segment",
         "features": [2]},
        {**DONE, "single_streets": 1, "single_segments": 2, "unmatched": [2]},
    ])
    run(STREETS=streets)

    assert [f.id() for f in streets.selectedFeatures()] == [2]
    assert any("now selected in \"busy streets\"" in w for w in feedback.warnings)
    assert "Single streets: 1 (2 road segments)." in "\n".join(feedback.infos)


def test_an_engine_error_names_the_streets(run, fake_engine, streets):
    fake_engine.play([{
        "event": "error", "type": "InputError",
        "message": "1 single-street problem(s):\n  - feature 1: time must be like '07:00-09:30'",
        "guide": "traffic.md#single-streets",
        "issues": [{"feature": 1, "message": "time must be like '07:00-09:30'"}],
    }], exit_code=3)
    with pytest.raises(QgsProcessingException) as raised:
        run(STREETS=streets)
    assert "feature 1: time must be like" in str(raised.value)
    assert "traffic.md#single-streets" in str(raised.value)
    assert [f.id() for f in streets.selectedFeatures()] == [1]


@pytest.mark.parametrize(("cells", "expected"), [
    (EXAMPLE_BANDS[:5], [{"name": "Morning peak", "days": "Mo-Fr", "time": "07:00-09:30",
                          "roads": ["motorway", "trunk", "primary", "secondary"],
                          "factor": 0.6}]),
    (["", "", "07:00-09:00", "primary; trunk", "0,5"],
     [{"time": "07:00-09:00", "roads": ["primary", "trunk"], "factor": 0.5}]),
    (["", "", "", "", "", "Night", "", "22:00-05:00", "all", "1.1"],
     [{"name": "Night", "time": "22:00-05:00", "roads": ["all"], "factor": 1.1}]),
    (["x", "Mo", "07:00-08:00", "primary", "fast"],
     [{"name": "x", "days": "Mo", "time": "07:00-08:00", "roads": ["primary"],
       "factor": "fast"}]),
])
def test_bands_from_the_table(cells, expected):
    assert bands_from_table(cells) == expected
