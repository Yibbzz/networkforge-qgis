"""Takes the tutorial's screenshots of QGIS (docs/images/tutorial-qgis-*.webp).

Real QGIS desktop does the steps of the tutorial's worked example, on a
screen nobody sees (Xvfb), in a profile of its own that holds this
plugin and routing.earth's Network Analyst plugin. Each step is saved
as a picture of the QGIS window:

    01 the Processing Toolbox with the NetworkForge tools
    02 the bridge line on the map       03 its attribute table
    04 the "Build scenario network" form, filled in
    05 the log when the build has finished
    06 the Before and After layers
    07 the Network Analyst plugin's settings, with pyvalhalla installed
    08 its "From PBF" dialog, for a graph of before.osm.pbf
    09 its graph list, with a graph of each PBF
    10 its routing panel: local server on the before graph, car, A and B,
       and the route it draws
    11 the same on the after graph
    12 stage 2: the lines and points given to the tool
    13 stage 2: the After layer, with the changed streets
    14 stage 3: the bollard on Sonning Bridge, as a point given to the tool
    15 stage 3: driving D to C on the stage 2 network, over Sonning Bridge
    16 stage 3: the same with the bollard, over the new bridge

    .venv/bin/python scripts/make_tutorial_screenshots.py

The routing is done through the Network Analyst plugin's own panel, with
the tests' copy of pyvalhalla (run `pytest -m network_analyst` once) and
the networks built in step 05. Needs `xvfb-run` and an internet connection (the background map
and, for the builds, OpenStreetMap). What QGIS did is written to
docs/images/tutorial-qgis-*.log; those files are not for the repository.
"""

import os
import shutil
import subprocess
import sys

import make_examples as m

WORK = m.CACHE / "tutorial"
# Where QGIS writes the networks: a folder a reader might use, since its
# name is in the screenshots. Not for the repository (see .gitignore).
OUTPUT = m.ROOT / "docs" / "tutorial-data" / "output"
PROFILES = WORK / "qgis-profile"
STAGE_1 = WORK / "reading-1-bridge"
ANALYST = m.CACHE / "network-analyst"
INSIDE = m.ROOT / "scripts" / "tutorial_screens_in_qgis.py"
SETTINGS = """[PythonPlugins]
processing=true
networkforge_qgis=true
valhalla=true

[qgis]
checkVersion=false

[app]
projections\\unknownCrsBehavior=NoAction
projections\\newProjectCrsBehavior=UsePresetCrs
projections\\defaultProjectCrs=EPSG:3857
"""


def profile():
    """A QGIS profile with nothing in it but the two plugins."""
    shutil.rmtree(PROFILES, ignore_errors=True)
    plugins = PROFILES / "profiles" / "default" / "python" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "networkforge_qgis").symlink_to(m.ROOT / "networkforge_qgis")
    theirs = sorted(ANALYST.glob("plugin-*/valhalla"))
    if not theirs:
        raise SystemExit("The Network Analyst plugin isn't in .pytest_cache yet: run "
                         "pytest -m network_analyst once.")
    (plugins / "valhalla").symlink_to(theirs[0])
    # pyvalhalla where the plugin's own "Install" button puts it (an unpacked
    # wheel): the tests' copy, so nothing is downloaded.
    ours = sorted(ANALYST.glob("pyvalhalla-*/lib/python3*/site-packages"))
    if not ours:
        raise SystemExit("pyvalhalla isn't in .pytest_cache yet: run pytest -m network_analyst once.")
    data = PROFILES / "profiles" / "default" / "valhalla" / "pyvalhalla"
    for part in ("valhalla", "pyvalhalla.libs"):     # what the unpacked wheel holds
        if (ours[0] / part).exists():
            shutil.copytree(ours[0] / part, data / part, symlinks=True)
    settings = PROFILES / "profiles" / "default" / "QGIS"
    settings.mkdir(parents=True)
    (settings / "QGIS3.ini").write_text(SETTINGS)


def qgis(session):
    env = {key: value for key, value in os.environ.items()
           if key not in ("PYTHONPATH", "VIRTUAL_ENV", "QT_QPA_PLATFORM")}
    env.update(NF_IMAGES=str(m.IMAGES), NF_WORK=str(OUTPUT), NF_SESSION=session,
               NF_DATA=str(m.ROOT / "docs" / "tutorial-data" / "reading-bridge.gpkg"),
               NF_ENGINE=str(m.CACHE / "networkforge-engine"))
    subprocess.run(
        ["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24",
         "qgis", "--nologo", "--noversioncheck", "--profiles-path", str(PROFILES),
         "--code", str(INSIDE)],
        env=env, timeout=1500, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = m.IMAGES / f"tutorial-qgis-{session}.log"
    print(log.read_text() if log.exists() else f"QGIS left no log for the {session} session")


if __name__ == "__main__":
    # before: building the network; analyst: routing on it with the Network
    # Analyst plugin's own panel; after: stage 2; stage3: the bollard.
    sessions = sys.argv[1:] or ["before", "analyst", "after", "stage3"]
    profile()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for session in sessions:
        qgis(session)
