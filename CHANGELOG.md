# Changelog

## Unreleased

- Plugin skeleton: the plugin loads and a "NetworkForge" group appears in
  the Processing Toolbox with one tool, "Engine information".
- Engine manager: "Engine information" installs NetworkForge engine
  v0.4.0 into its own environment inside the QGIS profile on first use,
  then reports what the engine supports (`networkforge info --json`).
