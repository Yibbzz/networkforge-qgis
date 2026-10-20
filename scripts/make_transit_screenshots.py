"""Takes the public transport tutorial's screenshots (docs/images/transit-qgis-*.webp).

Real QGIS desktop does the steps of docs/tutorial-transit.md on a screen
nobody sees (Xvfb), in a profile of its own that holds this plugin and
GISBoost's Easy-R5 plugin. Each step is saved as a picture:

    01 the Processing Toolbox with the Easy-R5 tools
    02 the study area, Fountain Square and Klotter Avenue on the map
    03 Easy-R5's "Check transit data (GTFS)" form, filled in
    04 its log, with the days that have service
    05 the closed stairways at Brighton, in the Before network
    06 the stairways' attribute table (the changes)
    07 NetworkForge's "Build scenario network" form, filled in
    08 Easy-R5's "Build R5 network" form, filled in
    09 its log when the network is built
    10 Easy-R5's "Generate isochrones" form: Fountain Square at 5:15 pm
    11 the 30-minute service area at 5:15 pm
    12 the same at 2:00 pm, over the 5:15 pm one
    13 from Klotter Avenue: the service area with the stairways closed and open
    14 the new tram line up Vine Street (its vertices are its stops)
    15 Easy-R5's "Build scenario" form, filled in
    16 "Generate isochrones" with the scenario file (its Advanced section open)
    17 the 2:00-3:00 pm service area with the tram, under the one without

    .venv/bin/python scripts/make_transit_screenshots.py
    NF_ONLY=16 .venv/bin/python scripts/make_transit_screenshots.py   (picture 16 only)

Run scripts/make_transit_tutorial_example.py first: it writes the
tutorial's data, downloads the feeds and builds the networks this uses
(the build takes 8 minutes and 4 GB, too much to repeat inside QGIS).
Needs `xvfb-run`, Easy-R5 in .pytest_cache (`pytest -m easy_r5`) and an
internet connection (the background map). What QGIS did is written to
docs/images/transit-qgis.log; that file is not for the repository.
"""

import os
import shutil
import subprocess

import make_examples as m

WORK = m.CACHE / "transit"
# Where QGIS writes its results: a folder a reader might use, since its
# name is in the screenshots. Not for the repository (see .gitignore).
OUTPUT = m.ROOT / "docs" / "tutorial-data" / "output" / "cincinnati"
PROFILES = WORK / "qgis-profile"
INSIDE = m.ROOT / "scripts" / "transit_screens_in_qgis.py"
SETTINGS = """[PythonPlugins]
processing=true
networkforge_qgis=true
easy_r5=true

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
    theirs = sorted((m.CACHE / "easy-r5").glob("plugin-*/easy_r5"))
    if not theirs:
        raise SystemExit("Easy-R5 isn't in .pytest_cache yet: run pytest -m easy_r5 once.")
    (plugins / "easy_r5").symlink_to(theirs[0])
    settings = PROFILES / "profiles" / "default" / "QGIS"
    settings.mkdir(parents=True)
    (settings / "QGIS3.ini").write_text(SETTINGS)


def inputs():
    """The feeds where a reader would keep them, next to the results."""
    if os.environ.get("NF_ONLY") and (OUTPUT / "uptown-tram.json").exists():
        return                     # retaking one picture: keep what the full run made
    if not (WORK / "network" / "after.osm.pbf").exists():
        raise SystemExit("Run scripts/make_transit_tutorial_example.py first.")
    shutil.rmtree(OUTPUT, ignore_errors=True)
    (OUTPUT / "gtfs").mkdir(parents=True)
    for feed in (WORK / "gtfs").glob("*.zip"):
        shutil.copy(feed, OUTPUT / "gtfs" / feed.name)
    shutil.copytree(WORK / "network", OUTPUT / "network")


def qgis():
    env = {key: value for key, value in os.environ.items()
           if key not in ("PYTHONPATH", "VIRTUAL_ENV", "QT_QPA_PLATFORM")}
    env.update(NF_IMAGES=str(m.IMAGES), NF_WORK=str(OUTPUT),
               NF_DATA=str(m.ROOT / "docs" / "tutorial-data" / "cincinnati-transit.gpkg"),
               NF_ENGINE=str(m.CACHE / "networkforge-engine"),
               NF_R5=str(m.CACHE / "easy-r5" / "r5"))
    subprocess.run(
        ["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24",
         "qgis", "--nologo", "--noversioncheck", "--profiles-path", str(PROFILES),
         "--code", str(INSIDE)],
        env=env, timeout=5400, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = m.IMAGES / "transit-qgis.log"
    print(log.read_text() if log.exists() else "QGIS left no log")


if __name__ == "__main__":
    profile()
    inputs()
    qgis()
