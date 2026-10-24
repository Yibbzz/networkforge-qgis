"""Makes the worked example for the traffic tutorial: Bristol at rush hour.

How far can you drive in 15 minutes from Southmead Hospital at 3 am, and
at 8 am on a weekday? With the plugin's own tool it:

1. downloads Geofabrik's Bristol extract (no build: the network is
   OpenStreetMap as it is),
2. adds traffic with "Add traffic": the tool's two example bands, main
   roads at 60% of their normal speed on weekday mornings and evenings,
3. draws 15-minute driving isochrones from the hospital at Monday 03:00
   and 08:00, with Valhalla serving the .tar as the Network Analyst
   plugin does after "From Tar".

The speeds are the tool's example assumptions, not measurements. It
writes docs/tutorial-data/bristol-traffic.gpkg (the hospital) and prints
the numbers the tutorial quotes; the pictures are screenshots of QGIS,
taken by scripts/make_traffic_screenshots.py.

    QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/make_traffic_tutorial_example.py

Needs an internet connection (the extract, about 13 MB, is kept in
.pytest_cache/traffic-bristol).
"""

import json
import shutil
import subprocess
import time
import urllib.request
from contextlib import contextmanager

import make_examples as m
from qgis.core import QgsDistanceArea, QgsGeometry, QgsProject, QgsVectorFileWriter

from networkforge_qgis.algorithms.add_traffic import EXAMPLE_BANDS

WORK = m.CACHE / "traffic-bristol"
EXTRACT_URL = ("https://download.geofabrik.de/europe/united-kingdom/england/"
               "bristol-latest.osm.pbf")
EXTRACT = WORK / "bristol-latest.osm.pbf"
DATA = m.ROOT / "docs" / "tutorial-data" / "bristol-traffic.gpkg"

HOSPITAL = (-2.5914, 51.4969)          # Southmead Hospital (OpenStreetMap, 2026-10-22)
MINUTES = 15
MONDAY_NIGHT, MONDAY_PEAK = "2026-10-19T03:00", "2026-10-19T08:00"


def extract():
    if not EXTRACT.exists():
        WORK.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(EXTRACT_URL, headers={"User-Agent": "networkforge-docs"})
        with urllib.request.urlopen(request, timeout=300) as reply, EXTRACT.open("wb") as f:
            shutil.copyfileobj(reply, f)
    return EXTRACT


@contextmanager
def valhalla_tar(tar, name):
    """Serve a packed Valhalla graph (.tar) as it is; yields isochrone(depart_at=None)."""
    python, programs = m.valhalla_programs()
    env = m.engine._clean_env()
    folder = m.WORK / "graphs" / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    config = folder / "valhalla.json"
    subprocess.run(
        [str(python), "-c",
         "import json, sys\n"
         "from valhalla.config import get_config\n"
         "config = get_config(tile_extract=sys.argv[1], tile_dir='')\n"
         f"config['httpd']['service']['listen'] = 'tcp://127.0.0.1:{m.PORT}'\n"
         "json.dump(config, open(sys.argv[2], 'w'))\n",
         str(tar), str(config)], check=True, env=env, capture_output=True)
    with open(folder / "service.log", "w") as log:
        server = subprocess.Popen([str(programs / "valhalla_service"), str(config), "1"],
                                  env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{m.PORT}/status", timeout=2)
                break
            except OSError:
                time.sleep(0.2)

        def isochrone(depart_at=None):
            """The 15-minute driving area from the hospital, as a QgsGeometry (WGS 84)."""
            body = {"locations": [{"lon": HOSPITAL[0], "lat": HOSPITAL[1]}],
                    "costing": "auto", "contours": [{"time": MINUTES}], "polygons": True}
            if depart_at:
                body["date_time"] = {"type": 1, "value": depart_at}
            request = urllib.request.Request(
                f"http://127.0.0.1:{m.PORT}/isochrone", data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=60) as reply:
                feature = json.load(reply)["features"][0]
            return QgsGeometry.fromWkt(_wkt(feature["geometry"]))

        yield isochrone
    finally:
        server.kill()
        server.wait()


def _wkt(geometry):
    def ring(points):
        return "(" + ", ".join(f"{x} {y}" for x, y in points) + ")"
    if geometry["type"] == "Polygon":
        return "POLYGON(" + ", ".join(ring(r) for r in geometry["coordinates"]) + ")"
    return "MULTIPOLYGON(" + ", ".join(
        "(" + ", ".join(ring(r) for r in polygon) + ")"
        for polygon in geometry["coordinates"]) + ")"


def km2(geometry):
    measure = QgsDistanceArea()
    measure.setSourceCrs(m.WGS84, QgsProject.instance().transformContext())
    measure.setEllipsoid("WGS84")
    return measure.measureArea(geometry) / 1e6


def save_data():
    hospital = m.memory_layer("Point", m.WGS84, [(HOSPITAL, "Southmead Hospital")],
                              fields=("name",))
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.unlink(missing_ok=True)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "hospital"
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        hospital, str(DATA), QgsProject.instance().transformContext(), options)
    assert error[0] == QgsVectorFileWriter.WriterError.NoError, error
    print("wrote", DATA)


def main():
    pbf = extract()
    print(f"extract: {pbf.stat().st_size / 1e6:.1f} MB")
    save_data()
    tar = m.run("add_traffic", NETWORK_FILE=str(pbf), BANDS=EXAMPLE_BANDS,
                OUTPUT=str(WORK / "bristol-traffic.tar"))["OUTPUT"]
    with valhalla_tar(tar, "traffic-bristol") as isochrone:
        areas = {label: km2(isochrone(when)) for label, when in
                 (("no time", None), ("Monday 03:00", MONDAY_NIGHT),
                  ("Monday 08:00", MONDAY_PEAK))}
    print(f"Numbers for the tutorial ({MINUTES} minutes' drive from Southmead Hospital):")
    for label, area in areas.items():
        print(f"  {label:13} {area:6.1f} km2")
    night, peak = areas["Monday 03:00"], areas["Monday 08:00"]
    print(f"  rush hour reaches {peak / night:.0%} of the night-time area "
          f"({night - peak:.1f} km2 less)")


if __name__ == "__main__":
    main()
