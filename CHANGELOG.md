# Changelog

## Unreleased

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
