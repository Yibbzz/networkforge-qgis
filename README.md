# NetworkForge QGIS plugin

A QGIS plugin for adding your own proposed roads, cycleways and paths to
the OpenStreetMap network, and getting a **before** and an **after**
network back as QGIS layers (plus OSM PBF files for routers such as
Valhalla).

This is a proof of concept and the QGIS front end only. All the network
logic lives in the separate engine,
[NetworkForge](https://github.com/Yibbzz/networkforge), which the plugin
will install into its own environment and run as a separate program.

## Status

Early development. The plugin adds a "NetworkForge" group to the
Processing Toolbox with three tools:

- **Check custom network layer** - checks your lines and attributes in
  seconds, without downloading anything. Problems are listed with a link
  to the guide, and the features concerned are selected.
- **Build scenario network** - choose an area and a layer of your own
  lines, and say how they are travelled: a preset such as `primary_road`
  for every line, or each feature's own attributes. OpenStreetMap data
  is downloaded for the area, or read from a local OSM file (required
  above 1,000 km2). You get a **Before network** and an **After
  network** layer coloured by kind of street, with your lines
  highlighted in the after layer, and `before.osm.pbf` and
  `after.osm.pbf` in the output folder for routers. Features named in a
  warning or error are selected in your layer.
- **Engine information** - shows the installed engine's version and what
  it supports, and can reinstall it.

The engine is installed on first use (once, needs an internet
connection).

The engine goes into a `networkforge` folder inside your QGIS profile
folder, next to an `engine.log` file that is useful when reporting
problems. Deleting that folder removes the engine; the plugin installs
it again when next needed.

## Install

In QGIS, add this plugin's repository once; after that QGIS installs it
and offers updates like any other plugin:

1. **Plugins > Manage and Install Plugins > Settings**.
2. Tick **Show also Experimental Plugins**.
3. Under **Plugin Repositories** click **Add**, give it the name
   `NetworkForge` and this URL, then **OK**:

   ```
   https://github.com/Yibbzz/networkforge-qgis/releases/latest/download/plugins.xml
   ```
4. Go to the **All** tab, search for **NetworkForge** and click
   **Install Plugin**.

Alternatively, download the zip from the
[latest release](https://github.com/Yibbzz/networkforge-qgis/releases/latest)
and use **Install from ZIP**.

Your custom network layer is any line layer you draw in QGIS. Give it a
text field called `highway` (and optionally `maxspeed`, `oneway`, ...)
to describe each line, or leave the fields out and pick a preset when
you build. Save it as a GeoPackage, not a Shapefile, which shortens
field names.

## Requirements

QGIS 3.34 or newer (developed on the 3.44 LTR).

## Development install

Link the plugin package into your QGIS profile, then enable it in QGIS:

```sh
mkdir -p ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins
ln -s "$PWD/networkforge_qgis" ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
```

In QGIS: **Plugins > Manage and Install Plugins > Installed**, tick
**NetworkForge**. Install the **Plugin Reloader** plugin to reload the
code after changes without restarting QGIS.

## Tests

The tests use `pytest` and `pytest-qgis` with the Python that QGIS
uses. On Linux, with [uv](https://docs.astral.sh/uv/) installed:

```sh
uv venv --python /usr/bin/python3 --system-site-packages .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```

Most tests use a stand-in for the engine (`tests/fake_engine.py`) that
plays back prepared replies, so they run in seconds. The end-to-end
tests (`-m engine`) use the real engine on a tiny hand-made street grid
(`tests/data/grid.osm`); their first run installs the engine, which
needs an internet connection. To skip them: `pytest -m "not engine"`.

GitHub runs all of them on every push, in the official QGIS Docker
image, for both the long-term release and the latest QGIS.

## Releasing

Pushing a version tag such as `v0.1.0` runs `.github/workflows/release.yml`:
it builds the plugin zip with `qgis-plugin-ci` and attaches it to a
GitHub release, together with the `plugins.xml` that the install steps
above point QGIS at. If the repository secrets `OSGEO_USERNAME` and
`OSGEO_PASSWORD` are set, it also publishes to plugins.qgis.org.

To build a zip by hand: `uvx qgis-plugin-ci package 0.1.0`.

## Limitations

No public transport, no traffic simulation and no turn restrictions yet.

## Credits and licence

Map data © OpenStreetMap contributors, available under the
[Open Database License](https://www.openstreetmap.org/copyright).

GPL-3.0, see [LICENSE](LICENSE).
