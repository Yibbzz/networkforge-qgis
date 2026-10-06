# What you can use it for

NetworkForge builds a street network you can route on, inside QGIS, in
a few minutes. That makes "what if?" questions about streets cheap to
ask: change the network, build it again, and compare.

Every use below follows the same three steps:

1. **Describe the change** as a line layer: new lines to add, or
   existing streets to change or remove.
2. **Build** with one of the plugin's tools. You get the network
   **before** and **after** the change.
3. **Compare** the two: what can be reached, how long a trip takes,
   which way a route goes. See [Comparing before and after](#comparing-before-and-after).

| You are | Your question | Go to |
|---|---|---|
| A transport or town planner | What does this new road, cycleway or bridge change? | [1](#1-a-proposed-road-cycleway-or-bridge) |
| An emergency or resilience planner | Which places are cut off if these roads flood? | [2](#2-a-flood-landslide-or-other-closure) |
| A highways or traffic officer | What happens if we close this street, or make it one-way? | [3](#3-roadworks-one-way-schemes-and-low-traffic-streets) |
| A road safety or policy officer | What does a 20 mph zone cost in travel time? | [4](#4-a-lower-speed-limit) |
| A masterplanner, or anyone with their own street data | Can I route on a network that isn't in OpenStreetMap? | [5](#5-a-network-from-your-own-data) |

New to the plugin? Install it from the [README](../README.md#install)
first. How to describe a line (which `highway` type, who may use it) is
in the engine's
[tagging guide](https://github.com/Yibbzz/networkforge/blob/v0.12.0/docs/tagging-guide.md).

## 1. A proposed road, cycleway or bridge

*A footbridge across the river is proposed. How many more homes come
within a 10-minute walk of the station?*

1. Draw the proposal as a line layer. Let the ends touch the streets it
   should join.
2. Run **Build scenario network**. Choose the area and your layer, and
   pick a travel type that fits: `footpath`, `cycleway`, `shared_path`,
   `primary_road` and so on. If your layer mixes kinds of line, give it
   a `highway` field and choose "Use each feature's own attributes".
3. You get a **Before network** and an **After network**, with your
   lines in pink in the after layer.
4. Run the same analysis on both and compare.

Good to know:

- A line that doesn't reach the network is not an error: you get a
  warning and the line is selected, so you can extend it.
- A bridge or tunnel that crosses a street without joining it needs
  `bridge` = `yes` (or `tunnel` = `yes`) and a `layer` value, as in
  OpenStreetMap.
- A proposal can also take something away. A bypass that comes with a
  closed high street is one layer with both; see use 3.

The README shows this use on an invented footbridge in Monaco.

## 2. A flood, landslide or other closure

*The flood map shows these streets under water. Which neighbourhoods
can an ambulance no longer reach in 8 minutes, and which have no way
out at all?*

Here nothing is added: existing streets are closed. A feature that
carries a street's OpenStreetMap id changes that street instead of
adding a line.

1. Get the streets with their ids. Either build the area once and use
   the **Before network** layer (id in `osmid`), or download the roads
   with the QuickOSM plugin (id in `osm_id`).
2. Select the streets the flood covers: **Vector > Research Tools >
   Select by Location**, streets that intersect your flood polygon.
3. Save the selection as a new layer (**Export > Save Selected Features
   As**, GeoPackage). This is your custom layer.
4. Close them. Add a text field called `remove` and set it to `yes` for
   every feature (the field calculator does this in one go). Or, to keep
   the streets in the layer but closed to everyone, set `access` to `no`
   instead.
5. Run **Build scenario network** with "Use each feature's own
   attributes".
6. Compare. In the after network, run a service area from the hospital
   or fire station. Streets that are in the before result and not in
   the after result have lost their cover.

Good to know:

- Removed streets are only in the Before network. Streets closed with
  `access` = `no` stay in the After network, drawn in orange, with
  `car`, `bike` and `walk` all false.
- A closure applies block by block, from junction to junction. A block
  that is only partly under water may be closed whole. Check the orange
  lines, or what is missing, before trusting the result.
- To find places that are **cut off completely**, run the service area
  with a very large travel cost. Whatever it does not reach has no route
  at all.
- Several scenarios (1-in-30-year flood, 1-in-100) are several custom
  layers and several builds into different output folders. The
  Processing batch mode runs them in one go.
- The same steps work for a landslide, a bridge inspection, a festival
  or a marathon route.

## 3. Roadworks, one-way schemes and low-traffic streets

*We want to stop through traffic on three residential streets. How much
longer do residents' car trips get, and do walking and cycling trips
stay the same?*

As in use 2, copy the streets concerned into a custom layer with their
id, then change an attribute:

| You want | Set |
|---|---|
| Close a street to everyone | `access` = `no` |
| Close it to motor traffic, keep walking and cycling | `motor_vehicle` = `no` |
| Make it one-way | `oneway` = `yes`, or `-1` for the opposite direction |
| Take it out altogether | `remove` = `yes` |
| Turn a road into a pedestrian street | `highway` = `pedestrian` |
| Ban a turn at a junction | a short line through the junction with `restriction` = `no_left_turn` (see below) |

Only attributes that differ from OpenStreetMap are applied, so the
other fields of the copied street can stay as they are. Changed streets
are drawn in orange in the After network.

Always check which way a new one-way street runs: look at
`car_direction` in the after layer (`forward` and `backward` are
relative to the direction the line is drawn in; show it with an arrow
symbol), or route a trip across it. If it is the wrong way round, swap
`yes` and `-1`.

**Banned turns.** A turn restriction is not a change to one street, so
it is drawn instead of copied: a short line from the street you arrive
on, through the junction, onto the street you leave on, with a field
called `restriction` set to `no_left_turn`, `no_right_turn`,
`no_straight_on`, `no_u_turn` or the same with `only_`. Only routers
obey turn restrictions, so compare the before and after with Valhalla
(below), not with QGIS's own network tools.

## 4. A lower speed limit

*What does a 20 mph limit on these streets add to a drive across
town?*

Copy the streets into a custom layer with their id, set `maxspeed`
(for example `20 mph`; a plain number is km/h), and build. The after
layer's `speed_kph` and `car_minutes` change on those streets, and
Valhalla uses the new limit too.

This shows the effect of the limit itself. There is no traffic model:
congestion and how drivers really behave are not part of it.

## 5. A network from your own data

*We have the street layout of a planned neighbourhood, or the council's
own centrelines, or a site that OpenStreetMap doesn't cover well. Can
we route on it?*

Run **Build standalone network**. It uses your lines and nothing else:
no area to choose, nothing downloaded.

1. Give every line a kind of street: a `highway` field, or one preset
   for all of them. Add `maxspeed` and `oneway` where you have them.
2. Choose where **lines join**. "Wherever lines cross or touch" suits
   drawings. "Only where lines share a vertex" suits clean centreline
   data, where a flyover crosses a road without a shared point.
3. You get a **Network** layer and `network.osm.pbf`.

If the lines don't form one connected network, a warning says so and
the stray lines are selected. Most often they stop just short of the
street they should meet.

This is what ArcGIS users do with "Create a network dataset". It is
also the way to work where you may not, or don't want to, use
OpenStreetMap data.

## Comparing before and after

There are two ways to analyse the networks. Both run on your own
computer.

**In QGIS itself.** The network layers are ordinary line layers with
travel columns, so the tools under **Processing Toolbox > Network
analysis** work on them:

- *Service area (from point)*: everything within a time or distance of
  a point. Run it on the before and the after layer and compare.
- *Shortest path (point to point)*: one route and its cost.

Settings for those tools:

| | Driving | Walking | Cycling |
|---|---|---|---|
| Filter on the layer first | `"car" = 1` | `"walk" = 1` | `"bike" = 1` |
| Direction field | `car_direction` | none | `bike_direction` |
| Values for forward / backward / both | `forward` / `backward` / `both` | | the same |
| Speed | field `speed_kph` | default speed 5 km/h | default speed 15 km/h |

Set the filter with a right-click on the layer, **Filter**. Choose
"Fastest" as the path type to work in travel time.

**With a router.** The output folder has `before.osm.pbf` and
`after.osm.pbf` (or `network.osm.pbf`). These are standard
OpenStreetMap files, tested with Valhalla, which the
[QGIS Network Analyst plugin](https://github.com/routing-earth/network-analyst-qgis-plugin)
runs for you: build one routing graph from each file and run the same
route, isochrone or travel time matrix on both. A router knows more
than the QGIS tools do: turn restrictions, turn delays, bollards,
ferries, and vehicle types such as bus and truck.

## What it can't tell you

- **Congestion.** Travel times come from speed limits. Traffic that
  moves onto other streets after a closure does not slow them down.
- **Public transport.** No timetables, so no bus or train trips.
- **How many people are affected.** The network says what can be
  reached. Counting homes, jobs or patients inside a service area is a
  second step with your own data (for example **Count Points in
  Polygon**).
- **Turn restrictions in QGIS's own tools.** They are in the PBF files
  for routers; the QGIS layers can't show them.
- **Whether OpenStreetMap is right.** The result is as good as the
  street data for your area. Look at the Before network before you rely
  on it.

Map data © OpenStreetMap contributors (ODbL).
