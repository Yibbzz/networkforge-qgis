# Changelog

## Unreleased

- The PBF files are now tested with routing.earth's QGIS Network Analyst
  plugin on every change: new lines, removed and closed streets, one-way
  streets, speed limits, banned turns and standalone networks are built,
  turned into Valhalla graphs and routed on with that plugin's own tools,
  on QGIS 3 and QGIS 4. A weekly check uses the newest version of their
  plugin and of Valhalla. See "Tested with the Network Analyst plugin"
  in the README.
- The use-case guide now says which way a street made one-way runs: the
  way your line is drawn.

## 0.3.0 - 2026-10-06

- The plugin now uses NetworkForge engine v0.12.0 (was v0.11.0); the
  first tool you run replaces the installed engine.
- Turn restrictions: in "Build scenario network" and "Build standalone
  network", a short line drawn through a junction with a `restriction`
  field (`no_left_turn`, `only_straight_on`, ...) bans or forces that
  turn. It is written to the PBF file for routers; the log says how many
  were added. "Check custom network layer" counts them, and the features
  that change existing streets.
- From the engine: attributes that aren't OpenStreetMap tags keep their
  type in the network layers (a number stays a number, so it can be
  used as a cost in QGIS); building a standalone network is about four
  times faster; clearer messages when every line is outside the area or
  a coordinate isn't a number.

## 0.2.1 - 2026-10-05

- The plugin now uses NetworkForge engine v0.11.0 (was v0.10.0); the
  first tool you run replaces the installed engine. From the engine: the
  `oneway` field of the network layers is always text (`yes`, `no` or
  `-1`), where it used to mix true/false and text; a line drawn along an
  existing street joins it at every junction it passes; a download from
  OpenStreetMap that fails is tried again twice before giving up; and
  "Build standalone network" no longer mentions OpenStreetMap in its
  progress messages.
- "Build scenario network" says how many street segments were removed.

## 0.2.0 - 2026-10-05

- The plugin now uses NetworkForge engine v0.10.0 (was v0.5.0). The
  first tool you run replaces the installed engine, which needs an
  internet connection and takes a few minutes, once.
- New tool, "Build standalone network": turns a line layer of your own
  into a routable network without OpenStreetMap. No area, no download
  and no before network; you choose whether lines join wherever they
  cross or only where they share a vertex. Gives a Network layer and
  `network.osm.pbf`.
- "Build scenario network" can change or remove existing streets: a
  feature with an OpenStreetMap way id (`osm_id` or `osmid`) changes
  that street, and `remove` = `yes` takes it out. Changed streets are
  drawn in orange in the After network, and the log says how many
  streets are new, changed and removed.
- From the engine: the PBF files now hold OpenStreetMap as it is (way
  ids, every tag, turn restrictions, ferries), so routes on the before
  file match routes on the OpenStreetMap data; every piece of the
  network is kept, not only the largest; lengths are right for layers
  in Web Mercator; the `pedestrian_street` preset allows cycling
  explicitly. See the engine's
  [changelog](https://github.com/Yibbzz/networkforge/blob/v0.10.0/CHANGELOG.md).

## 0.1.4 - 2026-10-01

- Fixed the engine install failing with "No module named pip" on the
  Flatpak QGIS for Linux: where QGIS's Python has no pip, the installer
  (uv) is now downloaded directly.
- Fixed the engine failing to start after installing on the Flatpak
  QGIS ("reports version None"): the engine now always runs on its own
  downloaded Python, never one found on the computer.
- When the engine can't report its version, the reason is now written
  to `engine.log`.

## 0.1.2 - 2026-10-01

- The plugin's description now says exactly what is downloaded on first
  use, where it is kept and how to remove it.

## 0.1.1 - 2026-10-01

- The plugin now says it supports QGIS 4, so QGIS 4 lists it when
  installing from the plugin repository.

## 0.1.0 - 2026-10-01

First release (experimental).

- "Build scenario network": builds the before and after networks for an
  area from a layer of custom lines, with progress and cancel, and loads
  both as layers coloured by kind of street, with the custom lines
  highlighted. PBF files for routers are written alongside.
- "Check custom network layer": validates the lines and their attributes
  without downloading anything.
- "Engine information": shows the engine's version and what it supports,
  and can reinstall it.
- Warnings and errors that name features select those features in the
  custom layer, and errors link to the engine's tagging guide.
- The NetworkForge engine (v0.5.0) is installed into its own environment
  inside the QGIS profile the first time a tool needs it.
- Tested on QGIS 3.44 and QGIS 4, with GitHub CI on QGIS LTR and latest.
