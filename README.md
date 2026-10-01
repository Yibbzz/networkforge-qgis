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

Early development. So far the plugin adds a "NetworkForge" group to the
Processing Toolbox with one tool, "Engine information". It installs the
engine on first use (once, needs an internet connection) and shows what
the engine supports. It does not build networks yet.

The engine goes into a `networkforge` folder inside your QGIS profile
folder, next to an `engine.log` file that is useful when reporting
problems. Deleting that folder removes the engine; the plugin installs
it again when next needed.

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

## Limitations

No public transport, no traffic simulation and no turn restrictions yet.

## Credits and licence

Map data © OpenStreetMap contributors, available under the
[Open Database License](https://www.openstreetmap.org/copyright).

GPL-3.0, see [LICENSE](LICENSE).
