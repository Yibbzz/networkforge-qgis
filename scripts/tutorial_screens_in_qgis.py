"""Takes the tutorial's screenshots. Runs inside QGIS desktop.

Started by scripts/make_tutorial_screenshots.py, which says what to do
through environment variables:

    NF_IMAGES   folder for the pictures
    NF_DATA     docs/tutorial-data/reading-bridge.gpkg
    NF_WORK     folder for the networks that are built
    NF_ENGINE   folder of the installed engine (the tests' one)
    NF_SESSION  "before": the steps up to the first route, with Valhalla
                serving the before network;
                "after": the route on the after network, and stage 2.
"""

import os
import time
import traceback
import urllib.request
from pathlib import Path

import processing
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsFillSymbol,
    QgsGeometry,
    QgsLineSymbol,
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
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QLineEdit,
    QTableView,
    QTextEdit,
)
from qgis.utils import iface

IMAGES = Path(os.environ["NF_IMAGES"])
DATA = os.environ["NF_DATA"]
WORK = Path(os.environ["NF_WORK"])
SESSION = os.environ["NF_SESSION"]
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
AREA = (-0.990, 51.440, -0.895, 51.495)
# As the form writes it when "Calculate from layer" picks the study area.
# (Given the layer itself, a form made from Python labels its longitudes
# and latitudes with the project's CRS.)
EXTENT = f"{AREA[0]},{AREA[2]},{AREA[1]},{AREA[3]} [EPSG:4326]"
PARK_ENTRANCE = (-0.9365, 51.4595, -0.9265, 51.4640)
HOME, WORKPLACE = (-0.9480, 51.4800), (-0.9280, 51.4627)
SONNING_EYE, EARLEY = (-0.9190, 51.4790), (-0.9300, 51.4440)
SONNING_BRIDGE = (-0.9205, 51.4735, -0.9125, 51.4790)
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
    path = IMAGES / f"tutorial-qgis-{name}.webp"
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


def data_layer(name, title):
    layer = QgsVectorLayer(f"{DATA}|layername={name}", title, "ogr")
    assert layer.isValid(), name
    QgsProject.instance().addMapLayer(layer)
    return layer


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


def set_up():
    """A tidy window, the background map and the tutorial's layers."""
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

    area = data_layer("study_area", "Study area")
    area.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
        "style": "no", "outline_color": "#1f2933", "outline_width": "0.5",
        "outline_style": "dash"})))
    bridge = data_layer("1_bridge", "Proposed bridge")
    bridge.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
        "color": "#e6007e", "width": "1.2", "capstyle": "round"})))
    # Home and work only. A copy, not a filter on the layer: in QGIS 3.34 a
    # filtered GeoPackage layer made the file's other layers load without a CRS.
    every_trip = QgsVectorLayer(f"{DATA}|layername=trips", "all trips", "ogr")
    trips = every_trip.materialize(QgsFeatureRequest().setFilterExpression(
        "\"label\" IN ('A', 'B')"))
    trips.setName("Trips")
    project.addMapLayer(trips)
    trips.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
        "name": "circle", "color": "#ffffff", "outline_color": "#1f2933",
        "outline_width": "0.6", "size": "3.6"})))
    label(trips, "label", 13)
    # QGIS takes the first layer's CRS for the project: set it again.
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    zoom(*AREA)
    return area, bridge, trips


def networkforge(tool, **parameters):
    return processing.runAndLoadResults(f"networkforge:{tool}", parameters)


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


def network_layer(stage, which, title):
    from networkforge_qgis import styling
    layer = QgsVectorLayer(f"{WORK / stage / which}.gpkg|layername=edges", title, "ogr")
    assert layer.isValid(), layer.source()
    QgsProject.instance().addMapLayer(layer)
    (styling.style_after if which == "after" else styling.style_before)(layer)
    return layer


def session_analyst():
    """Routing with the Network Analyst plugin's own panel, as a reader does it."""
    from qgis.utils import plugins
    from valhalla.core import graph_registry
    from valhalla.core.settings import ValhallaSettings
    from valhalla.global_definitions import RouterProfile
    from valhalla.gui.widgets.widget_router import PROFILE_TO_UI
    from valhalla.utils.resource_utils import get_default_valhalla_binary_dir

    area, bridge, trips = set_up()
    show(bridge, False)
    project = QgsProject.instance()
    before = network_layer("stage-1", "before", "Before network")

    # pyvalhalla is where the plugin's own "Install" puts it.
    ValhallaSettings().set_binary_dir(get_default_valhalla_binary_dir())
    panel = plugins["valhalla"].routing_dock
    router = panel.router_widget
    settings = router.settings_dlg
    settings.setupDepsTable()
    settings.resize(1000, 760)
    settings.show()
    pump(2)
    shot("07-analyst-settings", settings)

    # A graph from each PBF, with "Graphs > + > From PBF".
    builder = settings.graph_widget.local_ctl
    for name, pbf in (("reading-before", "before"), ("reading-after", "after")):
        form = builder.from_pbf_dlg
        form.ui_pbf_file.setFilePath(str(WORK / "stage-1" / f"{pbf}.osm.pbf"))
        form.ui_text_name.setText(name)
        form.open()
        form.resize(820, form.height())
        pump(1)
        if pbf == "before":
            shot("08-analyst-graph-from-pbf", form)
        form.accept()
        wait_for(lambda: graph_registry.entry_exists(name), 600, f"the graph {name}")
        pump(2)
    settings.graph_widget.refresh() if hasattr(settings.graph_widget, "refresh") else None
    pump(2)
    shot("09-analyst-graphs", settings)
    settings.close()

    # The panel: local server, car, A and B, Execute.
    panel.show()
    router.ui_cmb_prov.setCurrentIndex(router.ui_cmb_prov.findText("localhost"))
    for ui_enum, profile in PROFILE_TO_UI.items():
        if profile == RouterProfile.CAR:
            getattr(router, ui_enum.value).click()
    to_map = QgsCoordinateTransform(WGS84, iface.mapCanvas().mapSettings().destinationCrs(),
                                    project)
    for point in (HOME, WORKPLACE):
        panel.waypoints_widget._handle_add_pt(to_map.transform(QgsPointXY(*point)))

    def route_on(graph, title):
        router._refresh_graph_combo()
        router.ui_cmb_graphs.setCurrentText(graph)
        router.ui_btn_server_start.click()
        wait_for(server_up, 120, "the local server")
        known = set(project.mapLayers())
        panel.execute_btn.click()
        wait_for(lambda: set(project.mapLayers()) - known, 60, "the route")
        (layer_id,) = set(project.mapLayers()) - known
        route = project.mapLayer(layer_id)
        feature = next(route.getFeatures())
        LOG.append(f"{title}: {graph}, fields {feature.fields().names()}, "
                   f"{dict(zip(feature.fields().names(), feature.attributes()))}")
        return route

    first = route_on("reading-before", "route before")
    zoom(*AREA)
    shot("10-analyst-route-before")

    router.ui_btn_server_start.click()                  # stop it
    wait_for(lambda: router.valhalla_service.state() == QProcess.ProcessState.NotRunning
             and not server_up(), 60, "the server to stop")
    show(first, False)
    show(before, False)
    network_layer("stage-1", "after", "After network")
    route_on("reading-after", "route after")
    zoom(*AREA)
    shot("11-analyst-route-after")
    router.ui_btn_server_start.click()


def show(layer, visible):
    QgsProject.instance().layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(visible)


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
    zoom(*AREA)


def session_before():
    area, bridge, trips = set_up()
    toolbox_shot()

    shot("02-bridge-line")
    table = iface.showAttributeTable(bridge)
    table.setFixedSize(1080, 230)
    pump(1.5)
    view = table.findChild(QTableView)
    if view is not None:
        view.resizeColumnsToContents()
    pump(0.5)
    shot("03-attribute-table", table)
    table.close()

    folder = str(WORK / "stage-1")
    parameters = {"EXTENT": EXTENT, "CUSTOM": bridge, "OUTPUT_FOLDER": folder}
    dialog = processing.createAlgorithmDialog("networkforge:build_network", parameters)
    dialog.resize(1000, 820)
    dialog.show()
    pump(2)
    shot("04-build-form", dialog)

    # Run it from the form, as a reader does, and wait for the layers.
    project = QgsProject.instance()
    dialog.runAlgorithm()
    end = time.time() + 900
    while not project.mapLayersByName("After network") and time.time() < end:
        pump(1)
        if "Execution failed" in dialog.findChild(QTextEdit).toPlainText():
            raise RuntimeError("the build failed: " + dialog.findChild(QTextEdit).toPlainText()[-600:])
    pump(3)
    LOG.append(f"build finished: {bool(project.mapLayersByName('After network'))}")
    shot("05-build-log", dialog)
    dialog.close()

    show(bridge, False)                  # the After layer shows it now
    zoom(*AREA)
    shot("06-before-and-after-layers")


def session_after():
    area, bridge, trips = set_up()
    show(bridge, False)
    project = QgsProject.instance()
    root = project.layerTreeRoot()

    # Stage 2: the park's road and its two barriers.
    show(trips, False)
    lines = data_layer("2_bridge_and_park_road", "Bridge and park road")
    lines.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
        "color": "#e6007e", "width": "1.1", "capstyle": "round"})))
    points = data_layer("2_barriers_removed", "Barriers to remove")
    points.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
        "name": "square", "color": "#e6007e", "outline_color": "#ffffff",
        "outline_width": "0.5", "size": "3.4"})))
    zoom(*PARK_ENTRANCE)
    shot("12-stage2-what-you-give-the-tool")

    networkforge("build_network", EXTENT=EXTENT, CUSTOM=lines, POINTS=points,
                 OUTPUT_FOLDER=str(WORK / "stage-2"))
    pump(3)
    for layer in (lines, points):
        root.findLayer(layer.id()).setItemVisibilityChecked(False)
    for layer in project.mapLayersByName("Before network"):
        root.findLayer(layer.id()).setItemVisibilityChecked(False)
    zoom(*PARK_ENTRANCE)
    shot("13-stage2-after-layer")



def session_stage3():
    """Stage 3: a bollard on Sonning Bridge, built, then routed on with the
    Network Analyst plugin's panel (a bollard is in the PBF only, so the
    route is where it shows)."""
    from qgis.utils import plugins
    from valhalla.core import graph_registry
    from valhalla.core.settings import ValhallaSettings
    from valhalla.global_definitions import RouterProfile
    from valhalla.gui.widgets.widget_router import PROFILE_TO_UI
    from valhalla.utils.resource_utils import get_default_valhalla_binary_dir

    area, bridge, trips = set_up()
    show(bridge, False)
    show(trips, False)
    project = QgsProject.instance()
    root = project.layerTreeRoot()

    lines = data_layer("2_bridge_and_park_road", "Bridge and park road")
    lines.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
        "color": "#e6007e", "width": "1.1", "capstyle": "round"})))
    points = data_layer("3_barriers_removed_and_bollard", "Barriers out, bollard in")
    points.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
        "name": "square", "color": "#e6007e", "outline_color": "#ffffff",
        "outline_width": "0.5", "size": "3.4"})))
    label(points, "barrier", 11)
    zoom(*SONNING_BRIDGE)
    shot("14-stage3-what-you-give-the-tool")

    networkforge("build_network", EXTENT=EXTENT, CUSTOM=lines, POINTS=points,
                 OUTPUT_FOLDER=str(WORK / "stage-3"))
    pump(3)
    for layer in project.mapLayersByName("Before network"):
        project.removeMapLayer(layer.id())
    show(lines, False)
    stage3_after = project.mapLayersByName("After network")[0]
    stage3_after.setName("After network (stage 3)")

    # Graphs of the stage 2 and stage 3 networks, with the plugin's "From PBF".
    ValhallaSettings().set_binary_dir(get_default_valhalla_binary_dir())
    panel = plugins["valhalla"].routing_dock
    router = panel.router_widget
    builder = router.settings_dlg.graph_widget.local_ctl
    for name, stage in (("reading-stage-2", "stage-2"), ("reading-stage-3", "stage-3")):
        form = builder.from_pbf_dlg
        form.ui_pbf_file.setFilePath(str(WORK / stage / "after.osm.pbf"))
        form.ui_text_name.setText(name)
        form.open()
        pump(1)
        form.accept()
        wait_for(lambda: graph_registry.entry_exists(name), 600, f"the graph {name}")
        pump(2)

    stops = QgsVectorLayer(f"{DATA}|layername=trips", "all trips", "ogr").materialize(
        QgsFeatureRequest().setFilterExpression("\"label\" IN ('C', 'D')"))
    stops.setName("Trips")
    stops.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
        "name": "circle", "color": "#ffffff", "outline_color": "#1f2933",
        "outline_width": "0.6", "size": "3.6"})))
    label(stops, "label", 13)
    project.addMapLayer(stops)

    panel.show()
    router.ui_cmb_prov.setCurrentIndex(router.ui_cmb_prov.findText("localhost"))
    for ui_enum, profile in PROFILE_TO_UI.items():
        if profile == RouterProfile.CAR:
            getattr(router, ui_enum.value).click()
    to_map = QgsCoordinateTransform(WGS84, iface.mapCanvas().mapSettings().destinationCrs(),
                                    project)
    for point in (SONNING_EYE, EARLEY):
        panel.waypoints_widget._handle_add_pt(to_map.transform(QgsPointXY(*point)))

    def route_on(graph, title):
        router._refresh_graph_combo()
        router.ui_cmb_graphs.setCurrentText(graph)
        router.ui_btn_server_start.click()
        wait_for(server_up, 120, "the local server")
        known = set(project.mapLayers())
        panel.execute_btn.click()
        wait_for(lambda: set(project.mapLayers()) - known, 60, "the route")
        (layer_id,) = set(project.mapLayers()) - known
        route = project.mapLayer(layer_id)
        feature = next(route.getFeatures())
        LOG.append(f"{title}: {graph}, {feature['distance']:.0f} m, {feature['duration']:.0f} s")
        return route

    stage2_after = network_layer("stage-2", "after", "After network (stage 2)")
    show(stage3_after, False)
    show(points, False)
    first = route_on("reading-stage-2", "D to C, stage 2")
    zoom(*AREA)
    shot("15-stage3-route-before-the-bollard")

    router.ui_btn_server_start.click()
    wait_for(lambda: router.valhalla_service.state() == QProcess.ProcessState.NotRunning
             and not server_up(), 60, "the server to stop")
    show(first, False)
    show(stage2_after, False)
    show(stage3_after, True)
    show(points, True)
    route_on("reading-stage-3", "D to C, stage 3")
    zoom(*AREA)
    shot("16-stage3-route-with-the-bollard")
    router.ui_btn_server_start.click()


def main():
    try:
        from networkforge_qgis import engine
        engine.base_dir = lambda: Path(os.environ["NF_ENGINE"])
        LOG.append(f"providers: {[p.id() for p in QgsApplication.processingRegistry().providers()]}")
        {"before": session_before, "analyst": session_analyst,
         "after": session_after, "stage3": session_stage3}[SESSION]()
    except Exception:  # noqa: BLE001 - reported in the log file
        LOG.append(traceback.format_exc())
    (IMAGES / f"tutorial-qgis-{SESSION}.log").write_text("\n".join(LOG))
    QgsProject.instance().setDirty(False)
    QTimer.singleShot(3000, lambda: os._exit(0))
    iface.actionExit().trigger()


QTimer.singleShot(6000, main)
