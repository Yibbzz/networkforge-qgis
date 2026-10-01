"""Running the engine as a separate program: environment, events, cancel."""

import threading
import time

import pytest

from networkforge_qgis import engine


def test_clean_env_drops_qgis_python_settings(monkeypatch, tmp_path):
    # PYTHONEXECUTABLE made uv install into the wrong Python on Windows.
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE",
                 "__PYVENV_LAUNCHER__", "VIRTUAL_ENV", "GDAL_DATA", "PROJ_LIB"):
        monkeypatch.setenv(name, "from-qgis")
    monkeypatch.setenv("NF_KEEP_ME", "yes")

    env = engine._clean_env()

    assert not [k for k in env if k.upper().startswith("PYTHON") and k != "PYTHONUTF8"]
    for name in ("__PYVENV_LAUNCHER__", "VIRTUAL_ENV", "GDAL_DATA", "PROJ_LIB"):
        assert name not in env
    assert env["PYTHONUTF8"] == "1"
    assert env["NF_KEEP_ME"] == "yes"
    assert "PATH" in env


def test_clean_env_drops_certificate_paths_that_do_not_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path))

    env = engine._clean_env()

    assert "SSL_CERT_DIR" not in env
    assert env["SSL_CERT_FILE"] == str(tmp_path)


def test_guide_url_points_at_the_pinned_version():
    docs = f"{engine.ENGINE_REPO}/blob/v{engine.ENGINE_VERSION}/docs"
    assert engine.guide_url("fixing-tag-errors") == (
        f"{docs}/tagging-guide.md#fixing-tag-errors"
    )
    assert engine.guide_url("osm-data.md#large-areas") == f"{docs}/osm-data.md#large-areas"


def test_bundled_info_is_for_the_pinned_version():
    info = engine.bundled_info()
    assert info["version"] == engine.ENGINE_VERSION
    for key in ("presets", "network_types", "max_overpass_area_km2", "osm_formats",
                "tag_values", "tag_patterns"):
        assert key in info
    assert "all" in info["network_types"]


def test_run_passes_events_on_in_order(fake_engine, feedback):
    events = [
        {"event": "progress", "step": 1, "total": 2, "message": "One"},
        {"event": "warning", "message": "Careful", "features": [7]},
        {"event": "done", "outputs": {}},
    ]
    fake_engine.play([events[0], "not json at all", events[1], "", events[2]])
    seen = []

    code = engine.run(["build", "--json", 5], feedback, seen.append)

    assert code == 0
    assert seen == events
    assert fake_engine.args == ["build", "--json", "5"]
    log = engine.log_path().read_text(encoding="utf-8")
    assert "not json at all" in log
    assert "fake engine log line" in log  # the engine's stderr


def test_run_returns_the_exit_code(fake_engine, feedback):
    fake_engine.play(exit_code=3)
    assert engine.run(["check"], feedback, lambda event: None) == 3


def test_run_stops_quickly_when_cancelled(fake_engine, feedback):
    fake_engine.play([{"event": "progress", "step": 1, "total": 2, "message": "Slow"}],
                     sleep=60)
    threading.Timer(0.5, feedback.cancel).start()
    started = time.monotonic()

    with pytest.raises(engine.EngineCanceled):
        engine.run(["build"], feedback, lambda event: None)

    assert time.monotonic() - started < 10


def test_run_explains_an_engine_that_will_not_start(fake_engine, feedback, monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "_engine_cmd", lambda: [str(tmp_path / "missing-program")])

    with pytest.raises(engine.EngineError, match="Could not start the engine"):
        engine.run(["build"], feedback, lambda event: None)


def test_installed_version_is_none_without_an_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "base_dir", lambda: tmp_path)
    assert engine.installed_version() is None
