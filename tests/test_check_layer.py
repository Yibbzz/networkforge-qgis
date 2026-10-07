"""Check custom network layer: the engine's `check` command and its answers."""

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

ALGORITHM = "networkforge:check_layer"
DONE = {"event": "done", "features": 2, "modes": {"walk, bike": 1, "nothing": 1}, "edits": 0,
        "turn_restrictions": 0}


@pytest.fixture
def lines(qgis_new_project):
    layer = QgsVectorLayer("LineString?crs=EPSG:4326&field=highway:string", "plan", "memory")
    features = []
    for i in range(2):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY(
            [QgsPointXY(-3.69 + i / 100, 40.41), QgsPointXY(-3.68 + i / 100, 40.42)]
        ))
        feature.setAttributes(["cycleway"])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    QgsProject.instance().addMapLayer(layer)
    return layer


def test_checks_without_an_area_by_default(provider, fake_engine, lines, feedback):
    fake_engine.play([DONE])

    results = processing.run(ALGORITHM, {"CUSTOM": lines}, feedback=feedback)

    args = fake_engine.args
    assert args[:2] == ["check", "--json"]
    assert fake_engine.value("--id-field") == ID_FIELD
    assert fake_engine.value("--network-type") == "all"
    assert not [a for a in args if a.startswith("--bbox")]
    assert "--preset" not in args
    assert results["FEATURES"] == 2
    assert "No problems found in 2 feature(s)." in feedback.infos
    assert "  1 usable by: walk, bike" in feedback.infos


def test_changes_and_turn_restrictions_are_counted(provider, fake_engine, lines, feedback):
    fake_engine.play([dict(DONE, features=5, edits=2, turn_restrictions=1)])

    processing.run(ALGORITHM, {"CUSTOM": lines}, feedback=feedback)

    assert "  2 change existing streets" in feedback.infos
    assert "  1 turn restriction(s)" in feedback.infos


def test_area_preset_and_tags_are_passed_on(provider, fake_engine, lines, feedback):
    fake_engine.play([DONE])
    presets = list(engine.bundled_info()["presets"])

    processing.run(ALGORITHM, {
        "CUSTOM": lines, "EXTENT": "-3.70,-3.60,40.40,40.45 [EPSG:4326]",
        "PRESET": presets.index("cycleway") + 1, "MAXSPEED": "20", "OVERWRITE": True,
    }, feedback=feedback)

    assert "--bbox=-3.7000000,40.4000000,-3.6000000,40.4500000" in fake_engine.args
    assert fake_engine.value("--preset") == "cycleway"
    assert fake_engine.values("--tag") == ["maxspeed=20"]
    assert "--overwrite-tags" in fake_engine.args


def test_problems_stop_the_tool_and_select_the_features(provider, fake_engine, lines, feedback):
    second = sorted(f.id() for f in lines.getFeatures())[1]
    fake_engine.play([{
        "event": "error", "type": "InvalidTagsError", "guide": "fixing-tag-errors",
        "message": "1 custom tag problem(s):\n  - feature 2: no highway tag",
        "issues": [{"feature": second, "message": "no highway tag"}],
    }], exit_code=3)

    with pytest.raises(QgsProcessingException) as raised:
        processing.run(ALGORITHM, {"CUSTOM": lines}, feedback=feedback)

    assert f"  - feature {second}: no highway tag" in str(raised.value)
    assert engine.guide_url("fixing-tag-errors") in str(raised.value)
    assert lines.selectedFeatureIds() == [second]
