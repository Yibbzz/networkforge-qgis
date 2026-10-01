"""Engine information: shows what the installed engine reports."""

from qgis import processing
from qgis.core import QgsApplication

from networkforge_qgis import engine

ALGORITHM = "networkforge:engine_info"


def test_tool_has_an_input_so_qgis_shows_its_window(provider):
    # QGIS runs a tool with no inputs without its window, hiding the log.
    algorithm = QgsApplication.processingRegistry().algorithmById(ALGORITHM)
    assert algorithm.countVisibleParameters() > 0


def test_reports_what_the_engine_says(provider, fake_engine, feedback):
    fake_engine.play([dict(engine.bundled_info(), version="9.9.9")])

    results = processing.run(ALGORITHM, {}, feedback=feedback)

    assert results["ENGINE_VERSION"] == "9.9.9"
    assert fake_engine.args == ["info", "--json"]
    assert any("9.9.9" in line for line in feedback.infos)


def test_reinstall_installs_again(provider, fake_engine, feedback, monkeypatch):
    fake_engine.play([engine.bundled_info()])
    calls = []
    monkeypatch.setattr(engine, "install", lambda feedback=None: calls.append("install"))

    processing.run(ALGORITHM, {"REINSTALL": True}, feedback=feedback)

    assert calls == ["install"]
