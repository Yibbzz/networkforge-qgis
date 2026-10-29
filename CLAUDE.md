# NetworkForge QGIS plugin (`networkforge-qgis`)

A QGIS plugin that lets GIS users integrate their own proposed roads,
cycleways and paths into the OpenStreetMap network correctly, and get a
**before** and **after** network back as QGIS layers (plus OSM PBF files
for routers such as Valhalla). It can also change or remove existing
streets, and build a standalone network from the user's lines alone
(no OpenStreetMap). This is a proof of concept.

All network logic lives in the separate engine,
**NetworkForge** (https://github.com/Yibbzz/networkforge, GPL-3.0).
This repo is only the QGIS front end.

## Project goal (decided 2026-10-02)

Replicate, in QGIS and for free, what ArcGIS Network Analyst's "Create
a network dataset" gives Esri users: build a routable network from your
own data, then analyse it. Here that is two tools: NetworkForge makes
the network and writes OSM PBF files; routing.earth's **QGIS Network
Analyst** plugin (Valhalla, run locally through `pyvalhalla`) builds a
graph from the PBF and does the routing. The third aim is documentation
that is better than Esri's. `docs/roadmap.md` (local only, ignored by git; a symlink to
`~/networkforge-notes/plugin-roadmap.md`, backed up in the user's private
repo `Yibbzz/networkforge-notes`) has the plan and the
ordered next steps; keep it up to date. NetworkForge Lab, the planned
experiment harness built on NetworkForge and Valhalla, has its own repo
(`~/networkforge-lab`, github.com/Yibbzz/networkforge-lab).

So: don't add routing tools or a hosted web app here (the Network
Analyst plugin covers that), and treat "the PBF works in Valhalla" as
the output that matters most.

### The PBF is the product; the GeoPackage is a nice-to-have (decided 2026-10-13)

NetworkForge is for making OSM PBF files that proper routers read. The
Before / After GeoPackage layers are a second thought: a way to look at
the result in QGIS and to use QGIS's own simple network tools. They
only say whether a mode is allowed, in which direction and at what
speed. A router reading the PBF also knows cycle lanes and tracks,
surfaces, turn restrictions, barriers and vehicle sizes.

What follows from that:
- A feature is done when a routing test on the PBF proves it
  (`tests/test_network_analyst.py` here, `tests/valhalla` in the
  engine). GeoPackage columns and styling follow only where cheap.
- Don't hold back or bend a PBF feature because the GeoPackage can't
  show it, and don't ask the engine for GeoPackage columns to mirror
  what routers already read from tags.
- In docs and tool help, lead with the PBF files and routing; present
  the layers as a preview. Say plainly where the layers can't show a
  change (a cycle lane, a banned turn, a bollard).
- Time spent on the GeoPackage side (new columns, QGIS "Service area"
  recipes, styling beyond what exists) needs the user's say-so first.

## Hard rules

- **No network logic here.** Tag rules, snapping, OSM download, export:
  all engine. If the plugin needs something the engine can't do, note it
  as an engine change request instead of re-implementing it.
- **Never import the engine into QGIS's Python.** The engine runs in its
  own environment, as a separate process, through its CLI (see below).
  QGIS's Python lacks geopandas/osmnx/osmium and must not be modified.
- **Pin the engine version** (currently `v1.4.0`) in one constant. The
  CLI's flags, JSON events and exit codes are the contract; upgrading
  the engine is a deliberate change.
- **No attribution lines in commits or PRs** (no `Co-Authored-By: Claude`,
  no "Generated with Claude Code"). Commits must show only the user.
- The user is learning as they go: explain decisions in plain language,
  give clear next steps, and verify things work rather than assume.

## User workflow (what the plugin does)

1. User picks an **extent**: map canvas, a layer's extent, or a selected
   feature's extent (like the QuickOSM plugin).
2. User picks the **custom network layer** (lines), optionally "selected
   features only".
3. User picks how travel types are defined: a **preset** (blanket, e.g.
   "primary_road" + optional maxspeed) or **"use each feature's
   attributes"**; optional "overwrite existing attributes".
4. Optional: a local **OSM extract** (.osm.pbf) - required for areas
   over 1,000 km2 (the engine refuses larger Overpass downloads).
5. Plugin runs the engine with a progress bar and cancel button.
6. Result: **Before** and **After** layers loaded and styled (custom
   edges highlighted), PBF files saved for routers. Warnings are listed
   and the features concerned highlighted; on error, the broken features
   are selected and the message links to the engine's network rules
   (`docs/network-rules.md`, formerly `tagging-guide.md`).

## Architecture

### Engine management (`engine.py`)
- On first use: ensure `uv` is available (use one on PATH, otherwise
  `pip install --target <profile>/networkforge/uv uv` with QGIS's Python -
  uv is a standalone binary in a wheel, and `--target` keeps it out of
  QGIS's own packages; where QGIS's Python has no pip, as in the Flatpak
  QGIS, download uv's own build from its GitHub releases through
  `QgsBlockingNetworkRequest` instead), then create an environment in the QGIS profile
  folder, e.g.
  `QgsApplication.qgisSettingsDirPath()/networkforge/engine-venv`,
  and install the pinned engine from the tag's zip:
  `uv pip install "networkforge @ https://github.com/Yibbzz/networkforge/archive/refs/tags/v1.4.0.zip"`
  (with `uv venv --python 3.12 --python-preference only-managed` - uv
  downloads its own Python, so QGIS's Python version doesn't matter.
  Without `only-managed` uv reuses a matching Python it finds; the
  Flatpak QGIS's Python then leaks QGIS's numpy into the engine). Don't use the `git+https://` form: it
  needs git installed, which most Windows users don't have.
- When a tool first needs the engine (not on QGIS startup, which would
  slow every start): run `networkforge --version`; install or replace
  the engine if it doesn't match the pinned version, showing progress in
  the tool's log. Clear message when offline. A startup offer to install
  can be added later if testers find the slow first run surprising.
- Run everything as a subprocess of the environment's `networkforge`
  executable. On Windows pass `creationflags=subprocess.CREATE_NO_WINDOW`
  so no console window flashes. Keep stderr in a log file for support.

### Running a build
```python
proc = subprocess.Popen([engine_exe, "build", "--json", *args],
                        stdout=subprocess.PIPE, stderr=log_file, text=True,
                        creationflags=CREATE_NO_WINDOW_ON_WINDOWS)
for line in proc.stdout:              # one JSON event per line
    if feedback.isCanceled():
        proc.kill(); break
    event = json.loads(line)
    ...                               # progress / warning / done / error
```
Use a Processing algorithm (its `processAlgorithm` already runs off the
UI thread), not a custom dialog: QGIS then provides the form, progress,
cancel, batch mode, the modeler and `qgis_process` for free.

### Data exchange: files
The engine can't see QGIS memory, so:
- Export the chosen features (all or selected) to a temporary GeoPackage.
  **Add an explicit id attribute** `nf_src_fid` = `feature.id()` and pass
  `--id-field nf_src_fid`, so engine messages name QGIS feature ids
  reliably (don't depend on the exported file's own fid matching).
- Reproject the extent to EPSG:4326 and pass `--bbox=W,S,E,N` (use the
  `=` form; western longitudes are negative).
- Load outputs with `QgsVectorLayer(f"{path}|layername=edges", name, "ogr")`.

## Engine contract (v1.4.0; v1.0.0 was the first stable one)

Full reference: the engine README ("Command line", "For programs driving
the CLI", "Outputs") and the docstring at the top of `src/networkforge/cli.py`.

Commands:
- `networkforge info --json` - one event with: `version`, `presets`
  (name -> `{tags, modes}`), `network_types`, `modes`,
  `max_overpass_area_km2`, `osm_formats`, `gpkg_edge_columns`,
  `edit_id_fields` (`osm_id`, `osmid`), `remove_field` (`remove`),
  `standalone` (true), `join_at` (`crossings`, `vertices`),
  `turn_restriction_fields` (`restriction`, `restriction:hgv`, ...),
  `tag_keys`, `tag_values` (valid values for `highway`, `oneway` and
  the access keys: `access`, `foot`, `bicycle`, `bus`, `hgv`, ...),
  `tag_patterns` (regexes for `maxspeed`, `lanes`, `layer` and the
  limits `maxheight`, `maxweight`, ...).
  **Build dropdowns and value maps from this, don't hard-code them.**
- `networkforge check --custom F [--custom-layer L] [--id-field N]
  [--extent F | --bbox W,S,E,N] [--preset P] [--tag K=V ...]
  [--overwrite-tags] [--network-type T] --json` - validate, no download.
- `networkforge build` - the same input options plus `--osm-source F`,
  `--snap-tolerance M` (default 1), `--no-strict`, and outputs
  `--out F` (after, OSM/PBF), `--baseline-out F` (before, OSM/PBF),
  `--gpkg F` (after, GeoPackage), `--baseline-gpkg F` (before, GeoPackage).
- `networkforge build --no-osm` - a standalone network from the custom
  lines alone. Takes `--join-at crossings|vertices` (default
  `crossings`; only valid with `--no-osm`), `--snap-tolerance`, `--out`
  and `--gpkg`. **Must not** be given `--extent` / `--bbox`,
  `--osm-source`, `--baseline-out` or `--baseline-gpkg` (exit code 2).
  The plugin doesn't pass `--network-type` either: there is no OSM
  network to choose.

JSON events on stdout (stderr is human-readable log text):
```json
{"event": "progress", "step": 2, "total": 13, "message": "Downloading OSM network"}
{"event": "warning", "message": "...", "features": [17]}          // or "fields": ["length"]
{"event": "done", "outputs": {"gpkg": "...", "baseline_gpkg": "..."}, "nodes": 1, "edges": 2,
 "custom_edges": 3, "modified_edges": 0, "removed_edges": 0, "turn_restrictions": 0, "tagged_nodes": 0}   // check: "features", "modes", "edits", "turn_restrictions", "points"
{"event": "error", "type": "InvalidTagsError", "message": "...", "guide": "fixing-tag-errors",
 "issues": [{"feature": 17, "message": "maxspeed='fast' is not a valid OSM speed"}]}
```
- `guide` is `"<file>.md#anchor"` in the engine's `docs/`
  (`network-rules.md#fixing-tag-errors`), or, from engines up to
  v1.0.1, a bare anchor in `docs/tagging-guide.md` (what that page was
  called then). Link to the GitHub copy for the pinned version. Docs
  for users link to `blob/v<pinned>/docs/network-rules.md`; change
  those links when the engine is upgraded.
- `issues[].feature` / `warning.features` are `--id-field` values
  (feature `null` = not about one feature).

Exit codes: 0 ok, 1 unexpected, 2 bad usage (a plugin bug), 3 unusable
input, 4 OSM download failed, 5 structural check failed (an engine bug).

Since v0.5.0 a custom line that doesn't connect to the rest of the
network is a `warning` event naming the `features`, not an error; the
line is kept in the output. Only when no line reaches the network does
the build fail (`NoIntersectionError`).

Changing existing streets (since v0.7.0 / v0.8.0): a custom feature with
an OSM way id in `osm_id` or `osmid` changes that street instead of
adding a line (only attributes that differ from OSM, only on the stretch
it lies along); with `remove` = `yes` the stretch is taken out. The
plugin only has to export those fields, which it does. Changed edges
have `modified` = `yes` in the after GeoPackage. Errors use the guide
anchor `changing-existing-streets`.

Turn restrictions (since v0.12.0): a custom feature with a `restriction`
field (or `restriction:hgv` / `:bus` / `:motorcar` / `:bicycle`;
optional `except`) drawn from one street, through exactly one junction,
onto another becomes an OSM turn restriction relation in the after (or
standalone) PBF. It is not a row in the GeoPackage, so nothing can be
styled or counted in QGIS: the plugin reports `turn_restrictions` from
the `done` event. It needs no `highway`. A line through no junction or
several is an error naming the feature; a value that disagrees with the
drawn turn is a warning. Guide anchor: `turn-restrictions`. The plugin
only has to export the fields (GeoPackage keeps the colon in
`restriction:hgv`).

Points (since v1.0.0): a point feature in the custom layer with node
tags (`barrier=bollard`, `highway=traffic_signals`, `crossing=zebra`, ...)
tags the node it is on or cuts the nearest street there. The engine
reads ONE custom layer, and a QGIS layer has one geometry type, so the
tools take an optional second `POINTS` layer and `export_custom` writes
lines and points into one mixed-geometry GeoPackage layer. Lines keep
`nf_src_fid` = their QGIS id; a point's id is raised by a round number
(`_point_base`, at least 1,000,000) so the two can't be confused;
`_source_of` maps an id in an event back to (layer, QGIS id) for messages
and selection. In "Build scenario network" and "Check" the line layer is
optional when points are given. The `done` event has `tagged_nodes`;
`check`'s has `points`. A separate `--custom-points` option with its own
ids would be cleaner: an engine change request, not urgent.

Also since v1.0.0, all fields only (nothing for the plugin to do but
document): ferries (`route=ferry`, no `highway`, optional `duration`),
`remove_tags` (`info`: `remove_tags_field`) to delete tags from a street
or node, via-way turn restrictions (a turn line through two junctions),
and warnings for unknown values of `surface`, `sidewalk`, ... (`info`:
`tag_values`). The CLI, exit codes and JSON events are now stable: fields
may be added, none removed without a new major version.

Since v1.1.0 (all events and fields, nothing the plugin must do):
a `warning` event when a local OSM file (`--osm-source`) doesn't cover
the whole area, with `gaps`, a `[west, south, east, north]` box for
each uncovered part (the plugin lists the message; drawing the boxes
would be a nice extra); a warning naming fields that look like OSM tags
but aren't written; `ramp`, `ramp:wheelchair`, `ramp:stroller`,
`ramp:bicycle` are written and checked (`info`'s `tag_keys` /
`tag_values`); outputs that would overwrite an input or each other, or
a missing output folder, are refused as input errors.

Traffic (since v1.2.0): `networkforge traffic --pbf F --out F.tar
[--settings F.json|.toml] [--streets F --id-field N] --json` puts time
bands (road class) and single streets (a line layer: `days`, `time`,
`factor`, optional `direction` both/forward, `osm_id`/`osmid`) on a
network as Valhalla predicted traffic and writes Valhalla's graph as a
tar (Network Analyst: "From Tar"). Needs the engine's `traffic` extra
(pyvalhalla): `engine.ensure_traffic` installs it into the engine's
environment the first time "Add traffic" runs, not for every user.
`done`: `streets`, `segments`, `by_road`, `bands`, `streets_not_found`,
`single_streets`, `single_segments`, `unmatched`; unmatched streets are a
warning with `features`. Since engine v1.3.0: `speed_kph` wherever `factor` goes (the tool's
bands column takes "0.6", "25 km/h" or "15 mph"), `--speed-table F.csv
--speed-table-id-field N` (the tool exports any table to CSV with
`nf_src_fid`; warnings carry `rows`, `done` has `table_rows` and
`unmatched_rows`), and `direction` backward; short, much-slower bands are
lifted and warned about (Valhalla's packed week can't hold them). `info`'s `traffic` has days, factor_range,
roads, street_fields, directions. Only timed requests use it: Network
Analyst's routing panel (time box) sends a time, its Processing tools
don't. Guide: `docs/traffic.md` in the engine. A deliberate exception to
"the PBF is the product": OSM has no tag for a week of speeds.

Since v1.4.0 (all additions): a `restrictions` layer in every
GeoPackage (one line per turn restriction in the PBF written with it,
OSM's and the user's: `relation_id`, `from_way`, `via_node`,
`via_ways`, `to_way`, `custom`, the relation's tags; `info` has
`gpkg_layers`, `gpkg_restriction_columns`); `modified` / `custom` = yes
on the nodes points tagged; node columns `bus`, `psv`, `hgv`,
`wheelchair`, `toll`, `maxheight`, `maxwidth`, `maxweight`, `entrance`;
features (and traffic's single streets) whose coordinates can't be
longitude / latitude in their CRS are an input error naming them.

Since v0.11.1 attributes that aren't tags keep their type in the
GeoPackage, and text `True` / `False` is no longer read as `yes` / `no`
(a boolean field still is).

Standalone networks (since v0.10.0): a `warning` event names the
`features` outside the largest connected piece. Guide anchor:
`a-network-of-your-own-lines`.

The engine leaves a GeoPackage column out when no edge has a value:
`custom` is missing from the before network and from a build of changes
only, `modified` from a build with no changes. Check a field exists
before styling by it. `osmid` is the OSM way id (empty on custom edges).
Since v0.11.0 `oneway` in the GeoPackage is always OSM text (`yes`,
`no`, `-1`), never a boolean, and the `done` event's `edges`,
`custom_edges`, `modified_edges` and `removed_edges` count one per
street, the same as the GeoPackage's rows, so the plugin reports them
as they are.

Since v0.9.0 every connected piece of the network is kept. The PBF holds
OpenStreetMap as it is: way ids, all tags, turn restrictions, ferries.

GeoPackage `edges` columns for analysis: `car`, `bike`, `walk` (bool),
`speed_kph`, `length_m`, `car_minutes`, `bike_minutes`, `walk_minutes`,
`car_direction`, `bike_direction` (`forward`/`backward`/`both`), and
`custom` (`yes` on custom edges). One row per street; edges end exactly
on nodes. QGIS "Service area" works directly: filter `"car" = 1`,
direction field `car_direction` (values forward/backward/both), speed
field `speed_kph`.

## Repo layout (target)
```
networkforge-qgis/
├── networkforge_qgis/          # the plugin package QGIS loads
│   ├── metadata.txt            # name=NetworkForge, qgisMinimumVersion=3.34, experimental=False, GPL
│   ├── __init__.py             # classFactory(iface)
│   ├── plugin.py               # registers/unregisters the Processing provider
│   ├── provider.py
│   ├── engine.py               # install/version-check/run the engine CLI, parse events
│   ├── algorithms/
│   │   ├── common.py           # base class: export layer, run engine, select features
│   │   ├── build_network.py    # "Build scenario network"
│   │   ├── standalone_network.py # "Build standalone network" (no OSM)
│   │   ├── add_traffic.py      # "Add traffic (time of day)" (engine `traffic`)
│   │   ├── check_layer.py      # "Check custom network layer"
│   │   └── engine_info.py      # "Engine information" (version, reinstall)
│   ├── styling.py              # renderers for the result layers (built in code, not .qml)
│   ├── compat.py               # names that differ between QGIS 3.34, 3.44 and 4
│   ├── engine_info.json        # saved `info --json` of the pinned engine; forms are built from it
│   └── icons/
├── tests/                      # pytest + pytest-qgis
├── .github/workflows/          # tests in qgis/qgis Docker image; package + publish
├── README.md, LICENSE (GPL-3.0), CHANGELOG.md
└── CLAUDE.md                   # this file
```

## Algorithms

1. **Build scenario network** - inputs: extent (QgsProcessingParameterExtent),
   custom layer (lines; respect "selected only"; optional when a points
   layer is given), optional points layer, preset (enum from
   `info`, plus "Use feature attributes"), extra tags (e.g. maxspeed),
   overwrite checkbox, network type (default `all`), optional OSM file,
   output folder. Outputs: before/after GeoPackages loaded + styled,
   before/after PBF paths. Warn early if the extent is over 1,000 km2
   and no OSM file is given (the engine will refuse it).
2. **Check custom network layer** - runs `check --json`; lists issues,
   selects the offending features, links each to the guide.
3. **Build standalone network** - runs `build --no-osm`; inputs: the
   network layer, travel type (as above), where lines join (enum from
   `info`'s `join_at`), output folder, snap distance. No extent, OSM
   file or network type. Outputs: `network.gpkg` loaded as "Network"
   and `network.osm.pbf`. No OSM credit: it holds no OSM data.
4. **Add traffic (time of day)** - runs `traffic`; inputs: a network PBF
   (any the tools made), a table of time bands (QgsProcessingParameterMatrix:
   Name, Days, Time, Roads, Factor; two example rows), an optional
   single-streets line layer (exported with `nf_src_fid`, its warnings
   select features), output `.tar`. Installs pyvalhalla on first use
   (`engine.ensure_traffic`). Tested by `test_add_traffic.py` (fake
   engine) and in `test_network_analyst.py` through the Network Analyst
   plugin's own routingpy client with a `date_time`, as its routing
   panel sends it (its Processing tools send no time).
5. No tool for creating a custom layer: the user decided against it
   (users make a line layer in QGIS themselves). Don't add one back.
6. Styles: after-edges coloured by `highway`, custom edges bold pink and
   changed edges bold orange on top; the standalone network is coloured
   by `highway` only (every edge is custom). The `nodes` layer is loaded
   too ("After nodes", "Before nodes" unticked, "Network nodes" only when
   points were given), filtered with `setSubsetString` to what routers act
   on (`styling._NODE_GROUPS`: barriers, kerbs, signals, stop / give way,
   crossings, level crossings), built from the columns the file has.
   Stacked by `layerSortKey`, highest on top: After turn restrictions,
   After nodes, After network, then the same for Before (its turn
   restrictions and nodes unticked). Nodes your points tagged
   (`custom` / `modified` = yes, engine v1.4.0) are ringed and always
   shown. The `restrictions` layer (engine v1.4.0, always in the file,
   empty too) is drawn by `style_restrictions`: arrows, the user's
   (`custom` = yes) bold pink. A standalone network loads its nodes /
   restrictions layers only when the done event counts `tagged_nodes` /
   `turn_restrictions`.

## Gotchas already learned (from the engine work)
- `qgis_process` network algorithms need `--PROJECT_PATH=<an .qgs>` placed
  **before** the `--` separator; an empty project file is enough.
- A `PYTHONPATH` or active virtualenv in the environment breaks QGIS's own
  Python ("Couldn't load SIP module"): don't leak the engine's
  environment into QGIS, and run the engine with its own clean env.
- Use GeoPackage, not Shapefile (Shapefiles cut field names to 10
  characters: `motor_vehicle` -> `motor_vehi`).
- `car` in the GeoPackage excludes service roads (OSMnx's drive rule).
- OSM data needs credit: show "© OpenStreetMap contributors" (ODbL).
- Engine limitations to state in the plugin docs: no public transport,
  no traffic simulation; turn restrictions and barriers (OpenStreetMap's
  and the user's own) are for routers, QGIS's own network tools ignore
  them; existing streets can be re-tagged or removed, not redrawn;
  county-sized areas need a lot of memory.
- Upgrading the engine: change `ENGINE_VERSION` in `engine.py`, save the
  new `networkforge info --json` as `engine_info.json` (indent 1), and
  run the end-to-end tests (`pytest -m engine`), which install the pinned
  tag from GitHub - so the tag must be pushed first.

## Development environment
- Develop on the host with **QGIS LTR** (3.40+) installed, not in the
  engine's dev container (it's headless and can't run QGIS desktop).
- Symlink `networkforge_qgis/` into the QGIS profile's `python/plugins`
  folder; install the **Plugin Reloader** plugin to reload without restarts.

## Testing
- `pytest` + `pytest-qgis`, run in CI inside the `qgis/qgis` Docker image
  (tags `ltr` and `latest`), like the engine's QGIS job.
- A `windows` job in `tests.yml` runs the same tests on
  `windows-latest` (`test_network_analyst.py` in a step of its own):
  QGIS LTR from Chocolatey's `qgis-ltr` (qgis.org's installer), tests
  run with its `bin\python-qgis-ltr.bat`, engine in
  `NF_TEST_ENGINE_DIR` = `...\Zoë Müller\networkforge`. It can't be run
  from Linux: check the job on GitHub after changing it or `engine.py`.
- A `macos` job (since 2026-10-28) runs the same tests on
  `macos-latest` (Apple silicon) with qgis.org's LTR installer
  (Homebrew's `qgis@ltr` cask, `/Applications/QGIS-LTR.app`). Its Python
  (`Contents/MacOS/python3.12`) can't start outside the app without
  `PYTHONPATH` = its standard library (`Contents/Resources/python3.11`,
  whatever the name), `lib-dynload` and `site-packages`; the job sets
  that. The plugin clears `PYTHON*` for the engine, so the stand-in
  engine runs with `NF_TEST_FAKE_PYTHON` (`/usr/bin/python3`) there.
- Engine v1.0.0 couldn't open OSM files in folders with non-ASCII
  letters on Windows (`osmium`); v1.0.1 fixed it (the engine's
  `paths.py`). Two tests in `test_end_to_end.py` guard it.
- `tests/test_qgis_process.py` starts the real `qgis_process`
  (`NF_QGIS_PROCESS`, or found on PATH) with `QGIS_CUSTOM_CONFIG_PATH`
  set to a new folder holding a copy of the plugin, with uv taken off
  PATH: the first tool run there is a new user's first run. No accents
  in its paths: on Windows `qgis_process` is a .bat file, and cmd.exe is
  not what users go through. `test_end_to_end.py` has the accents.
- Unit tests fake the CLI (a stub emitting canned JSON lines) - fast.
- One end-to-end test installs the pinned engine and builds from a small
  local extract (`--osm-source`), never Overpass. A tiny extract can be
  generated with the engine itself (`networkforge.write_osm`) or taken
  from Geofabrik (e.g. Monaco, <1 MB).
- `tests/test_network_analyst.py` (marker `network_analyst`, part of the
  normal run and CI) routes on the PBF files with routing.earth's Network
  Analyst plugin: it downloads the plugin at a pinned commit (`qgis-v3`
  branch for QGIS 3, `master` for QGIS 4) and a pinned `pyvalhalla` into
  `.pytest_cache/network-analyst`, serves a graph on port 8002 (the
  plugin's "localhost" provider) and runs the plugin's Processing tools
  (`valhalla:valhalla_directions_auto`, ...). `NF_NETWORK_ANALYST=latest`
  uses the newest commit and newest pyvalhalla instead; the weekly
  workflow `network-analyst-latest.yml` runs that. Things learned:
  their package is called `valhalla`, the same as pyvalhalla's module, so
  pyvalhalla lives in its own environment; their enum parameters need
  explicit values from Python; start and end trips mid-block, because
  Valhalla is unpredictable about trips that start exactly on a junction;
  kill `valhalla_service` rather than terminate it (it takes ~10 s to
  wind down). A failure here that is a wrong network belongs in the
  engine; add a scenario for every new kind of change the engine learns.
- A one-way change (`oneway=yes` on a feature with an OSM id) runs in the
  direction the feature is drawn, not the OSM way's direction.
- `tests/test_easy_r5.py` (marker `easy_r5`, in the normal run and CI;
  skipped on QGIS 4, which Easy-R5 doesn't support) is Esri's public
  transit tutorial in miniature with GISBoost's Easy-R5 plugin at a
  pinned commit: NetworkForge's after PBF plus two GTFS feeds, transit
  service areas at 5:15 pm and 2:00 pm. The PBF in R5 itself is tested
  in the engine (`tests/r5`, r5py). Things learned: R5 drops connected
  pieces under about 40 streets (hence an 8 x 8 grid) and reports whole
  minutes; Easy-R5's Java download fails to unpack on Python 3.10.12
  (CPython gh-107845; the test works round it); Easy-R5 refuses a
  transit run where no trip uses transit; R5 won't change buses between
  two stops at the identical spot; Easy-R5 sizes its isochrone grid from
  MAX_TRIP_DURATION (default 90 min); no wheelchair mode. Its service
  areas are empty with GDAL 3.11+ (QGIS 3.44, so Windows and
  `qgis/qgis:ltr` since 2026-10-27): it contours at one fixed level
  (`gdal_contour -p -fl 15`), which newer GDAL turns into no polygon;
  `-fl 0 15` works on both. The service-area test is a strict xfail on
  GDAL 3.11+ until Easy-R5 changes it.

## Pictures in the docs
- `scripts/make_examples.py` builds the example networks with the
  plugin's tools and draws them with Valhalla routes
  (`docs/images/example-*.png`, used by `docs/examples.md`). Rerun it
  when styling or an example changes; the numbers in `docs/examples.md`
  are printed by it and must be kept in step by hand.
- `docs/tutorial.md` is **the user's own writing**: fix formatting only
  (broken lists, links, image paths), never change a word without being
  asked. It uses `docs/images/tutorial-bridge-area.webp` and
  `tutorial-qgis-01..16.webp` (WebP at quality 85: a fifth of the PNG size), and links to
  `docs/tutorial-data/reading-bridge.gpkg`. The other pictures the
  tutorial script makes are in `.gitignore`.
- `scripts/make_tutorial_example.py` makes the tutorial's worked example:
  getting to work over a new Thames bridge east of Reading, in three
  stages (the bridge; the business park's road opened by removing two
  barriers and raising its limit; a bollard on Sonning Bridge). It
  writes `docs/images/tutorial-bridge-*.png` and
  `docs/tutorial-data/reading-bridge.gpkg`, and prints the trip times
  the tutorial quotes. It downloads the streets through the engine
  (Overpass) and the rivers from the Overpass API, so it needs the
  internet, and it finds the park's streets by OpenStreetMap way id:
  if OpenStreetMap changes there, its `assert` says so. The scheme is
  invented, not the official design: say so wherever the pictures are
  used.
- `scripts/make_tutorial_screenshots.py` takes the tutorial's QGIS
  screenshots (`docs/images/tutorial-qgis-*.webp`): real QGIS desktop on
  a virtual screen (`xvfb-run`; QGIS 3.34 crashes with
  `QT_QPA_PLATFORM=offscreen` here), in a profile of its own
  (`--profiles-path`, never the user's) holding this plugin and the
  Network Analyst plugin, does the steps in
  `scripts/tutorial_screens_in_qgis.py`. Run `make_tutorial_example.py`
  first. Things learned: don't filter a GeoPackage layer in place
  (`setSubsetString`), the file's other layers then load without a CRS;
  give a form made from Python its extent as text with `[EPSG:4326]`,
  not as a layer. The routing screenshots (07-11 and 15-16) go through the
  Network Analyst plugin's own panel, as a reader would: its settings
  dialog, "From PBF" for a graph of each PBF, its local server, the car,
  two waypoints and Execute. pyvalhalla is copied from the tests' cache
  to `<profile>/valhalla/pyvalhalla`, where their "Install" button puts
  it; stop their server and wait for the process to end before starting
  it on another graph (the start/stop button is one toggle).
- `docs/tutorial-transit.md` is **the user's own writing** (since
  2026-10-20; like `tutorial.md`, fix formatting only, never change a
  word without being asked). It is Esri's public transit tutorial done with Easy-R5: Cincinnati,
  Metro's and TANK's GTFS feeds, 30-minute service areas from Fountain
  Square at 5:15 pm and 2:00 pm, and in place of Esri's wheelchair mode
  two closed city stairways at Brighton (OSM ways 197716033, 197715354,
  `foot=no`) reopened, compared from Klotter Avenue; then (step 8) an
  invented tram line up Vine Street to Uptown as an Easy-R5 "Build
  scenario" (new line, vertices = stops, 18 km/h, every 10 min), compared
  over a 60-minute departure window (2-3 pm): a new line has a frequency,
  not a timetable, so R5 draws its departures at random and a 1-minute
  window gives a different area each run (11.0 vs 11.3 km2); over an hour
  it varies by about 0.1 km2. `NF_ONLY=16` retakes just the form picture. Esri's tutorial changes neither streets
  nor timetables: steps 7 and 8 go beyond it.
  `scripts/make_transit_tutorial_example.py` writes
  `docs/tutorial-data/cincinnati-transit.gpkg`, downloads the feeds and
  builds everything into `.pytest_cache/transit` (the street build is
  240 km2 through Overpass: 8 minutes, 4 GB; kept between runs), and
  prints the areas the tutorial quotes. Then
  `scripts/make_transit_screenshots.py` (with
  `transit_screens_in_qgis.py`) takes `docs/images/transit-qgis-*.webp`
  in QGIS desktop with Easy-R5. The feeds expire (this pair overlaps
  5 Oct - 6 Nov 2026): with new feeds pick a weekday both run, change
  `DATE` in both scripts and the tutorial, and rerun both. Things learned:
  the stairways assert they are still closed in OSM; a headless QGIS
  started by `make_examples` can't read a GeoPackage layer's CRS (pass
  memory layers to Easy-R5); Overpass refuses requests without a
  User-Agent; wait for a Processing form with its `algorithmFinished`
  signal, not by reading its log; on this 7 GB machine R5 gets killed
  (exit -9) when other apps are open, so the scripts pass
  `JAVA_HEAP_GB` 3.
- `docs/tutorial-traffic.md` is **the user's own writing** (since
  2026-10-24; like `tutorial.md`, fix formatting only, never change a
  word without being asked). It is deliberately simple: Bristol,
  Geofabrik's `bristol-latest.osm.pbf` given straight to "Add traffic" (no
  build), the tool's two example bands, and 15-minute driving isochrones
  from Southmead Hospital in the Network Analyst panel at Monday 03:00 and
  08:00 (about 81 and 44 km2). `scripts/make_traffic_tutorial_example.py`
  downloads the extract into `.pytest_cache/traffic-bristol`, writes
  `docs/tutorial-data/bristol-traffic.gpkg` (the hospital) and prints the
  areas; `scripts/make_traffic_screenshots.py` (with
  `traffic_screens_in_qgis.py`) takes `tutorial-traffic-qgis-01..07`.
  The panel's isochrone page is `menu_widget` row 2, intervals in seconds
  (`ui_isochrone_intervals`). **Network Analyst 6.0.1 / 7.0.1 crash with
  "Time settings" ticked** (their issue #64, fixed in their master): the
  tutorial, the tool's help and the engine's guide use Options > Extra
  JSON `{"date_time": {"type": 1, "value": "2026-10-19T08:00"}}`; change
  them back when a fixed release is out. Its "From Tar" moves the tar into
  its library and names the graph after the file. An earlier Reading
  version (bridge queues, a speed table) was dropped as too complicated.
- `scripts/make_form_images.py` grabs the tools' forms from QGIS desktop
  running off-screen (`docs/images/*-form.png`). Rerun it whenever a
  tool's parameters or help text change.

## Hands-on testing
- `manual-test/` holds the checklist a person works through in QGIS
  (`README.md`), a project (`manual-test.qgz`), the layers
  (`test-data.gpkg`) and a Monaco extract. `scripts/make_test_data.py`
  makes them and prints the log lines each test should show; when a
  tool's messages or the engine's counts change, rerun it and update the
  expected lines in the checklist by hand.

## Packaging
- `qgis-plugin-ci` builds the zip from `metadata.txt` and publishes to
  plugins.qgis.org on a version tag (secret `QGIS_PLUGIN_TOKEN`). Start
  as `experimental=True`; stable (`experimental=False`) since 2026-10-28.
- plugins.qgis.org scans every upload and **blocks** a version on a
  critical bandit or detect-secrets finding (0.5.0 was blocked for
  bandit B603, "subprocess call"); a blocked version can only be
  replaced by a new one. `scripts/plugin_checks.sh` runs the same tools
  (newest versions, as the site does) in `tests.yml` and before
  `release.yml` publishes. `networkforge_qgis/.bandit` skips B404 / B603
  with the reason: starting the engine as a program is the design.
  Their Qt6 check (warnings only) is QGIS's `pyqt5_to_pyqt6.py`;
  `scripts/qt6_check.sh` runs it in `qgis/qgis:latest`. Write QGIS enum
  values with their enum's name (`QgsFeatureSink.Flag.FastInsert`):
  QGIS 3.34 accepts that too.

## Milestones (do in order; each ends with something that visibly works)
1. **Skeleton** - plugin loads; "NetworkForge" appears in the Processing Toolbox.
2. **Engine manager** - installs the pinned engine into its own env and runs
   `networkforge info --json`. **Verify on Windows** (most users) and the
   developer's OS before going further; this decides the whole approach.
3. **Build algorithm** - end to end on a real area: before/after layers
   loaded and styled, progress and cancel working.
4. **Errors and warnings** - issues/warnings select and highlight features;
   messages link to the guide.
5. **Check + styles.**
6. **Tests + CI.**
7. **Package and publish as experimental.**
