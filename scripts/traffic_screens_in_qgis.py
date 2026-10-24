"""Takes the traffic tutorial's screenshots (Bristol). Runs inside QGIS desktop.

Started by scripts/make_traffic_screenshots.py, which says what to do
through environment variables:

    NF_IMAGES   folder for the pictures
    NF_DATA     docs/tutorial-data/bristol-traffic.gpkg (the hospital)
    NF_WORK     folder holding bristol-latest.osm.pbf, where the .tar is written
    NF_ENGINE   folder of the installed engine (the tests' one)
"""

import os
import shutil
import time
import traceback
import urllib.request
from pathlib import Path

import processing
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFillSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QProcess, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import QApplication, QDockWidget, QLineEdit, QTextEdit
from qgis.utils import iface

IMAGES = Path(os.environ["NF_IMAGES"])
DATA = os.environ["NF_DATA"]
WORK = Path(os.environ["NF_WORK"])
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
AREA = (-2.74, 51.41, -2.44, 51.585)          # Bristol, round the hospital's 15 minutes
HOSPITAL = (-2.5914, 51.4969)
SECONDS = 900                                  # the panel takes isochrone intervals in seconds
LOG = []


def pump(seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)


def settle():
    """Wait until the map has finished drawing (the background comes over the internet)."""
    canvas = iface.mapCanvas()
    canvas.refresh()
    pump(1)
    end = time.time() + 90
    while canvas.isDrawing() and time.time() < end:
        pump(0.3)
    pump(1.5)


def shot(name, widget=None):
    iface.messageBar().clearWidgets()
    pump(0.3)
    path = IMAGES / f"tutorial-traffic-qgis-{name}.webp"
    (widget or iface.mainWindow()).grab().save(str(path), "WEBP", 85)
    LOG.append(f"wrote {path}")


def dock(name=None, title=None):
    for widget in iface.mainWindow().findChildren(QDockWidget):
        if (name and widget.objectName() == name) or (
                title and widget.windowTitle().startswith(title)):
            return widget
    return None


def zoom(west, south, east, north):
    project = QgsProject.instance()
    transform = QgsCoordinateTransform(WGS84, project.crs(), project)
    iface.mapCanvas().setExtent(transform.transformBoundingBox(
        QgsRectangle(west, south, east, north)))
    settle()


def label(layer, field, size=11):
    text = QgsTextFormat()
    font = QFont("DejaVu Sans")
    font.setBold(True)
    text.setFont(font)
    text.setSize(size)
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.2)
    buffer.setColor(QColor("#ffffff"))
    text.setBuffer(buffer)
    settings = QgsPalLayerSettings()
    settings.fieldName = field
    settings.setFormat(text)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def show(layer, visible):
    QgsProject.instance().layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(visible)


def wait_for(condition, seconds, what):
    end = time.time() + seconds
    while not condition():
        if time.time() > end:
            raise RuntimeError(f"timed out waiting for {what}")
        pump(0.5)


def server_up():
    try:
        urllib.request.urlopen("http://localhost:8002/status", timeout=1)
        return True
    except OSError:
        return False


def set_up():
    """A tidy window, the background map and the hospital."""
    window = iface.mainWindow()
    window.resize(1500, 940)
    for name in ("Browser", "Browser2"):
        if dock(name):
            dock(name).hide()
    analyst = dock(title="Network Analyst")
    if analyst:
        analyst.hide()
    layers_dock = dock("Layers")
    layers_dock.show()
    window.resizeDocks([layers_dock], [290], Qt.Orientation.Horizontal)

    project = QgsProject.instance()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    background = QgsRasterLayer(
        "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0",
        "OpenStreetMap", "wms")
    project.addMapLayer(background)
    background.setOpacity(0.75)
    hospital = QgsVectorLayer(f"{DATA}|layername=hospital", "hospital", "ogr")
    assert hospital.isValid(), DATA
    project.addMapLayer(hospital)
    hospital.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
        "name": "circle", "color": "#ffffff", "outline_color": "#1f2933",
        "outline_width": "0.6", "size": "3.6"})))
    label(hospital, "name", 11)
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    zoom(*AREA)
    return hospital


def toolbox_shot():
    toolbox = dock("ProcessingToolbox")
    toolbox.show()
    toolbox.raise_()
    search = toolbox.findChild(QLineEdit)
    if search is not None:
        search.setText("NetworkForge")
    pump(1.5)
    zoom(*AREA)
    shot("01-toolbox")
    if search is not None:
        search.setText("")
    toolbox.hide()
    pump(0.5)


def add_traffic_from_the_form():
    """The form filled in for the extract (example bands left as they are), run from the form."""
    parameters = {"NETWORK_FILE": str(WORK / "bristol-latest.osm.pbf"),
                  "OUTPUT": str(WORK / "bristol-traffic.tar")}
    dialog = processing.createAlgorithmDialog("networkforge:add_traffic", parameters)
    dialog.resize(1000, 860)
    dialog.show()
    pump(2)
    shot("02-add-traffic-form", dialog)
    dialog.runAlgorithm()
    end = time.time() + 900

    def log_text():
        return "\n".join(box.toPlainText() for box in dialog.findChildren(QTextEdit)
                         if "Execution" in box.toPlainText()
                         or "NetworkForge" in box.toPlainText()[:200])
    while time.time() < end:
        pump(1)
        text = log_text()
        if "Execution failed" in text:
            raise RuntimeError("the tool failed: " + text[-800:])
        if "Execution completed" in text:
            break
    else:
        raise RuntimeError("the tool didn't finish in 15 minutes")
    pump(2)
    LOG.append("log ends: " + log_text()[-600:])
    shot("03-add-traffic-log", dialog)
    dialog.close()


def from_tar(name, tar):
    """What the Network Analyst plugin's Graphs > + > From Tar does with the file it is given.

    It names the graph after the file, as the plugin does.
    """
    from valhalla.core import graph_registry

    if graph_registry.entry_exists(name):
        graph_registry.unregister(name)
    entry = graph_registry.graph_dir().joinpath(name)
    entry.mkdir(parents=True, exist_ok=True)
    dest = entry.joinpath(Path(tar).name)
    shutil.copy(tar, dest)          # the plugin moves it; a copy keeps ours
    graph_registry.register(name, graph_registry.local_graph_config(
        tile_extract=str(dest.resolve())), replace=True)


def session():
    from qgis.utils import plugins
    from valhalla.core.settings import ValhallaSettings
    from valhalla.global_definitions import RouterProfile
    from valhalla.gui.widgets.widget_router import PROFILE_TO_UI
    from valhalla.utils.resource_utils import get_default_valhalla_binary_dir

    set_up()
    toolbox_shot()
    add_traffic_from_the_form()
    project = QgsProject.instance()
    for layer in project.mapLayersByName("Valhalla graph with traffic"):
        project.removeMapLayer(layer.id())

    # The tar into the Network Analyst plugin's library, as From Tar does.
    ValhallaSettings().set_binary_dir(get_default_valhalla_binary_dir())
    panel = plugins["valhalla"].routing_dock
    router = panel.router_widget
    from_tar("bristol-traffic", WORK / "bristol-traffic.tar")
    settings = router.settings_dlg
    settings.setupDepsTable()
    settings.resize(1000, 760)
    settings.show()
    pump(2)
    if hasattr(settings.graph_widget, "refresh"):
        settings.graph_widget.refresh()
    pump(2)
    shot("04-analyst-graphs", settings)
    settings.close()

    # The panel: local server, car, the isochrone page, the hospital, 900 s,
    # and a departure time in Extra JSON (Time settings crashes in 6.0.1 / 7.0.1).
    panel.show()
    router.ui_cmb_prov.setCurrentIndex(router.ui_cmb_prov.findText("localhost"))
    for ui_enum, profile in PROFILE_TO_UI.items():
        if profile == RouterProfile.CAR:
            getattr(router, ui_enum.value).click()
    panel.menu_widget.setCurrentRow(2)                   # Isochrones
    panel.ui_isochrone_intervals.setText(str(SECONDS))
    to_map = QgsCoordinateTransform(WGS84, iface.mapCanvas().mapSettings().destinationCrs(),
                                    project)
    panel.waypoints_widget._handle_add_pt(to_map.transform(QgsPointXY(*HOSPITAL)))
    options = panel.routing_params_widget
    panel.options_box.setChecked(True)
    if hasattr(panel.options_box, "setCollapsed"):
        panel.options_box.setCollapsed(False)
    options.ui_time_box.setChecked(False)
    options.ui_extra_box.setChecked(True)
    if hasattr(options.ui_extra_box, "setCollapsed"):
        options.ui_extra_box.setCollapsed(False)

    router._refresh_graph_combo()
    router.ui_cmb_graphs.setCurrentText("bristol-traffic")
    router.ui_btn_server_start.click()
    wait_for(server_up, 120, "the local server")

    def isochrone(hour):
        options.ui_extra_json.setPlainText(
            '{"date_time": {"type": 1, "value": "2026-10-19T%02d:00"}}' % hour)
        known = set(project.mapLayers())
        panel.execute_btn.click()
        wait_for(lambda: set(project.mapLayers()) - known, 120, "the isochrone")
        (layer_id,) = set(project.mapLayers()) - known
        layer = project.mapLayer(layer_id)
        LOG.append(f"{hour:02d}:00: {layer.name()}, {layer.featureCount()} feature(s), "
                   f"fields {layer.fields().names()}")
        return layer

    night = isochrone(3)
    zoom(*AREA)
    shot("05-isochrone-3am")
    show(night, False)
    peak = isochrone(8)
    zoom(*AREA)
    shot("06-isochrone-8am")

    # Both together, renamed and coloured, as a reader can do in the Layers panel.
    for layer, name, colour in ((night, "15 minutes at 3 am", "31,119,180"),
                                (peak, "15 minutes at 8 am", "214,39,40")):
        layer.setName(name)
        layer.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
            "color": f"{colour},90", "outline_color": f"{colour},255",
            "outline_width": "0.7"})))
        layer.triggerRepaint()
        show(layer, True)
    for layer in project.mapLayersByName("Valhalla Waypoints"):
        show(layer, False)
    iface.mapCanvas().refreshAllLayers()
    zoom(*AREA)
    shot("07-isochrones-compared")
    router.ui_btn_server_start.click()
    wait_for(lambda: router.valhalla_service.state() == QProcess.ProcessState.NotRunning,
             60, "the server to stop")


def main():
    try:
        from networkforge_qgis import engine
        engine.base_dir = lambda: Path(os.environ["NF_ENGINE"])
        session()
    except Exception:  # noqa: BLE001 - reported in the log file
        LOG.append(traceback.format_exc())
    (IMAGES / "tutorial-traffic-qgis.log").write_text("\n".join(LOG))
    QgsProject.instance().setDirty(False)
    QTimer.singleShot(3000, lambda: os._exit(0))
    iface.actionExit().trigger()


QTimer.singleShot(6000, main)
