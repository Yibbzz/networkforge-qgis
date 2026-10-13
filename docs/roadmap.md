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
[network-analyst.md](https://github.com/Yibbzz/networkforge/blob/v1.0.1/docs/network-analyst.md)
lists each ArcGIS feature, the tag that replaces it and the test that
proves it.

## Next steps

The tools do what the goal asks: new lines, changed and removed
streets, turn restrictions, points, ferries and standalone networks.
They are tested with Valhalla through the Network Analyst plugin, on
Linux and Windows, and have been used by hand on a screen on both (see
[Done](#done)). What is left is getting it to people. Do these in
order.

### 1. Tell routing.earth

- [ ] Comment on
      [issue #13](https://github.com/routing-earth/qgis-network-analyst-tutorial-challenge/issues/13)
      of their tutorial challenge with a before and after picture
      (`docs/images/example-footbridge.png`).
- [ ] Ask two things: whether a tutorial that uses a second plugin
      (NetworkForge) is welcome, and what format they want.
- [x] Default vehicle sizes (plugin 6.1.0 and 7.1.0): width and height
      were swapped for car, bus and lorry, so a lorry passed under a 3 m
      bridge. Reported as their
      [issue #82](https://github.com/routing-earth/network-analyst-qgis-plugin/issues/82)
      and confirmed; fix offered in
      [pull request #83](https://github.com/routing-earth/network-analyst-qgis-plugin/pull/83).
- Not reported, by choice: run from Python, their tools refuse their
  own defaults for drop-down settings ("Incorrect parameter value for
  INPUT_PROVIDER"). Passing each drop-down by its position is an easy
  way round it, and the tests here do that.

### 2. Write the tutorial

- [ ] Their rules: written by a person, not by AI, and not a copy of
      Esri's steps one by one.
- [ ] Start from a planning question ("what does this new link
      change?"), not from settings.
- [ ] The [examples](examples.md), [use cases](use-cases.md) and
      [ArcGIS guide](migrating-from-arcgis.md) are material to draw on.
- [ ] Keep a copy in this repo's `docs/` as the main user guide.

### 3. Publish on plugins.qgis.org

- [ ] Make an OSGeo account and set the repository secrets
      `OSGEO_USERNAME` and `OSGEO_PASSWORD`; the release workflow does
      the rest on the next version tag.
- [ ] Until then, users add this repository's URL to QGIS by hand.
- [ ] Keep "experimental" until a few people outside the project have
      used it.

### Later, in the engine

None of these belong in this plugin (it has no network logic), and none
blocks the steps above.

- [ ] **Elevation fields** (`F_ZLEV`, `T_ZLEV`) of data prepared for
      ArcGIS. The engine joins lines that share a vertex whatever their
      `layer`, so a bridge that is cut where it crosses a street becomes
      a crossroads: its pieces have to be merged and the vertex at the
      crossing deleted by hand first (see
      [the ArcGIS guide](migrating-from-arcgis.md), step 3). The main
      engine change worth making for ArcGIS data.
- [ ] **A bridge with a vertex exactly on the street below** is joined
      to it when lines join "wherever they cross", although it is tagged
      as a bridge. It stays apart only without a vertex there.
- [ ] **A separate input for points** with ids of their own, so the
      plugin need not renumber points from 1,000,000.
- [ ] **Public transport**: out of scope for now.

## Done

- [x] **Used on a screen** (2026-10-11): the whole
      [hands-on checklist](../manual-test/README.md) worked through in
      QGIS with the data in `manual-test/`, on Linux and on Windows.
- [x] **Routed in the Network Analyst plugin by hand** (2026-10-11):
      their plugin and `pyvalhalla` installed, a graph built from the
      checklist's PBF output with their own button, and routes for
      walking, cycling and driving. The routes use the custom lines.
- [x] **Works on Windows** (2026-10-11), by hand and automatically:
      - By hand: the plugin installed and used end to end on a Windows
        computer, routing included (checklist part 8).
      - On every push: a Windows job on GitHub (`windows` in
        `.github/workflows/tests.yml`) installs QGIS from qgis.org's
        installer, has QGIS load the plugin from a new profile, lets the
        first tool run install the engine, builds networks in folders
        with spaces and accents, and routes on the PBF files with the
        Network Analyst plugin and Valhalla.
      - It found one fault, in the engine: on Windows an OSM file could
        not be read from a folder with an accent in its name. Fixed in
        engine v1.0.1, which also gave the engine a Windows job of its
        own.
- [x] **The two plugins work together** (2026-10-06): automated tests
      build networks with this plugin and route on them with the Network
      Analyst plugin's own tools, on every push, on QGIS 3 (LTR) with
      their plugin 6.1.0 and on QGIS 4 with 7.1.0, and weekly against
      their newest version. See "Tested with the Network Analyst plugin"
      in the README.
- [x] **Esri's examples as automated tests** in the engine (v0.6.0,
      `tests/valhalla`): one-way streets, paths closed to cars, low
      bridges, unpaved roads, bridges that cross without joining.
- [x] **Changing and removing existing streets** (engine v0.7.0 and
      v0.8.0); the plugin draws changed streets in orange.
- [x] **A network from your own data alone** (engine v0.10.0, "Build
      standalone network").
- [x] **Turn restrictions** drawn as lines through a junction, also
      through a stretch of street (engine v0.12.0 and v1.0.0).
- [x] **Points on the network**: barriers, signals and crossings, as a
      points layer (engine v1.0.0).
- [x] **New ferries** (engine v1.0.0).
- [x] **Examples and guides**: [examples](examples.md) with pictures,
      [use cases](use-cases.md), [moving from ArcGIS](migrating-from-arcgis.md).

## Things not planned

- **A hosted web app** for uploading networks and routing online. The
  Network Analyst plugin already runs Valhalla on the user's own
  computer, so there is nothing to host. Worth another look only if
  people ask to share results with colleagues who don't use QGIS.
- **Routing tools inside this plugin.** The Network Analyst plugin does
  that; this plugin makes the network.
