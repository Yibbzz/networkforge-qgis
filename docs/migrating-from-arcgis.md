# Moving an ArcGIS street network to QGIS

You have street data that was prepared for ArcGIS Network Analyst, and
you want to route on it in QGIS without OpenStreetMap. This guide shows
how, with **Build standalone network**.

The short version: an ArcGIS network dataset describes streets with
fields and settings of your own choosing; NetworkForge and Valhalla read
the handful of attribute names that OpenStreetMap uses. So moving over
is mostly **adding a few fields with QGIS's field calculator**. One
part, overpasses stored as elevation fields, takes more care.

## What comes across, and what doesn't

| In ArcGIS | Here | Effort |
|---|---|---|
| Street and path feature classes | one line layer | open it |
| Road class or hierarchy | `highway` | one expression |
| One-way field | `oneway` | one expression |
| Speed, or travel time and length | `maxspeed` | one expression |
| Restrictions per vehicle (cars, buses, lorries, walking) | `motor_vehicle`, `bus`, `hgv`, `foot` | one expression each |
| Unpaved roads, height and weight limits, tolls | `surface`, `maxheight`, `maxweight`, `toll` | one expression each |
| Street names | `name` | rename |
| Turn feature class | lines with `restriction` | check the drawing |
| Connectivity policy (End Point, Any Vertex) | the "Lines join" setting | one choice |
| Elevation fields (`F_ZLEV`, `T_ZLEV`), z coordinates | `bridge`, `tunnel`, `layer` | **by hand** where streets cross at different levels |
| Costs from your own fields (surveyed minutes, a custom impedance) | not used by the router | kept as fields for QGIS's own tools |
| Turn delays you set yourself | not possible | Valhalla works out its own |
| Travel modes | chosen in the Network Analyst plugin when you route | nothing to move |
| Historical or live traffic, public transport | not supported | |

## Step 1: open the data in QGIS

- A **file geodatabase** opens directly: drag the `.gdb` folder into
  QGIS and pick the street feature class (and the walking paths and
  turns, if there are any). The network dataset itself can't be read,
  and isn't needed: only the feature classes it was built from.
- Save each as a **GeoPackage** (right-click, Export, Save Features As).
  Don't use a Shapefile: it shortens field names to ten characters.
- If streets and walking paths are separate layers, merge them
  (**Vector > Data Management Tools > Merge Vector Layers**) once both
  have the fields below.

## Step 2: add the OpenStreetMap fields

Open the attribute table, start the field calculator, and for each row
of this table create a **new text field** with the name on the left.
Keep your old fields: they do no harm.

The expressions use the field names of the data in Esri's "Create a
network dataset" tutorial, which follows a common commercial street-data
layout. Put your own field names and codes in their place.

| New field | Expression | What it does |
|---|---|---|
| `highway` | `CASE WHEN "FUNC_CLASS" = '1' THEN 'motorway' WHEN "FUNC_CLASS" = '2' THEN 'trunk' WHEN "FUNC_CLASS" = '3' THEN 'primary' WHEN "FUNC_CLASS" = '4' THEN 'tertiary' ELSE 'residential' END` | The kind of street. **Required on every line.** |
| `oneway` | `CASE WHEN "DIR_TRAVEL" = 'F' THEN 'yes' WHEN "DIR_TRAVEL" = 'T' THEN '-1' ELSE 'no' END` | `yes` is one-way in the direction the line is drawn, `-1` against it. |
| `maxspeed` | `to_string("KPH")` | Speed limit in km/h. For miles per hour: `to_string("MPH") \|\| ' mph'`. |
| `name` | `"ST_NAME"` | Used in directions. |
| `motor_vehicle` | `if("AR_AUTO" = 'N', 'no', NULL)` | Closed to motor traffic. Leave empty where allowed. |
| `foot` | `if("AR_PEDEST" = 'N', 'no', NULL)` | No walking. |
| `bus` | `if("AR_BUS" = 'N', 'no', NULL)` | No buses. |
| `hgv` | `if("AR_TRUCKS" = 'N', 'no', NULL)` | No lorries. |
| `surface` | `if("PAVED" = 'N', 'unpaved', NULL)` | Lets a router avoid unpaved roads. |

Notes:

- **`highway` is a judgement.** A five-step road class has to be spread
  over OpenStreetMap's types. What matters most for routing is the
  split between motorways, main roads and local streets. The full list
  is in the
  [tagging guide](https://github.com/Yibbzz/networkforge/blob/v1.0.0/docs/tagging-guide.md#attributes).
  Paths for walking only are `footway`; slip roads are `motorway_link`,
  `trunk_link` and so on.
- **One-way codes differ between datasets.** Some use `FT` and `TF`,
  some `F` and `T`, some `1` and `-1`. "From-to" is the direction the
  line is drawn, which is `yes`. Check a street you know.
- **No speed field, only travel time?** Work the speed out:
  `to_string(round(("Meters" / 1000) / ("FT_Minutes" / 60)))`.
- **Height and weight limits** are numbers in metres and tonnes:
  `maxheight` = `3.5`, `maxweight` = `7.5`.
- A value OpenStreetMap doesn't know is not an error for every field,
  but a wrong `highway`, `oneway` or `maxspeed` stops the build with the
  features selected. **Check custom network layer** finds these in
  seconds.

## Step 3: overpasses and underpasses

This is the one part that isn't a field calculation.

ArcGIS data often cuts **every** street at every crossing, bridges
included, and uses two elevation fields to say which line ends really
meet: an end at level 0 and an end at level 1 at the same spot do not
connect. NetworkForge has no levels at a point. As in OpenStreetMap,
two lines that share a vertex are joined there, so those ends would be
joined and a flyover would become a crossroads.

To keep them apart, the upper street must be **one line that passes
over** the crossing with **no vertex at it**:

1. Find the places: select the lines where an elevation field is not 0
   (`"F_ZLEV" <> 0 OR "T_ZLEV" <> 0`).
2. Where a bridge is cut at the street it crosses, join its two pieces
   into one line (select both, **Edit > Edit Geometry > Merge Selected
   Features**).
3. Delete the merged line's vertex at the crossing: with the **Vertex
   Tool**, click that vertex and press Delete. The line now passes over
   the street below without sharing a point with it.
4. Set `bridge` = `yes` and `layer` = `1` on it (for a tunnel, `tunnel`
   = `yes` and `layer` = `-1`), so routers and maps know what it is.

The street underneath can stay as it is, cut in two or not.

Lines with a level only at one end, such as ramps, need nothing: they
meet the bridge at its end, which is right.

This only works with the "Only where lines share a vertex" setting in
step 5. With the other setting, lines are joined wherever they touch.

A small network has a handful of these and it takes minutes. A city has
hundreds; if that is your case, tell us on the
[engine's issue tracker](https://github.com/Yibbzz/networkforge/issues),
because reading elevation fields directly is the main thing missing for
ArcGIS data.

## Step 4: turns

If the data has a turn feature class and QGIS shows it as lines, each
turn is already drawn the way NetworkForge wants: from one street,
through the junction, onto the next. Add a field `restriction` and set
it to the kind of turn: `no_left_turn`, `no_right_turn`,
`no_straight_on` or `no_u_turn`. Then merge the turns into the street
layer, or copy them in.

Each turn line must start and end part-way along its streets and pass
through the junction. If the build says a line "doesn't pass through a
junction", it stops short: extend it.

## Step 5: build

Run **Build standalone network**:

- **Network layer**: your street layer.
- **Travel type**: "Use each feature's own attributes".
- **Lines join**: "Only where lines share a vertex". Data prepared for
  ArcGIS has a vertex wherever streets really meet, so this matches the
  "Any Vertex" and "End Point" connectivity you had, and never joins
  lines that merely cross. It is also what keeps the bridges of step 3
  apart from the streets under them.

If the tool warns that the network is in separate pieces, the lines it
selects don't reach the rest. Usually their ends are a few centimetres
apart: raise the snap distance under Advanced parameters.

You get a **Network** layer and `network.osm.pbf`.

## Step 6: check it against what you had

Before trusting it, compare a few trips you know with the old network:

- In QGIS: **Shortest path (point to point)** on the Network layer. Its
  `car`, `walk` and `car_direction` columns show at a glance whether
  one-way streets and closed streets came across.
- In the Network Analyst plugin: build a graph from `network.osm.pbf`
  and run the same route by car and on foot.

Look hardest at the overpasses from step 3, the one-way streets, and
any street only some vehicles may use.

## What will be different

- **Travel times.** ArcGIS used your minutes field. Valhalla works out
  its own from the road type and speed limit, and adds time for turns
  and junctions. Expect similar routes and somewhat different times.
- **Your own cost fields** are still in the Network layer, with their
  types, so QGIS's own tools can use a minutes field as the cost. The
  router can't.
- **Hierarchy** is no longer a setting: the router prefers bigger roads
  on long trips because of their `highway` type.
- **Size.** A town or a city district is fine. A whole county or country
  needs a lot of memory.
