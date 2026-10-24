"""Takes the traffic tutorial's screenshots of QGIS (docs/images/tutorial-traffic-qgis-*.webp).

Real QGIS desktop, on a screen nobody sees (Xvfb), in the same kind of
profile as scripts/make_tutorial_screenshots.py (this plugin and the
Network Analyst plugin), does the tutorial's steps for Bristol:

    01 the Processing Toolbox with the NetworkForge tools, and the hospital
    02 the "Add traffic" form, filled in for the Bristol extract
    03 its log when it has finished
    04 the Network Analyst plugin's graph list, with the .tar file
    05 its isochrone panel: 15 minutes from the hospital at Monday 03:00
    06 the same at 08:00
    07 the two areas together, renamed and coloured

    .venv/bin/python scripts/make_traffic_screenshots.py

Run scripts/make_traffic_tutorial_example.py first: it downloads the
extract (copied here into docs/tutorial-data/output/traffic, the folder
the screenshots show) and writes bristol-traffic.gpkg. Needs `xvfb-run`
and an internet connection (the background map). What QGIS did is
written to docs/images/tutorial-traffic-qgis.log, not for the repository.
"""

import os
import shutil
import subprocess

import make_examples as m
import make_tutorial_screenshots as screens

EXTRACT = m.CACHE / "traffic-bristol" / "bristol-latest.osm.pbf"
OUTPUT = m.ROOT / "docs" / "tutorial-data" / "output" / "traffic"
INSIDE = m.ROOT / "scripts" / "traffic_screens_in_qgis.py"


def qgis():
    env = {key: value for key, value in os.environ.items()
           if key not in ("PYTHONPATH", "VIRTUAL_ENV", "QT_QPA_PLATFORM")}
    env.update(NF_IMAGES=str(m.IMAGES), NF_WORK=str(OUTPUT),
               NF_DATA=str(m.ROOT / "docs" / "tutorial-data" / "bristol-traffic.gpkg"),
               NF_ENGINE=str(m.CACHE / "networkforge-engine"))
    subprocess.run(
        ["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24",
         "qgis", "--nologo", "--noversioncheck", "--profiles-path", str(screens.PROFILES),
         "--code", str(INSIDE)],
        env=env, timeout=1800, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = m.IMAGES / "tutorial-traffic-qgis.log"
    print(log.read_text() if log.exists() else "QGIS left no log")


if __name__ == "__main__":
    if not EXTRACT.exists():
        raise SystemExit("Run scripts/make_traffic_tutorial_example.py first.")
    shutil.rmtree(OUTPUT, ignore_errors=True)
    OUTPUT.mkdir(parents=True)
    shutil.copy(EXTRACT, OUTPUT / EXTRACT.name)
    screens.profile()
    qgis()
