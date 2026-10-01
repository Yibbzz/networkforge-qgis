# Changelog

## Unreleased

- Plugin skeleton: the plugin loads and a "NetworkForge" group appears in
  the Processing Toolbox with one tool, "Engine information".
- Engine manager: "Engine information" installs NetworkForge engine
  v0.4.0 into its own environment inside the QGIS profile on first use,
  then reports what the engine supports (`networkforge info --json`).
- "Engine information" opens its window (so its log is visible) and can
  reinstall the engine. Fixed the engine install failing on Windows.
- "Build scenario network": builds the before and after networks for an
  area from a layer of custom lines, with progress and cancel, and loads
  both as styled layers. PBF files are written alongside.
- Uses NetworkForge engine v0.5.0: custom lines that don't connect to
  the network now give a warning instead of stopping the build. An
  installed v0.4.0 engine is replaced the next time a tool runs.
- Tests for the engine runner and the tools, using a stand-in engine.
- Warnings and errors that name features now select those features in
  the custom layer, so they are easy to find and fix.
- "Check custom network layer": validates the lines and their attributes
  without downloading anything.
- "New custom network layer": an empty layer with the engine's
  attributes, drop-down lists and checks.
- Before and after layers are coloured by kind of street.
- End-to-end tests against the real engine, and GitHub CI on QGIS LTR
  and latest.
