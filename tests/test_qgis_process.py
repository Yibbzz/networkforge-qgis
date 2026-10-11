"""The plugin as a new user gets it: loaded by QGIS itself, nothing installed.

The other tests import the plugin's code into pytest. These start the
real QGIS (`qgis_process`, QGIS without its windows) with a brand new
profile folder that holds a copy of the plugin, the way QGIS's plugin
manager installs it. The profile folder and the data folders have a
space in their names, as "C:\\Users\\Ann Lee" and "My Documents" do on
Windows.

Folders with accents are tried in test_end_to_end.py instead: on Windows
`qgis_process` is a .bat file, which can garble an accent before QGIS
ever sees it. That would be a fault of this test, not of the plugin.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from qgis.core import (
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from networkforge_qgis import engine

PLUGIN = Path(__file__).parent.parent / "networkforge_qgis"
TOOLS = ("build_network", "check_layer", "engine_info", "standalone_network")
# The program's name on Linux and macOS, then in the Windows installers
# (long-term release, latest release).
PROGRAMS = ("qgis_process", "qgis_process-qgis-ltr", "qgis_process-qgis")


def _without_uv(path):
    """PATH minus the folders that hold uv, so the plugin has to fetch it."""
    folders = [folder for folder in path.split(os.pathsep)
               if folder and not any((Path(folder) / name).exists()
                                     for name in ("uv", "uv.exe"))]
    return os.pathsep.join(folders)


@pytest.fixture(scope="module")
def qgis_process(tmp_path_factory):
    """Run `qgis_process` with a new profile that has the plugin switched on."""
    program = os.environ.get("NF_QGIS_PROCESS") or next(
        (found for found in map(shutil.which, PROGRAMS) if found), None)
    if program is None:
        message = ("qgis_process was not found: put QGIS's bin folder on PATH "
                   "or set NF_QGIS_PROCESS to the program")
        # On GitHub a skipped test would look like a pass.
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)

    config = tmp_path_factory.mktemp("QGIS profiles")
    profile = config / "profiles" / "default"
    shutil.copytree(PLUGIN, profile / "python" / "plugins" / PLUGIN.name,
                    ignore=shutil.ignore_patterns("__pycache__"))
    env = dict(os.environ)
    env["QGIS_CUSTOM_CONFIG_PATH"] = str(config)
    env["PATH"] = _without_uv(env.get("PATH", ""))

    def run(*args, timeout=300):
        command = [program, *[str(a) for a in args]]
        if os.name == "nt" and program.lower().endswith((".bat", ".cmd")):
            # A .bat file is run by cmd.exe, which misreads a quoted program
            # followed by quoted arguments ("C:\Program Files\..." and a
            # folder with a space) unless the whole line is quoted again.
            command = f'cmd.exe /d /s /c "{subprocess.list2cmdline(command)}"'
        result = subprocess.run(
            command,
            capture_output=True, stdin=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace", env=env, timeout=timeout,
        )
        result.text = f"{result.stdout}\n{result.stderr}"
        return result

    enabled = run("plugins", "enable", PLUGIN.name)
    assert enabled.returncode == 0, enabled.text
    run.profile = profile
    return run


def _engine_log(profile):
    log = profile / "networkforge" / "engine.log"
    if not log.exists():
        return "(no engine.log)"
    return log.read_text(encoding="utf-8", errors="replace")[-6000:]


def _streets_file(path):
    """A GeoPackage of three streets that meet: a main road and two side roads."""
    layer = QgsVectorLayer("LineString?crs=EPSG:4326&field=highway:string", "streets", "memory")
    features = []
    for highway, points in (
        ("residential", [(-3.700, 40.400), (-3.696, 40.400)]),
        ("residential", [(-3.698, 40.400), (-3.698, 40.402)]),
        ("footway", [(-3.697, 40.400), (-3.697, 40.398)]),
    ):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points]))
        feature.setAttributes([highway])
        features.append(feature)
    layer.dataProvider().addFeatures(features)

    path.parent.mkdir(parents=True, exist_ok=True)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "streets"
    QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(path), QgsCoordinateTransformContext(), options)
    assert QgsVectorLayer(str(path), "saved", "ogr").featureCount() == len(features)
    return path


def test_qgis_loads_the_plugin_and_lists_its_tools(qgis_process):
    listed = qgis_process("list")

    assert listed.returncode == 0, listed.text
    for tool in TOOLS:
        assert f"networkforge:{tool}" in listed.stdout, listed.text


def test_qgis_shows_a_tool_form(qgis_process):
    # Building the form reads engine_info.json; no engine is needed yet.
    shown = qgis_process("help", "networkforge:build_network")

    assert shown.returncode == 0, shown.text
    for parameter in ("EXTENT", "CUSTOM", "OSM_FILE", "OUTPUT_FOLDER"):
        assert parameter in shown.stdout, shown.text


@pytest.mark.engine
def test_first_run_installs_the_engine_and_builds_a_network(qgis_process, tmp_path):
    """What a new user's first run does, from fetching uv to a finished network."""
    profile = qgis_process.profile
    assert not (profile / "networkforge").exists()  # nothing installed yet
    streets = _streets_file(tmp_path / "My Documents" / "new streets.gpkg")
    out = tmp_path / "My Documents" / "network out"

    built = qgis_process(
        "run", "networkforge:standalone_network",
        f"--CUSTOM={streets}", f"--OUTPUT_FOLDER={out}",
        timeout=1800,  # the first run downloads Python and the engine
    )

    details = f"{built.text}\n--- engine.log ---\n{_engine_log(profile)}"
    assert built.returncode == 0, details
    # The engine and uv went into the profile folder, not into QGIS.
    venv = profile / "networkforge" / "engine-venv"
    engine_program = (venv / "Scripts" / "networkforge.exe" if os.name == "nt"
                      else venv / "bin" / "networkforge")
    assert engine_program.exists(), details
    assert any((profile / "networkforge" / "uv").rglob("uv*")), details
    assert f"Installing NetworkForge engine {engine.ENGINE_VERSION}" in built.text, details

    network = QgsVectorLayer(f"{out / 'network.gpkg'}|layername=edges", "network", "ogr")
    assert network.isValid(), details
    # The side roads cut the main road in three, so there are more
    # street segments than the three lines that went in.
    assert network.featureCount() >= 5, details
    assert {f["highway"] for f in network.getFeatures()} == {"residential", "footway"}
    assert (out / "network.osm.pbf").stat().st_size > 0

    # A second run finds the engine and doesn't install it again.
    again = qgis_process("run", "networkforge:engine_info", timeout=600)
    assert again.returncode == 0, again.text
    assert f"NetworkForge engine version: {engine.ENGINE_VERSION}" in again.text, again.text
    assert "Installing NetworkForge engine" not in again.text, again.text
