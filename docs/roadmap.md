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
[network-analyst.md](https://github.com/Yibbzz/networkforge/blob/v1.0.0/docs/network-analyst.md)
lists each ArcGIS feature, the tag that replaces it and the test that
proves it.

## Next steps

The tools do what the goal asks: new lines, changed and removed
streets, turn restrictions, points, ferries and standalone networks,
each tested with Valhalla through the Network Analyst plugin. What is
left is proving it in real use and getting it to people. Do these in
order.

### 1. Use it on a screen

Everything so far was tested without a screen, on networks of a few
streets.

- [ ] Work through the [hands-on checklist](../manual-test/README.md),
      parts 1 to 6, with the data in `manual-test/`. About an hour.
- [ ] Fix what it turns up: confusing labels, unclear messages, styling.

### 2. Click through the Network Analyst plugin once

- [ ] Checklist part 7: install their plugin and `pyvalhalla`, build a
      graph from `after.osm.pbf` with their own button, and route on it.
      The automated tests run the same Valhalla programs directly, but
      can't click that button.

### 3. Test on Windows

- [ ] Checklist part 8. Most users are on Windows, and it was last tried
      with plugin 0.1.x and engine v0.5.0. The engine install is the
      part most likely to differ.

### 4. Tell routing.earth

- [ ] Comment on
      [issue #13](https://github.com/routing-earth/qgis-network-analyst-tutorial-challenge/issues/13)
      of their tutorial challenge with a before and after picture
      (`docs/images/example-footbridge.png`).
- [ ] Ask two things: whether a tutorial that uses a second plugin
      (NetworkForge) is welcome, and what format they want.
- [ ] Report what the tests found: run from Python or `qgis_process`,
      their tools refuse their own defaults for drop-down settings
      ("Incorrect parameter value for INPUT_MODE").

### 5. Write the tutorial

- [ ] Their rules: written by a person, not by AI, and not a copy of
      Esri's steps one by one.
- [ ] Start from a planning question ("what does this new link
      change?"), not from settings.
- [ ] The [examples](examples.md), [use cases](use-cases.md) and
      [ArcGIS guide](migrating-from-arcgis.md) are material to draw on.
- [ ] Keep a copy in this repo's `docs/` as the main user guide.

### 6. Publish on plugins.qgis.org

- [ ] Make an OSGeo account and set the repository secrets
      `OSGEO_USERNAME` and `OSGEO_PASSWORD`; the release workflow does
      the rest on the next version tag.
- [ ] Until then, users add this repository's URL to QGIS by hand.
- [ ] Keep "experimental" until steps 1 to 3 are done and a few people
      outside the project have used it.

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
