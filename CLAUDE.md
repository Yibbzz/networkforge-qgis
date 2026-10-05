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
that is better than Esri's. `docs/roadmap.md` has the plan and the
ordered next steps; keep it up to date.

So: don't add routing tools or a hosted web app here (the Network
Analyst plugin covers that), and treat "the PBF works in Valhalla" as
the output that matters most.

## Hard rules

- **No network logic here.** Tag rules, snapping, OSM download, export:
  all engine. If the plugin needs something the engine can't do, note it
  as an engine change request instead of re-implementing it.
- **Never import the engine into QGIS's Python.** The engine runs in its
  own environment, as a separate process, through its CLI (see below).
  QGIS's Python lacks geopandas/osmnx/osmium and must not be modified.
- **Pin the engine version** (currently `v0.10.0`) in one constant. The
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
   are selected and the message links to the engine's tagging guide.

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
  `uv pip install "networkforge @ https://github.com/Yibbzz/networkforge/archive/refs/tags/v0.10.0.zip"`
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

## Engine contract (v0.10.0)

Full reference: the engine README ("Command line", "For programs driving
the CLI", "Outputs") and the docstring at the top of `src/networkforge/cli.py`.

Commands:
- `networkforge info --json` - one event with: `version`, `presets`
  (name -> `{tags, modes}`), `network_types`, `modes`,
  `max_overpass_area_km2`, `osm_formats`, `gpkg_edge_columns`,
  `edit_id_fields` (`osm_id`, `osmid`), `remove_field` (`remove`),
  `standalone` (true), `join_at` (`crossings`, `vertices`),
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
 "custom_edges": 3, "modified_edges": 0, "removed_edges": 0}   // check: "features", "modes", "edits"
{"event": "error", "type": "InvalidTagsError", "message": "...", "guide": "fixing-tag-errors",
 "issues": [{"feature": 17, "message": "maxspeed='fast' is not a valid OSM speed"}]}
```
- `guide` is an anchor in the engine's `docs/tagging-guide.md`, or
  `"<file>.md#anchor"` for another doc in its `docs/`. Link to the
  GitHub copy for the pinned version.
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

Standalone networks (since v0.10.0): a `warning` event names the
`features` outside the largest connected piece. Guide anchor:
`a-network-of-your-own-lines`.

The engine leaves a GeoPackage column out when no edge has a value:
`custom` is missing from the before network and from a build of changes
only, `modified` from a build with no changes. Check a field exists
before styling by it. `osmid` is the OSM way id (empty on custom edges).
`oneway` is a boolean in some outputs and the text `True`/`False` in
others (new lines and changes in one build), so read `car_direction`
instead.

The `done` event's `edges`, `custom_edges`, `modified_edges` and
`removed_edges` count a two-way OSM street once per direction, so they
don't match the GeoPackage's rows (one per street). The plugin counts
the rows of the output layer for its log (`count_edges` in `common.py`).

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
│   ├── metadata.txt            # name=NetworkForge, qgisMinimumVersion=3.34, experimental=True, GPL
│   ├── __init__.py             # classFactory(iface)
│   ├── plugin.py               # registers/unregisters the Processing provider
│   ├── provider.py
│   ├── engine.py               # install/version-check/run the engine CLI, parse events
│   ├── algorithms/
│   │   ├── common.py           # base class: export layer, run engine, select features
│   │   ├── build_network.py    # "Build scenario network"
│   │   ├── standalone_network.py # "Build standalone network" (no OSM)
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
   custom layer (lines; respect "selected only"), preset (enum from
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
4. No tool for creating a custom layer: the user decided against it
   (users make a line layer in QGIS themselves). Don't add one back.
5. Styles: after-edges coloured by `highway`, custom edges bold pink and
   changed edges bold orange on top; the standalone network is coloured
   by `highway` only (every edge is custom). Nodes hidden by default.

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
  no traffic simulation; turn restrictions come from OpenStreetMap only
  (kept in the PBF, users can't add their own); existing streets can be
  re-tagged or removed, not redrawn.
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
- Unit tests fake the CLI (a stub emitting canned JSON lines) - fast.
- One end-to-end test installs the pinned engine and builds from a small
  local extract (`--osm-source`), never Overpass. A tiny extract can be
  generated with the engine itself (`networkforge.write_osm`) or taken
  from Geofabrik (e.g. Monaco, <1 MB).

## Packaging
- `qgis-plugin-ci` builds the zip from `metadata.txt` and publishes to
  plugins.qgis.org on a version tag (needs an OSGeo account). Start as
  `experimental=True`.

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
