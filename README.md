# NetworkForge QGIS plugin

[![tests](https://github.com/Yibbzz/networkforge-qgis/actions/workflows/tests.yml/badge.svg)](https://github.com/Yibbzz/networkforge-qgis/actions/workflows/tests.yml)
[![coverage](https://codecov.io/gh/Yibbzz/networkforge-qgis/graph/badge.svg)](https://codecov.io/gh/Yibbzz/networkforge-qgis)
[![Network Analyst (newest)](https://github.com/Yibbzz/networkforge-qgis/actions/workflows/network-analyst-latest.yml/badge.svg)](https://github.com/Yibbzz/networkforge-qgis/actions/workflows/network-analyst-latest.yml)

A QGIS plugin for adding your own proposed roads, cycleways and paths to
the OpenStreetMap network. You get a **before** and an **after** network
back as OSM PBF files for routers such as Valhalla, and as QGIS layers to
look at. It can also change or remove existing streets, ban turns, add
bollards and signals, and build a network from your own lines alone,
without OpenStreetMap.

Routing on the result is done with routing.earth's
[QGIS Network Analyst plugin](https://github.com/routing-earth/network-analyst-qgis-plugin),
which runs Valhalla on your own computer. Together the two give QGIS
users a routable network of their own, for free.

![Before and after networks around the harbour, with the custom line highlighted in the after network](docs/images/before-after.png)

## Start here

- **[The tutorial](docs/tutorial.md)**: a whole scheme, step by step with
  screenshots: a commute across the Thames in Reading, a new bridge,
  changes to the streets around it, and routes before and after with
  the Network Analyst plugin. The data to follow along is included.
- **[Examples](docs/examples.md)**: six short ones with pictures: a
  footbridge, a closed street, a network from six lines, a one-way
  street, a banned turn and a bollard.
- **[Use cases](docs/use-cases.md)**: planning, floods and closures,
  traffic schemes, your own street data.
- **[Moving an ArcGIS street network to QGIS](docs/migrating-from-arcgis.md)**.

## Install

1. In QGIS, open **Plugins > Manage and Install Plugins > Settings**.
2. Tick **Show also Experimental Plugins**.
3. Under **Plugin Repositories** click **Add**, name it `NetworkForge`,
   paste this URL and click **OK**:

   ```
   https://github.com/Yibbzz/networkforge-qgis/releases/latest/download/plugins.xml
   ```
4. On the **All** tab, search for **NetworkForge** and click
   **Install Plugin**.

Or download the zip from the
[latest release](https://github.com/Yibbzz/networkforge-qgis/releases/latest)
and use **Install from ZIP**. Needs QGIS 3.34 or newer.

The first time you run a tool, the plugin installs its engine into a
`networkforge` folder in your QGIS profile (once, needs an internet
connection). Nothing is installed into QGIS itself. The `engine.log`
file in that folder is useful when reporting a problem.

## The tools

In the Processing Toolbox, under **NetworkForge**:

- **Build scenario network**: your lines joined into OpenStreetMap for an
  area, giving the before and after networks. OpenStreetMap is
  downloaded for areas up to 1,000 km2; for bigger ones, give it a
  downloaded OSM file.
- **Build standalone network**: a network from your own lines alone.
- **Check custom network layer**: checks your lines and attributes in
  seconds, without downloading anything.
- **Engine information**: the installed engine's version; it can also
  reinstall the engine.

## Describing your lines

Your lines are an ordinary QGIS line layer (a GeoPackage, not a
Shapefile, which shortens field names). Each line is described with
OpenStreetMap's own field names, such as `highway`, `maxspeed` and
`oneway`, or you pick a preset for all of them when you build. The same
layer can change or remove existing streets and ban turns, and a second,
points layer adds bollards, signals and crossings.

What the fields mean, where lines join, and how to do each of these is
in the engine's **[network rules](https://github.com/Yibbzz/networkforge/blob/main/docs/network-rules.md)**.
When a line is wrong, the tool selects it and links to the part of
those rules that explains why.

## Tested with the Network Analyst plugin

Every change is tested by building networks with this plugin and
routing on the PBF files with the Network Analyst plugin's own tools:
new roads and cycleways, closed and removed streets, one-way streets,
speed limits, banned turns, bollards, cycle tracks, standalone networks
and ferries. This runs on QGIS 3 and QGIS 4, on Linux and Windows, and
once a week against the newest version of their plugin (the third badge
above). The scenarios are in
[`tests/test_network_analyst.py`](tests/test_network_analyst.py).

## Development

Link the plugin into your QGIS profile, enable it in QGIS, and use the
**Plugin Reloader** plugin to reload it after changes:

```sh
ln -s "$PWD/networkforge_qgis" ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
```

Tests use `pytest` and `pytest-qgis` with QGIS's Python:

```sh
uv venv --python /usr/bin/python3 --system-site-packages .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```

The first run installs the engine and downloads the Network Analyst
plugin and `pyvalhalla` into `.pytest_cache` (needs the internet and
port 8002). `-m "not engine and not network_analyst"` runs only the
fast tests. [`manual-test/`](manual-test/README.md) has a checklist for
what the automated tests can't see.

Pushing a version tag such as `v0.5.0` builds the plugin zip and
publishes a GitHub release (`.github/workflows/release.yml`).

## Limitations

No public transport and no traffic simulation. Turn restrictions,
bollards and signals are in the PBF files for routers; the QGIS layers
can't show them, so QGIS's own network tools ignore them. An existing
street can be changed or removed, not redrawn. Areas the size of a
county or a country need a lot of memory.

All the network logic lives in the separate engine,
[NetworkForge](https://github.com/Yibbzz/networkforge). This repository
is the QGIS front end.

## Credits and licence

Map data © OpenStreetMap contributors, under the
[Open Database License](https://www.openstreetmap.org/copyright).

GPL-3.0, see [LICENSE](LICENSE).
