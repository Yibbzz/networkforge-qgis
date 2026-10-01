""""Engine information": installs the engine if needed and shows what it supports.

Runs `networkforge info --json`. On first use this is also what sets the
engine up, so it doubles as a check that the installation works.
"""

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
)

from .. import engine


class EngineInfoAlgorithm(QgsProcessingAlgorithm):
    REINSTALL = "REINSTALL"
    ENGINE_VERSION = "ENGINE_VERSION"
    ENGINE_PATH = "ENGINE_PATH"

    def name(self):
        return "engine_info"

    def displayName(self):
        return "Engine information"

    def shortHelpString(self):
        return (
            "Shows which version of the NetworkForge engine is installed "
            "and what it supports. The engine does all the network work; "
            "this plugin runs it as a separate program.\n\n"
            "If the engine is not installed yet, this installs it into its "
            "own folder inside your QGIS profile. That happens once, needs "
            "an internet connection and can take a few minutes.\n\n"
            "Tick \"Reinstall the engine\" to replace an installation that "
            "has stopped working.\n\n"
            "Map data © OpenStreetMap contributors (ODbL)."
        )

    def createInstance(self):
        return EngineInfoAlgorithm()

    def initAlgorithm(self, config=None):
        # QGIS runs a tool with no parameters straight away, without its
        # window, so the log below would never be seen.
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.REINSTALL, "Reinstall the engine", defaultValue=False
            )
        )
        self.addOutput(
            QgsProcessingOutputString(self.ENGINE_VERSION, "Engine version")
        )
        self.addOutput(
            QgsProcessingOutputString(self.ENGINE_PATH, "Engine program")
        )

    def processAlgorithm(self, parameters, context, feedback):
        try:
            if self.parameterAsBoolean(parameters, self.REINSTALL, context):
                feedback.pushInfo("Reinstalling the NetworkForge engine...")
                engine.install(feedback)
            else:
                engine.ensure_installed(feedback)
            info = engine.info()
        except engine.EngineCanceled:
            return {}
        except engine.EngineError as err:
            raise QgsProcessingException(str(err))

        feedback.pushInfo(f"NetworkForge engine version: {info['version']}")
        feedback.pushInfo(f"Installed at: {engine.venv_dir()}")
        feedback.pushInfo(f"Log file: {engine.log_path()}")
        feedback.pushInfo("Presets: " + ", ".join(info["presets"]))
        feedback.pushInfo("Network types: " + ", ".join(info["network_types"]))
        feedback.pushInfo("Travel modes: " + ", ".join(info["modes"]))
        feedback.pushInfo(
            "Largest area downloadable from OpenStreetMap: "
            f"{info['max_overpass_area_km2']:,} km2 (use a local OSM file "
            "for anything bigger)"
        )
        return {
            self.ENGINE_VERSION: info["version"],
            self.ENGINE_PATH: str(engine.engine_exe()),
        }
