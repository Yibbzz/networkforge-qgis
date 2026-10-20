"""Takes the public transport tutorial's screenshots. Runs inside QGIS desktop.

Started by scripts/make_transit_screenshots.py, which says what to do
through environment variables:

    NF_IMAGES   folder for the pictures
    NF_DATA     docs/tutorial-data/cincinnati-transit.gpkg
    NF_WORK     folder with the feeds (gtfs/) and the built networks
                (network/), where QGIS writes its results
    NF_ENGINE   folder of the installed engine (the tests' one)
    NF_R5       folder with Easy-R5's Java and R5 (the tests' one)
"""

import os
import time
import traceback
from pathlib import Path

import processing
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import QApplication, QDockWidget, QLineEdit, QTableView, QTextEdit
from qgis.utils import iface

IMAGES = Path(os.environ["NF_IMAGES"])
DATA = os.environ["NF_DATA"]
WORK = Path(os.environ["NF_WORK"])
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
AREA = (-84.585, 39.055, -84.415, 39.200)
EXTENT = f"{AREA[0]},{AREA[2]},{AREA[1]},{AREA[3]} [EPSG:4326]"
DOWNTOWN_VIEW = (-84.590, 39.050, -84.410, 39.200)
SERVICE_AREA_VIEW = (-84.585, 39.055, -84.415, 39.150)
TRAM_VIEW = (-84.540, 39.095, -84.485, 39.142)
KLOTTER_VIEW = (-84.580, 39.085, -84.460, 39.150)
BRIGHTON = (-84.5345, 39.1205, -84.5265, 39.1248)
DATE, PEAK, OFF_PEAK = "2026-10-20", "17:15", "14:00"
PINK, BLUE, ORANGE = "#e6007e", "#2f6fdb", "#f28e2b"
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
    path = IMAGES / f"transit-qgis-{name}.webp"
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


def add(layer):
    assert layer.isValid(), layer.source()
    QgsProject.instance().addMapLayer(layer)
    return layer


def data_layer(name, title):
    return add(QgsVectorLayer(f"{DATA}|layername={name}", title, "ogr"))


def show(layer, visible):
    QgsProject.instance().layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(visible)


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
    settings.yOffset = -4
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def marker(layer, colour):
    layer.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
        "name": "circle", "color": colour, "outline_color": "#ffffff",
        "outline_width": "0.6", "size": "4"})))
    label(layer, "name", 12)


def area_style(layer, colour, opacity=0.4):
    fill = QColor(colour)
    fill.setAlphaF(opacity)
    symbol = QgsFillSymbol.createSimple({"outline_color": colour, "outline_width": "0.7"})
    symbol.setColor(fill)
    symbol.symbolLayer(0).setStrokeColor(QColor(colour))
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.triggerRepaint()


def km2(layer):
    measure = QgsDistanceArea()
    measure.setEllipsoid("WGS84")
    measure.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
    return sum(measure.measureArea(f.geometry()) for f in layer.getFeatures()) / 1e6


def set_up():
    """A tidy window, the background map and the tutorial's layers."""
    window = iface.mainWindow()
    window.resize(1500, 940)
    for name in ("Browser", "Browser2"):
        if dock(name):
            dock(name).hide()
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

    area = data_layer("study_area", "study_area")
    area.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
        "style": "no", "outline_color": "#1f2933", "outline_width": "0.5",
        "outline_style": "dash"})))
    steps = data_layer("steps_reopened", "steps_reopened")
    steps.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
        "color": PINK, "width": "1.6", "capstyle": "round"})))
    downtown = data_layer("fountain_square", "fountain_square")
    marker(downtown, "#1f2933")
    klotter = data_layer("klotter_avenue", "klotter_avenue")
    marker(klotter, PINK)
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    zoom(*DOWNTOWN_VIEW)
    return area, steps, downtown, klotter


def form(algorithm, parameters, height=820):
    dialog = processing.createAlgorithmDialog(algorithm, parameters)
    dialog.resize(1000, height)
    dialog.show()
    pump(2)
    return dialog


def show_advanced(dialog, label):
    """Open a form's Advanced Parameters and scroll down to the setting called `label`."""
    from qgis.PyQt.QtWidgets import QLabel, QScrollArea
    from qgis.PyQt.QtWidgets import QGroupBox, QToolButton
    # The Advanced Parameters box: click its arrow, as a reader does.
    for box in dialog.findChildren(QGroupBox, "grpAdvanced"):
        arrows = box.findChildren(QToolButton)
        LOG.append(f"advanced: {len(arrows)} arrow button(s)")
        if arrows:
            arrows[0].click()
    pump(1.5)
    labels = [w for w in dialog.findChildren(QLabel) if w.text().startswith(label)]
    target = next((w for w in labels if w.isVisible()), labels[0] if labels else None)
    area = target.parent() if target is not None else None
    while area is not None and not isinstance(area, QScrollArea):
        area = area.parent()
    if area is not None:
        bar = area.verticalScrollBar()
        top = target.mapTo(area.widget(), target.rect().topLeft()).y()
        bar.setValue(min(bar.maximum(), max(0, top - area.viewport().height() + 160)))
        LOG.append(f"advanced: scrolled to {bar.value()} of {bar.maximum()} (label at {top})")
    else:
        LOG.append(f"advanced: {len(labels)} labels, no scroll area round them")
    pump(1)


def run_form(dialog, seconds, what):
    """Run a form as a reader does, and wait for it to finish."""
    finished = []
    dialog.algorithmFinished.connect(lambda ok, results: finished.append(ok))
    dialog.runAlgorithm()
    log = dialog.findChild(QTextEdit, "txtLog") or dialog.findChildren(QTextEdit)[-1]
    end = time.time() + seconds
    while not finished:
        if time.time() > end:
            raise RuntimeError(f"timed out waiting for {what}")
        pump(1)
    pump(3)
    if not finished[0]:
        raise RuntimeError(f"{what} failed: " + log.toPlainText()[-800:])
    return log.toPlainText()


def toolbox_shot():
    toolbox = dock("ProcessingToolbox")
    toolbox.show()
    toolbox.raise_()
    search = toolbox.findChild(QLineEdit)
    if search is not None:
        search.setText("R5")
    pump(1.5)
    zoom(*DOWNTOWN_VIEW)
    shot("01-toolbox")
    if search is not None:
        search.setText("")
    toolbox.hide()
    pump(0.5)


def isochrones(network, origin, departure, name, title, colour, picture=None, scenario=None,
               window=1):
    """Easy-R5's 30-minute service area, run from its form; the layer it loads."""
    path = WORK / f"service-area-{name}.gpkg"
    path.unlink(missing_ok=True)
    project = QgsProject.instance()
    known = set(project.mapLayers())
    dialog = form("easyr5:generateisochrones", {
        "NETWORK": network, "ORIGINS": origin, "ORIGIN_ID_FIELD": "name",
        "DATE": DATE, "DEPARTURE_TIME": departure, "TIME_WINDOW": window,
        "MAX_TRIP_DURATION": 30, "MODE": 0, "CUTOFFS": "30", "GRID_SPACING": 100,
        "OUTPUT_LAYER": str(path), "JAVA_HEAP_GB": 3,
        **({"SCENARIO": scenario} if scenario else {})}, height=900)
    if picture:
        if scenario:
            show_advanced(dialog, "Scenario file")
        shot(picture, dialog)
    run_form(dialog, 1800, f"the service area {name}")
    dialog.close()
    pump(2)
    # Easy-R5 loads the result with a style of its own: put it back
    # with the tutorial's colours.
    for layer_id in set(project.mapLayers()) - known:
        project.removeMapLayer(layer_id)
    layer = add(QgsVectorLayer(str(path), title, "ogr"))
    area_style(layer, colour)
    LOG.append(f"{title}: {km2(layer):.1f} km2")
    return layer


def session():
    from networkforge_qgis import styling

    area, steps, downtown, klotter = set_up()
    # Easy-R5 finds Java and R5 where "Download R5 engine and Java 21" put
    # them: the tests' copy (a second run on a folder only checks it).
    processing.run("easyr5:downloadr5", {"TARGET_FOLDER": os.environ["NF_R5"]})
    toolbox_shot()
    show(steps, False)
    zoom(*DOWNTOWN_VIEW)
    shot("02-the-area")

    # The feeds: Esri's "Examine the GTFS public transit data".
    metro = str(WORK / "gtfs" / "metro.zip")
    dialog = form("easyr5:checktransitdata", {
        "GTFS": metro, "WHOLE_FOLDER": True, "DATE": DATE, "EXTENT": EXTENT,
        "OUTPUT_REPORT": str(WORK / "gtfs-report.html")})
    shot("03-check-transit-data-form", dialog)
    text = run_form(dialog, 600, "the GTFS check")
    LOG.append("GTFS check log:\n" + text[-3000:])
    shot("04-check-transit-data-log", dialog)
    dialog.close()
    pump(1)
    for widget in iface.mainWindow().findChildren(QDockWidget):
        if widget.windowTitle().startswith("Results Viewer"):
            widget.hide()

    # The stairways: closed in OpenStreetMap, reopened as changes.
    before = add(QgsVectorLayer(
        f"{WORK / 'network' / 'before.gpkg'}|layername=edges", "Before network", "ogr"))
    styling.style_before(before)
    show(steps, True)
    show(downtown, False)
    zoom(*BRIGHTON)
    shot("05-closed-steps")
    table = iface.showAttributeTable(steps)
    table.setFixedSize(900, 170)
    pump(1.5)
    view = table.findChild(QTableView)
    if view is not None:
        view.resizeColumnsToContents()
    pump(0.5)
    shot("06-steps-attribute-table", table)
    table.close()

    dialog = form("networkforge:build_network", {
        "EXTENT": EXTENT, "CUSTOM": steps, "OUTPUT_FOLDER": str(WORK / "network")})
    shot("07-build-form", dialog)
    dialog.close()

    # The transit network: Esri's "GTFS To Public Transit Data Model",
    # "Connect Public Transit Data Model To Streets" and "Build Network".
    networks = {}
    for which in ("before", "after"):
        dialog = form("easyr5:buildnetwork", {
            "OSM_PBF": str(WORK / "network" / f"{which}.osm.pbf"),
            "GTFS_FOLDER": str(WORK / "gtfs")}, height=640)
        if which == "before":
            shot("08-build-r5-network-form", dialog)
        text = run_form(dialog, 1200, f"the R5 network ({which})")
        if which == "before":
            LOG.append("Build R5 network log:\n" + text[-2500:])
            shot("09-build-r5-network-log", dialog)
        networks[which] = dialog.results()["NETWORK_DAT"]
        dialog.close()
    LOG.append(f"R5 networks: {networks}")

    # Esri's service areas: 30 minutes from downtown at 5:15 pm and 2:00 pm.
    show(before, False)
    show(steps, False)
    show(klotter, False)
    show(downtown, True)
    zoom(*DOWNTOWN_VIEW)
    peak = isochrones(networks["before"], downtown, PEAK, "downtown-peak",
                      "30 minutes from Fountain Square, 5:15 pm", BLUE,
                      picture="10-isochrones-form")
    zoom(*SERVICE_AREA_VIEW)
    shot("11-service-area-peak")
    off_peak = isochrones(networks["before"], downtown, OFF_PEAK, "downtown-off-peak",
                          "30 minutes from Fountain Square, 2:00 pm", ORANGE)
    area_style(peak, BLUE, 0.15)
    zoom(*SERVICE_AREA_VIEW)
    shot("12-service-area-off-peak")

    # The stairways: 30 minutes from Klotter Avenue, closed and open.
    for layer in (peak, off_peak, downtown):
        show(layer, False)
    show(klotter, True)
    after_area = isochrones(networks["after"], klotter, PEAK, "klotter-after",
                            "30 minutes from Klotter Avenue, steps open", PINK)
    before_area = isochrones(networks["before"], klotter, PEAK, "klotter-before",
                             "30 minutes from Klotter Avenue, steps closed", BLUE)
    area_style(after_area, PINK, 0.35)
    area_style(before_area, BLUE, 0.45)
    show(steps, True)
    zoom(*KLOTTER_VIEW)
    shot("13-klotter-before-and-after")

    # Section 8: a new tram line up Vine Street, as an Easy-R5 scenario.
    for layer in (after_area, before_area, steps, klotter):
        show(layer, False)
    tram = data_layer("uptown_tram", "uptown_tram")
    tram.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
        "color": PINK, "width": "1.4", "capstyle": "round"})))
    stops = QgsMarkerSymbol.createSimple({
        "name": "circle", "color": "#ffffff", "outline_color": PINK,
        "outline_width": "0.7", "size": "2.6"})
    line = tram.renderer().symbol()
    from qgis.core import QgsMarkerLineSymbolLayer
    vertices = QgsMarkerLineSymbolLayer()
    vertices.setPlacements(Qgis.MarkerLinePlacement.Vertex)
    vertices.setSubSymbol(stops)
    line.appendSymbolLayer(vertices)
    tram.triggerRepaint()
    show(downtown, True)
    zoom(*TRAM_VIEW)
    shot("14-uptown-tram-line")

    dialog = form("easyr5:buildscenario", {
        "NEW_LINES": tram, "LINE_NAME_FIELD": "name", "NEW_LINE_MODE": 0,
        "SPEED_KMH": 18, "HEADWAY_MINUTES": 10, "SERVICE_START": "05:00",
        "SERVICE_END": "23:00", "OUTPUT_SCENARIO": str(WORK / "uptown-tram.json")}, height=900)
    shot("15-build-scenario-form", dialog)
    text = run_form(dialog, 300, "the scenario")
    LOG.append("Build scenario log:\n" + text[-1500:])
    scenario = dialog.results()["OUTPUT_SCENARIO"]
    dialog.close()

    # Over an hour, both: the tram has a frequency, not a timetable.
    show(off_peak, False)
    off_peak = isochrones(networks["before"], downtown, OFF_PEAK, "downtown-hour",
                          "30 minutes from Fountain Square, 2-3 pm, today", ORANGE,
                          window=60)
    with_tram = isochrones(networks["before"], downtown, OFF_PEAK, "downtown-tram",
                           "30 minutes from Fountain Square, 2-3 pm, with the tram", PINK,
                           scenario=scenario, window=60, picture="16-isochrones-scenario-form")
    show(off_peak, True)
    area_style(with_tram, PINK, 0.55)
    area_style(off_peak, ORANGE, 0.75)
    # Today's area on top, so the pink that shows is what the tram adds.
    root = QgsProject.instance().layerTreeRoot()
    node = root.findLayer(off_peak.id())
    root.insertChildNode(0, node.clone())
    node.parent().removeChildNode(node)
    zoom(*SERVICE_AREA_VIEW)
    shot("17-service-area-with-tram")


def scenario_form_only():
    """Retake only picture 16 (the form with the scenario file), from files already made."""
    set_up()
    processing.run("easyr5:downloadr5", {"TARGET_FOLDER": os.environ["NF_R5"]})
    network = processing.run("easyr5:buildnetwork", {
        "OSM_PBF": str(WORK / "network" / "before.osm.pbf"),
        "GTFS_FOLDER": str(WORK / "gtfs")})["NETWORK_DAT"]
    downtown = QgsProject.instance().mapLayersByName("fountain_square")[0]
    dialog = form("easyr5:generateisochrones", {
        "NETWORK": network, "ORIGINS": downtown, "ORIGIN_ID_FIELD": "name",
        "DATE": DATE, "DEPARTURE_TIME": OFF_PEAK, "TIME_WINDOW": 60,
        "MAX_TRIP_DURATION": 30, "MODE": 0, "CUTOFFS": "30", "GRID_SPACING": 100,
        "SCENARIO": str(WORK / "uptown-tram.json")}, height=900)
    show_advanced(dialog, "Scenario file")
    shot("16-isochrones-scenario-form", dialog)


def main():
    try:
        from networkforge_qgis import engine
        engine.base_dir = lambda: Path(os.environ["NF_ENGINE"])
        LOG.append(f"providers: {[p.id() for p in QgsApplication.processingRegistry().providers()]}")
        (scenario_form_only if os.environ.get("NF_ONLY") == "16" else session)()
    except Exception:  # noqa: BLE001 - reported in the log file
        LOG.append(traceback.format_exc())
    (IMAGES / "transit-qgis.log").write_text("\n".join(LOG))
    QgsProject.instance().setDirty(False)
    QTimer.singleShot(3000, lambda: os._exit(0))
    iface.actionExit().trigger()


QTimer.singleShot(6000, main)
