"""What QGIS reads to decide whether it may install and load the plugin."""

import configparser
from pathlib import Path

METADATA = Path(__file__).parent.parent / "networkforge_qgis" / "metadata.txt"


def test_plugin_declares_support_for_qgis_3_and_4():
    # With no maximum, QGIS assumes "3.99" and QGIS 4 hides the plugin.
    parser = configparser.ConfigParser()
    parser.read(METADATA, encoding="utf-8")
    general = parser["general"]
    assert general["qgisMinimumVersion"] == "3.34"
    assert general["qgisMaximumVersion"] == "4.99"
    assert general["supportsQt6"] == "True"
