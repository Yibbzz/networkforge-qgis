# Roadmap

Where this project is going, and what to do next. For how to install
and use the plugin today, see the [README](../README.md).

## The goal

Give QGIS users what ArcGIS Network Analyst users have: a way to build
a routable network from their own data and analyse it. In the open
source world that is two tools working together:

| Step | Tool | Result |
|---|---|---|
| Build the network | **NetworkForge** (this plugin and its engine) | `before.osm.pbf` and `after.osm.pbf`: OpenStreetMap, without and with your own lines and changes. Or `network.osm.pbf`: your own lines alone |
| Analyse the network | **[QGIS Network Analyst](https://github.com/routing-earth/network-analyst-qgis-plugin)** by routing.earth, which runs Valhalla locally | routes, isochrones, matrices on either network |

The third part of the goal is **documentation that is better than
Esri's**: shorter, starting from a planning question, and written for
the QGIS, OpenStreetMap and Valhalla world.

### Why this is worth doing

- The Network Analyst plugin can build a routing graph "from your own
  OSM PBF file", but nothing says how to make such a file with your own
  roads in it. The usual answer is to edit OpenStreetMap data by hand
  in JOSM, a separate program. routing.earth's own note on the
  "Create a network dataset" tutorial says it "would need a josm
  session today".
- NetworkForge makes that file from inside QGIS, and joins the new
  lines to the existing streets so that routes can use them.

## What Esri's tutorial does, and what replaces it

The tutorial to match is Esri's
[Create a network dataset](https://doc.esri.com/en/arcgis-pro/latest/help/analysis/networks/how-to-create-a-usable-network-dataset.html).
It builds a network for San Diego from prepared street data. Most of
its steps are manual settings that OpenStreetMap tags and Valhalla
already take care of:

| Esri step | Here |
|---|---|
| Streets and walking paths as sources | OpenStreetMap has both; your lines are added by NetworkForge. Or your own line layer alone, with "Build standalone network" |
| Connectivity policy (End Point, Any Vertex) | "Lines join" in "Build standalone network": wherever they cross, or only where they share a vertex |
| Vertical connectivity fields for overpasses (`F_ZLEV`, `T_ZLEV`) | streets join where they share a point; `bridge`, `tunnel` and `layer` keep crossings apart |
| Costs: minutes, miles, turn delays | worked out by Valhalla from `highway` and `maxspeed` |
| Restrictions for cars, buses, walking (`AR_AUTO`, ...) | `motor_vehicle`, `bus`, `foot`, or a preset |
| One-way streets (`DIR_TRAVEL`) | `oneway` |
| Avoid unpaved roads | `surface` |
| Height limit for a tour bus | `maxheight` |
| Hierarchy (`FUNC_CLASS`) | the `highway` class |
| Travel modes: car, tour bus, walking | Valhalla's costing options, chosen in the Network Analyst plugin |
| Directions and street names | `name`; Valhalla writes the directions |
| Build Network | "build graph from PBF" in the Network Analyst plugin |
| Explore Network | look at the Before and After layers in QGIS |

The engine accepts every tag in the right-hand column, and since
engine v0.6.0 its Valhalla tests check that each one reaches the PBF
file and changes the routes Valhalla gives. The engine's
[network-analyst.md](https://github.com/Yibbzz/networkforge/blob/v0.12.0/docs/network-analyst.md)
lists each ArcGIS feature, the tag that replaces it and the test that
proves it.

## Next steps

Do these in order. Each one ends with something you can show.

### 1. Prove the two plugins work together

A first check without QGIS passed on 2026-10-02: a before and after PBF
from the engine (the test street grid plus a diagonal cycleway) were
built into Valhalla graphs with `pyvalhalla` 3.9.0. The cycling route
corner to corner dropped from 606 m to 429 m; walking and driving
stayed at 606 m, as they should for a cycleway.

**Checked in the Network Analyst plugin itself since 2026-10-06**, by
the automated tests in `tests/test_network_analyst.py`. They build the
networks with this plugin's tools, build a Valhalla graph from each PBF,
start Valhalla on the computer and run the Network Analyst plugin's own
Processing tools against it. They run on every push, on QGIS 3 (LTR)
with their plugin 6.1.0 and on QGIS 4 with their plugin 7.1.0, and once
a week against the newest commit of their plugin and the newest
`pyvalhalla` (workflow "Network Analyst (newest)").

- [x] New lines: a cycleway shortens the cycling route only; a road
      shortens the drive.
- [x] Changes to existing streets: removed, closed to everyone, closed
      to motor traffic, made one-way, given a lower speed limit.
- [x] A banned turn, in OpenStreetMap and in a standalone network.
- [x] Standalone networks: joined at crossings or at vertices only,
      bridges, one-way streets.
- [x] Their walking isochrone runs on the after network.

Still to do by hand, once, on a computer with a screen:

- [ ] In the Network Analyst plugin's settings, install `pyvalhalla` and
      build a graph from `after.osm.pbf` with its own button. The tests
      can't click it; they run the same programs (`valhalla_build_tiles`,
      `valhalla_service`) directly.
- [ ] Do it on a real area (the Monaco footbridge from the README).

Found on the way: run from Python or `qgis_process`, the Network Analyst
plugin's tools refuse their own defaults for drop-down settings
("Incorrect parameter value for INPUT_MODE"), so those must be given.
Worth reporting to routing.earth.

Everything below depends on this. If it fails, the fix belongs in the
engine, not in this plugin.

### 2. Check the Esri examples, as automated tests in the engine

**Done in engine v0.6.0** (`tests/valhalla`, GitHub job "PBF in
Valhalla", with a pinned `pyvalhalla`). The plan was:

Add a Valhalla job to the engine's GitHub tests (`pyvalhalla` installs
with pip, no server or Docker needed): build a before and after PBF for
each case below, build both graphs, and compare routes. That is where
these checks belong, because the engine writes the PBF; this plugin
only passes files along. Pin the `pyvalhalla` version so a Valhalla
change can't break the tests unannounced.

One line of each kind, with Valhalla treating it correctly:

- [x] a one-way street (`oneway=yes`): routes only go one way
- [x] a path closed to cars (`highway=footway`): walking uses it,
      driving does not
- [x] a low bridge (`maxheight`): a bus or truck goes around, a car
      does not
- [x] an unpaved road (`surface`): avoided when asked
- [x] a bridge over an existing road (`bridge=yes`, `layer=1`): crosses
      it without joining it

### 3. Add a short "Routing with Valhalla" section to the README

- [ ] Steps to load the two PBF files into the Network Analyst plugin.
- [ ] One before and after picture made with Valhalla.

### 4. Offer the tutorial to routing.earth

- [ ] Comment on
      [issue #13](https://github.com/routing-earth/qgis-network-analyst-tutorial-challenge/issues/13)
      of their tutorial challenge with the before and after picture.
- [ ] Ask two things: whether a tutorial that uses a second plugin
      (NetworkForge) is welcome, and what format they want.
- [ ] Their rules: the tutorial must be written by a person, not by AI,
      and should not copy Esri's steps one by one.

### 5. Write the tutorial

- [ ] Start from a planning question ("what does this new link
      change?"), not from settings.
- [ ] Cover the Esri examples from step 2 that worked.
- [ ] Keep a copy in this repo's `docs/` as the main user guide.

### 6. Close the gaps with Esri

Changes for the engine, most useful first. None of these belong in this
plugin (it has no network logic).

- [x] **Closing or changing existing streets**, not only adding lines:
      engine v0.7.0 (change) and v0.8.0 (remove). A feature with an
      OpenStreetMap way id changes that street; `remove` = `yes` takes
      it out. The plugin draws changed streets in orange.
- [x] **A network from your own data alone**, as Esri's tutorial does:
      engine v0.10.0, "Build standalone network" in this plugin.
- [x] **Turn restrictions**: those in OpenStreetMap are kept in the PBF
      since engine v0.6.0. Since engine v0.12.0 you can draw your own, as
      a short line through a junction with a `restriction` field, as
      ArcGIS does with a turn feature class. Not covered: restrictions
      through a stretch of street ("via way"), and turn penalties in
      seconds (Valhalla works out turn delays itself).
- [ ] **Public transport**: out of scope for now.

## Things not planned

- **A hosted web app** for uploading networks and routing online. The
  Network Analyst plugin already runs Valhalla on the user's own
  computer, so there is nothing to host. Worth another look only if
  people ask to share results with colleagues who don't use QGIS.
- **Routing tools inside this plugin.** The Network Analyst plugin does
  that; this plugin makes the network.
