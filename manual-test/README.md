# Hands-on test checklist

The automated tests can't look at a screen. This checklist is for a
person: about an hour in QGIS, with ready-made data, and for each test
what you should see. Tick the boxes as you go and note anything that
looks wrong, even small things such as a confusing label.

## What is in this folder

| File | What it is |
|---|---|
| `manual-test.qgz` | A QGIS project with everything below loaded, a street map behind it and snapping switched on. **Open this.** |
| `test-data.gpkg` | The layers (listed below). |
| `monaco.osm.pbf` | OpenStreetMap for Monaco, so the tests don't depend on a download. © OpenStreetMap contributors (ODbL). |

Layers in the project:

| Group | Layer | For |
|---|---|---|
| Monaco | `monaco_area` | the area to build |
| | `monaco_footbridge` | a new line: a footbridge across the harbour |
| | `monaco_closed_street` | 79 stretches of Boulevard Albert 1er, `remove` = `yes` |
| | `monaco_slower_street` | 40 stretches of Rue Grimaldi, `maxspeed` = `20` |
| | `monaco_trips` | start and end points for routes |
| | `broken_lines` | three lines, two with mistakes |
| Newtown | `newtown_streets` | six invented streets, no OpenStreetMap |
| | `newtown_streets_and_turn` | the same plus a banned left turn |
| | `newtown_streets_with_gap` | the same plus a track that stops 5 m short |
| | `newtown_bollard` | one point, `barrier` = `bollard` |
| | `newtown_trips` | points A, B and C |
| Draw your own | `my_lines`, `my_points` | empty, with the fields already there |

**Before you start:** for every tool, choose an **output folder** of
your own (for example a new folder on your desktop), not this one.
Use a different folder for each test, or remove the result layers from
the project before running a tool into the same folder again.

If something fails, the file to send is `engine.log`, in the
`networkforge` folder of your QGIS profile (**Settings > User Profiles >
Open Active Profile Folder**).

---

## Part 1: the plugin loads

- [ ] **1.1** Open `manual-test.qgz`. The map shows Monaco's harbour with
      a rectangle, a line across the water and four points.
- [ ] **1.2** **Processing > Toolbox** has a **NetworkForge** group with
      four tools: Build scenario network, Build standalone network,
      Check custom network layer, Engine information.
- [ ] **1.3** Run **Engine information**. The log ends with
      `NetworkForge engine version: 1.0.0`. The first time, it installs
      the engine first: a few minutes, with progress in the log.
      Time it took: ______

## Part 2: checking a layer

- [ ] **2.1** **Check custom network layer**, Custom network layer =
      `monaco_footbridge`. Log: `No problems found in 1 feature(s).`
- [ ] **2.2** The same with `broken_lines`. The tool stops with:
      - `feature 2: maxspeed='fast' is not a valid OSM speed`
      - `feature 3: no highway tag (or route=ferry for a ferry)`
      - a link to the guide that opens in your browser
      - `The 2 features concerned are now selected in "broken_lines".`
- [ ] **2.3** In the map, the two bad lines are highlighted (make the
      layer visible; they are just west of the harbour). Open the
      attribute table: the selected rows are "bad speed" and "no
      highway".

## Part 3: adding to OpenStreetMap (Monaco)

For all of these: **Build scenario network**, Area = click the arrow
beside the box > **Calculate from Layer** > `monaco_area`, Travel type =
"Use each feature's own attributes", Local OSM file = `monaco.osm.pbf`.

- [ ] **3.1 A new line.** Custom network layer = `monaco_footbridge`.
      - The progress bar moves and names each step.
      - Log: `After network: 4,574 street segments, of which 1 new and 0 changed.`
      - Two layers appear: **Before network** and **After network**,
        coloured by kind of street.
      - In After network the bridge is a bold pink line. Before network
        doesn't have it.
      - The output folder has `before.gpkg`, `after.gpkg`,
        `before.osm.pbf` and `after.osm.pbf`.
- [ ] **3.2 A street removed.** Custom network layer =
      `monaco_closed_street`.
      - Log: `Street segments removed: 79. They are in the Before network only.`
      - Boulevard Albert 1er (the main road down the west side of the
        harbour) is in Before network and missing from After network.
- [ ] **3.3 A street changed.** Custom network layer =
      `monaco_slower_street`.
      - Log: `... of which 0 new and 40 changed.`
      - Rue Grimaldi is drawn in bold **orange** in After network.
      - Click it with the Identify tool: `maxspeed` is `20` and
        `modified` is `yes`.
- [ ] **3.4 Selected features only.** In `monaco_closed_street`, select
      a few stretches, tick "Selected features only" under the layer,
      and build. The log's `Custom lines:` number is the number you
      selected, and only those are removed.
- [ ] **3.5 Cancel.** Start 3.1 again and press **Cancel** while it
      runs. It stops within a second or two and QGIS stays usable.
- [ ] **3.6 Download instead of a file.** Run 3.1 with the Local OSM
      file box **empty** (needs internet). It downloads the streets and
      gives the same kind of result. Time it took: ______

## Part 4: a network of your own lines (Newtown)

Zoom to the Newtown group first (right-click `newtown_streets` > Zoom to
Layer). It is an invented place, so the background map shows whatever
is really there; switch the background off if it distracts.

For all of these: **Build standalone network**, Travel type = "Use each
feature's own attributes".

- [ ] **4.1 Six streets.** Network layer = `newtown_streets`.
      - Log: `Network: 10 street segments.` No warnings.
      - A **Network** layer appears. The output folder has
        `network.gpkg` and `network.osm.pbf`.
- [ ] **4.2 A banned turn and a bollard.** Network layer =
      `newtown_streets_and_turn`, Points layer = `newtown_bollard`.
      - Log: `Turn restrictions added: 1. ...` and
        `Points put on the network: 1. ...`
      - `Network: 11 street segments.` (the bollard cut Mill Lane)
- [ ] **4.3 A line that doesn't reach.** Network layer =
      `newtown_streets_with_gap`.
      - A warning says the network is in 2 separate pieces, and
        `The feature concerned is now selected in "newtown_streets_with_gap".`
      - The selected line is Farm Track, on the east side.
- [ ] **4.4 ... joined by a bigger snap distance.** The same, with
      **Advanced parameters > How close lines must come to be joined** =
      `10`. No warning; `Network: 12 street segments.`
- [ ] **4.5 Joining at vertices only.** Network layer =
      `newtown_streets`, Lines join = "Only where lines share a vertex".
      - A warning about 2 separate pieces; Mill Lane is selected (it
        crosses the other streets without sharing a point with them).
      - `Network: 6 street segments.`
- [ ] **4.6 A preset.** Network layer = `newtown_streets`, Travel type =
      `residential_street`, tick "Overwrite the features' own
      attributes". In the Network layer every line, Park Path included,
      now has `highway` = `residential`.

## Part 5: draw your own

The project has snapping on. Draw in `my_lines` and `my_points` (select
the layer, **Toggle Editing**, **Add Line Feature** or **Add Point
Feature**; fill in only the fields you need and leave the rest empty).
Keep a Before network layer from part 3 visible to snap to.

- [ ] **5.1 A path.** In Monaco, draw a line between two streets with
      `highway` = `footway`. Save, build with `my_lines`. It appears in
      pink, and the log says 1 new.
- [ ] **5.2 A line that misses.** Draw a second line out at sea, touching
      nothing. Build: a warning says it doesn't connect, and it is
      selected in `my_lines`. The build still finishes.
- [ ] **5.3 A banned turn.** At a junction of two streets, draw a short
      line from one street, **through the junction**, onto the other.
      Set `restriction` = `no_left_turn` (or `no_right_turn`, whichever
      you drew). Build: `Turn restrictions added: 1`.
- [ ] **5.4 A turn drawn wrong.** Move that line so it no longer passes
      through the junction. Build: it stops, says the line "doesn't pass
      through a junction", and selects it.
- [ ] **5.5 A bollard.** In `my_points`, put a point on a street with
      `barrier` = `bollard`. Build with Points layer = `my_points`:
      `Points put on the network: 1` more than before.
- [ ] **5.6 A change to an existing street.** With the Identify tool,
      find the `osmid` of a street in the Before network. Select that
      street, copy it (Ctrl+C), paste it into `my_lines` (Ctrl+V while
      editing), type the id into `osm_id` and set `oneway` = `yes`.
      Build: it is drawn in orange and its `car_direction` is `forward`.

Was anything hard to work out without this list? ______________________

## Part 6: QGIS's own network tools

Use the Before and After network layers from test 3.1.

- [ ] **6.1** Right-click **After network** > **Filter**, type
      `"walk" = 1`, OK. Do the same for **Before network**.
- [ ] **6.2** **Processing Toolbox > Network analysis > Shortest path
      (point to point)** on Before network: Path type = Shortest, Start
      point and End point = click "walk A" and "walk B" from
      `monaco_trips`. Note the length: ______ m
- [ ] **6.3** The same on After network. The path crosses the bridge and
      is shorter: ______ m (Valhalla gives about 960 m before and 730 m
      after; QGIS's figures will differ a little.)
- [ ] **6.4** **Service area (from point)** from "walk A", Travel cost =
      `400`, on both layers. The After result reaches across the
      harbour; the Before result doesn't.

## Part 7: with the Network Analyst plugin

This is the pairing the project is built for, and its graph-building
button is the one step no automated test covers.

- [ ] **7.1** Install **Network Analyst** from **Plugins > Manage and
      Install Plugins**. Which version did QGIS offer? ______
- [ ] **7.2** In its settings, install `pyvalhalla` (it offers to).
- [ ] **7.3** In its settings, add a graph **from an OSM PBF file**:
      `before.osm.pbf` from test 3.1. Does the build finish without
      errors? Then the same for `after.osm.pbf`.
- [ ] **7.4** Start the local Valhalla with the **before** graph, choose
      the `localhost` provider, and route on foot from "walk A" to
      "walk B". Expected: about **960 m, 11 min**, round the harbour.
- [ ] **7.5** Switch to the **after** graph and route again. Expected:
      about **730 m, 9 min**, across the bridge.
- [ ] **7.6** Build a graph from the `after.osm.pbf` of test 3.2 and
      drive from "drive A" to "drive B". Expected: about **930 m**,
      along the quay, not the boulevard (**650 m** on the before graph).
- [ ] **7.7** Build a graph from the `network.osm.pbf` of test 4.2 and
      route from A to B (`newtown_trips`). Expected: by car about
      **700 m** round the block; on foot about **300 m** past the
      bollard.

## Part 8: on Windows

Most users are on Windows, and it was last tried several versions ago.
On a Windows computer with QGIS:

- [ ] **8.1** Install the plugin from the repository URL in the README.
- [ ] **8.2** Test 1.3. No black console window flashes up while the
      engine installs or runs. Time it took: ______
- [ ] **8.3** Tests 3.1, 4.2 and 5.1.
- [ ] **8.4** Use an output folder with a space and an accent in its
      name (for example `Réseau test`). It still works.

## What to report

For each test that didn't match: the test number, what you saw instead,
a screenshot if it is about looks, and `engine.log` if a tool stopped.
