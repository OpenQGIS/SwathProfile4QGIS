# -*- coding: utf-8 -*-
"""
Dock widget for swath profile algorithm parameters.
"""

from qgis.core import (
    QgsProject, QgsFeature, QgsGeometry, QgsCoordinateTransform, QgsMapLayerProxyModel,
    QgsProperty, QgsPropertyDefinition, QgsPropertyCollection,
    QgsExpressionContext, QgsExpressionContextUtils,
)
from qgis.gui import QgsMapLayerComboBox, QgsPropertyOverrideButton
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QCheckBox,
    QRadioButton, QButtonGroup, QGroupBox, QSpinBox,
    QDoubleSpinBox, QProgressBar, QMessageBox,
    QScrollArea, QSizePolicy, QLineEdit, QFileDialog,
)
from qgis.PyQt.QtCore import Qt, QThread
from .i18n import tr


# Property key constants
PROP_STRIP_WIDTH = 0
PROP_N_PROFILES = 1
PROP_STEP_SIZE = 2


class SwathParamDock(QDockWidget):
    """Dock widget for configuring swath profile parameters."""

    def __init__(self, plugin, parent=None):
        super().__init__(tr("剖面参数", "Swath Parameters"), parent)
        self.plugin = plugin
        self._worker = None
        self._thread = None
        self._drawn_geom = None
        self._swath_bands = []
        self._baseline_geoms_cache = []
        self._strip_widths_cache = []
        self._is_processing = False

        # Property definitions for data-defined override
        self._prop_defs = {
            PROP_STRIP_WIDTH: QgsPropertyDefinition(
                "strip_width", tr("条带宽度", "Strip width"),
                QgsPropertyDefinition.Double,
            ),
            PROP_N_PROFILES: QgsPropertyDefinition(
                "n_profiles", tr("剖面数", "Number of profiles"),
                QgsPropertyDefinition.Integer,
            ),
            PROP_STEP_SIZE: QgsPropertyDefinition(
                "step_size", tr("步长", "Step size"),
                QgsPropertyDefinition.Double,
            ),
        }
        self._prop_collection = QgsPropertyCollection("swath_params")

        self.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
            | Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea
        )
        self._build_ui()

    def minimumSizeHint(self):
        from qgis.PyQt.QtCore import QSize
        return QSize(200, 250)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Root container
        root = QWidget()
        self.setWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for parameters
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        main_layout.addWidget(scroll, 1)

        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 4)

        # --- Title ---
        title_label = QLabel(tr("剖面参数", "Swath Parameters"))
        title_label.setStyleSheet("font-weight:600; font-size:14px;")
        layout.addWidget(title_label)

        # --- DEM selector ---
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.dem_combo = QgsMapLayerComboBox()
        self.dem_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.dem_combo.setMinimumWidth(120)
        self.dem_combo.setToolTip(tr(
            "用于提取剖面高程的栅格数据。\n"
            "必须使用投影坐标系（如 UTM），单位为米。",
            "Raster layer for elevation sampling.\n"
            "Must use a projected CRS (e.g. UTM) in meters."
        ))
        form.addRow(tr("DEM 栅格:", "DEM raster:"), self.dem_combo)

        # --- Baseline selector ---
        self.line_combo = QgsMapLayerComboBox()
        self.line_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.line_combo.setMinimumWidth(120)
        self.line_combo.setToolTip(tr(
            "包含基线要素的线图层。\n"
            "每条线将独立生成一个剖面。",
            "Line layer containing baseline features.\n"
            "Each line generates one independent profile."
        ))
        form.addRow(tr("基线图层:", "Baseline layer:"), self.line_combo)
        layout.addLayout(form)

        # --- Draw-on-map button ---
        draw_row = QHBoxLayout()
        self.draw_btn = QPushButton(tr("地图绘制", "Draw on map"))
        self.draw_btn.setToolTip(tr(
            "在地图上手动绘制一条基线。\n"
            "左键添加节点，右键结束绘制。",
            "Draw a baseline manually on the map.\n"
            "Left-click to add vertices, right-click to finish."
        ))
        self.draw_btn.clicked.connect(self._on_draw)
        draw_row.addWidget(self.draw_btn)
        self.draw_status = QLabel("")
        draw_row.addWidget(self.draw_status, 1)
        layout.addLayout(draw_row)

        # --- Parameters form with override buttons ---
        param_form = QFormLayout()
        param_form.setLabelAlignment(Qt.AlignRight)

        # Strip width
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(1.0, 1e8)
        self.width_spin.setValue(500.0)
        self.width_spin.setToolTip(tr(
            "剖面的总宽度，单位与 DEM 相同（通常为米）。\n"
            "偏移线模式：以基线为中心，两侧各延伸一半宽度。",
            "Total swath width in DEM map units (usually meters).\n"
            "Offset-line: extends half-width each side of baseline."
        ))
        self.width_override = QgsPropertyOverrideButton(self)
        self.width_override.init(
            PROP_STRIP_WIDTH,
            QgsProperty(),
            self._prop_defs[PROP_STRIP_WIDTH],
            self.line_combo.currentLayer()
        )
        self.width_override.registerLinkedWidget(self.width_spin)
        self.width_override.setToolTip(tr("数据定义覆盖", "Data defined override"))
        self.width_override.changed.connect(self._on_override_changed)
        width_row = QHBoxLayout()
        width_row.addWidget(self.width_spin, 1)
        width_row.addWidget(self.width_override)
        param_form.addRow(tr("条带宽度:", "Strip width:"), width_row)

        # Step size
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.5, 1e6)
        self.step_spin.setValue(3.0)
        self.step_spin.setDecimals(1)
        self.step_spin.setToolTip(tr(
            "沿每条偏移线每隔多少米采样一个高程点。\n"
            "例：步长=2 表示每隔 2 米取一个点。\n"
            "推荐值：DEM 分辨率的 1~2 倍（如 DEM 为 12.5m，步长设 12~25）。\n"
            "值越小 → 曲线越精细，计算越慢。",
            "Sampling interval in map units along each offset line.\n"
            "Example: step=2 means sample every 2 meters.\n"
            "Recommended: 1-2× DEM resolution (e.g. DEM=12.5m, set 12-25).\n"
            "Smaller = smoother curve, slower computation."
        ))
        self.step_override = QgsPropertyOverrideButton(self)
        self.step_override.init(
            PROP_STEP_SIZE,
            QgsProperty(),
            self._prop_defs[PROP_STEP_SIZE],
            self.line_combo.currentLayer()
        )
        self.step_override.registerLinkedWidget(self.step_spin)
        self.step_override.setToolTip(tr("数据定义覆盖", "Data defined override"))
        self.step_override.changed.connect(self._on_override_changed)
        step_row = QHBoxLayout()
        step_row.addWidget(self.step_spin, 1)
        step_row.addWidget(self.step_override)
        param_form.addRow(tr("步长:", "Step size:"), step_row)

        # Number of profiles
        self.nlines_spin = QSpinBox()
        self.nlines_spin.setRange(2, 500)
        self.nlines_spin.setValue(30)
        self.nlines_spin.setToolTip(tr(
            "以基线为中心的平行偏移线总数。\n"
            "线越多，统计结果越稳定，但计算更慢。",
            "Total number of parallel offset lines centered on baseline.\n"
            "More lines = more stable stats but slower."
        ))
        self.nlines_override = QgsPropertyOverrideButton(self)
        self.nlines_override.init(
            PROP_N_PROFILES,
            QgsProperty(),
            self._prop_defs[PROP_N_PROFILES],
            self.line_combo.currentLayer()
        )
        self.nlines_override.registerLinkedWidget(self.nlines_spin)
        self.nlines_override.setToolTip(tr("数据定义覆盖", "Data defined override"))
        self.nlines_override.changed.connect(self._on_override_changed)
        nlines_row = QHBoxLayout()
        nlines_row.addWidget(self.nlines_spin, 1)
        nlines_row.addWidget(self.nlines_override)
        param_form.addRow(tr("剖面数:", "Number of profiles:"), nlines_row)
        layout.addLayout(param_form)

        # --- Only selected ---
        self.sel_check = QCheckBox(tr("仅选中要素", "Only selected features"))
        self.sel_check.setToolTip(tr(
            "只处理基线图层中当前选中的要素。\n"
            "未勾选时处理图层中的所有要素。",
            "Process only selected features from baseline layer.\n"
            "When unchecked, all features are processed."
        ))
        layout.addWidget(self.sel_check)

        # --- Export swath band ---
        self.export_check = QCheckBox(tr("导出条幅范围", "Export swath band"))
        self.export_check.setToolTip(tr(
            "处理完成后将条幅范围保存为矢量文件",
            "Save swath band polygon as vector file after processing"
        ))
        layout.addWidget(self.export_check)

        export_row = QHBoxLayout()
        self.export_path = QLineEdit()
        self.export_path.setPlaceholderText(tr("输出文件路径 (.shp)", "Output file path (.shp)"))
        self.export_path.setToolTip(tr("条幅范围输出路径", "Swath band output path"))
        export_row.addWidget(self.export_path)
        self.export_browse = QPushButton("...")
        self.export_browse.setFixedWidth(30)
        self.export_browse.setToolTip(tr("浏览选择文件", "Browse for file"))
        self.export_browse.clicked.connect(self._browse_export_path)
        export_row.addWidget(self.export_browse)
        layout.addLayout(export_row)

        layout.setAlignment(Qt.AlignTop)

        # --- Progress bar (fixed at bottom) ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_label = QLabel("")

        progress_widget = QWidget()
        progress_layout = QVBoxLayout(progress_widget)
        progress_layout.setContentsMargins(12, 4, 12, 4)
        progress_layout.setSpacing(2)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_label)
        main_layout.addWidget(progress_widget)

        # --- Buttons (fixed at bottom) ---
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 4, 12, 8)
        self.process_btn = QPushButton(tr("处理", "Process"))
        self.process_btn.setFixedWidth(80)
        self.process_btn.setToolTip(tr("开始计算剖面", "Start swath profile computation"))
        self.process_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                padding: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        self.process_btn.clicked.connect(self._on_process)
        btn_row.addWidget(self.process_btn)
        self.cancel_btn = QPushButton(tr("关闭", "Close"))
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.setToolTip(tr("关闭面板", "Close panel"))
        self._set_cancel_btn_style("close")
        self.cancel_btn.clicked.connect(self._on_cancel_or_close)
        btn_row.addWidget(self.cancel_btn)
        main_layout.addLayout(btn_row)

        # Allow widget to be resized smaller than content hint
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        # Connect layer change to update override buttons
        self.line_combo.layerChanged.connect(self._on_layer_changed)
        # Initialize override buttons with current layer
        self._on_layer_changed(self.line_combo.currentLayer())

    # ------------------------------------------------------------------
    # Override handling
    # ------------------------------------------------------------------

    def _on_override_changed(self, *args, **kwargs):
        """Sync property collection when override button changes."""
        btn = self.sender()
        if btn:
            key = btn.propertyKey()
            prop = btn.toProperty()
            self._prop_collection.setProperty(key, prop)

    def _on_layer_changed(self, layer):
        """Update override buttons when baseline layer changes."""
        for btn in (self.width_override, self.step_override, self.nlines_override):
            btn.setVectorLayer(layer)

    def _evaluate_property(self, key, feature, default_value):
        """Evaluate a property for a given feature."""
        prop = self._prop_collection.property(key)
        if prop and prop.isActive() and prop.isValid():
            context = QgsExpressionContext()
            context.appendScope(QgsExpressionContextUtils.projectScope(QgsProject.instance()))
            if feature:
                context.setFeature(feature)
            return prop.valueAsDouble(context, default_value)[0]
        return default_value

    # ------------------------------------------------------------------
    # Export path
    # ------------------------------------------------------------------

    def _browse_export_path(self):
        """Open file dialog to select export path."""
        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出条幅范围", "Export swath band"),
            "swath_band.shp",
            "Shapefile (*.shp);;GeoJSON (*.geojson);;GeoPackage (*.gpkg)"
        )
        if path:
            self.export_path.setText(path)

    # ------------------------------------------------------------------
    # Map drawing
    # ------------------------------------------------------------------

    def _on_draw(self):
        self.draw_status.setText(tr("在地图上点击…（右键完成）", "Click on map… (right-click to finish)"))
        self.plugin.activate_map_tool(self._on_draw_finished)
        self.showMinimized()

    def _on_draw_finished(self, geom):
        self.plugin.deactivate_map_tool()
        self.showNormal()
        if geom is not None:
            self._drawn_geom = geom
            self.draw_status.setText(
                tr(f"已绘制线段: {geom.length():.1f} 地图单位",
                   f"Drawn line: {geom.length():.1f} map units")
            )
        else:
            self._drawn_geom = None
            self.draw_status.setText(tr("已取消", "Cancelled"))

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def _on_process(self):
        raster = self.dem_combo.currentLayer()
        if raster is None:
            QMessageBox.warning(self, tr("横截面", "Swath"),
                                tr("请选择 DEM 栅格。", "Please select a DEM raster."))
            return

        # Validate DEM must be projected CRS
        dem_crs = raster.crs()
        if dem_crs.isGeographic():
            QMessageBox.warning(self, tr("横截面", "Swath"),
                                tr("DEM 必须使用投影坐标系（如 UTM），当前是地理坐标系。",
                                   "DEM must use a projected CRS (e.g. UTM). Current is geographic."))
            return

        # Collect baselines
        baselines = []
        if self._drawn_geom is not None:
            f = QgsFeature()
            f.setGeometry(self._drawn_geom)
            baselines.append(f)
            src_crs = QgsProject.instance().crs()
        else:
            line_layer = self.line_combo.currentLayer()
            if line_layer is None:
                QMessageBox.warning(self, tr("横截面", "Swath"),
                                    tr("请选择基线图层或在地图上绘制。",
                                       "Please select a baseline layer or draw on map."))
                return
            src_crs = line_layer.crs()
            if self.sel_check.isChecked():
                baselines = list(line_layer.selectedFeatures())
            else:
                baselines = list(line_layer.getFeatures())
            if not baselines:
                QMessageBox.warning(self, tr("横截面", "Swath"),
                                    tr("未找到要素。", "No features found."))
                return

        # Transform baseline geometries to DEM CRS
        if src_crs != dem_crs:
            xform = QgsCoordinateTransform(src_crs, dem_crs, QgsProject.instance())
            for feat in baselines:
                geom = feat.geometry()
                if geom and not geom.isEmpty():
                    geom.transform(xform)
                    feat.setGeometry(geom)

        # Build default params
        default_params = {
            "strip_width": self.width_spin.value(),
            "n_profiles": self.nlines_spin.value(),
            "step_size": self.step_spin.value(),
        }

        # Force sync property collection from GUI buttons to ensure they are 100% up to date
        self._prop_collection.setProperty(PROP_STRIP_WIDTH, self.width_override.toProperty())
        self._prop_collection.setProperty(PROP_STEP_SIZE, self.step_override.toProperty())
        self._prop_collection.setProperty(PROP_N_PROFILES, self.nlines_override.toProperty())

        # Launch worker with property collection for data-defined override
        from .swath_worker import SwathWorker
        self._thread = QThread()
        self._worker = SwathWorker(baselines, raster, default_params, "offset",
                                   self._prop_collection, self._prop_defs)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self.process_btn.setEnabled(False)
        self.cancel_btn.setText(tr("取消", "Cancel"))
        self.cancel_btn.setToolTip(tr("取消当前计算", "Cancel current computation"))
        self._set_cancel_btn_style("cancel")
        self._is_processing = True
        self.progress_bar.setValue(0)

        # Show total computation info
        n_features = len(baselines)
        n_profiles = default_params["n_profiles"]
        total_lines = n_features * n_profiles
        self.progress_label.setText(
            tr(f"计算: {n_features} 线 × {n_profiles} 剖面 = {total_lines} 条",
               f"Computing: {n_features} × {n_profiles} = {total_lines} lines")
        )

        self._thread.start()

    def _on_progress(self, pct, msg):
        self.progress_bar.setValue(pct)
        self.progress_label.setText(msg)

    def _process_single_line(self, feature):
        """Process a single line feature picked from map, but load all layer features so they can be switched in the dropdown."""
        from qgis.core import QgsCoordinateTransform, QgsProject, QgsFeature, QgsGeometry

        raster = self.dem_combo.currentLayer()
        if not raster:
            return

        dem_crs = raster.crs()
        if dem_crs.isGeographic():
            return

        line_layer = self.line_combo.currentLayer()
        if not line_layer:
            return

        # Get all baseline features from the layer (or selected if sel_check is on)
        if self.sel_check.isChecked():
            baselines = list(line_layer.selectedFeatures())
        else:
            baselines = list(line_layer.getFeatures())

        # Ensure the picked feature is in the list and find its index
        select_idx = 0
        found = False
        for idx, feat in enumerate(baselines):
            if feat.id() == feature.id():
                select_idx = idx
                found = True
                break
        if not found:
            # If the picked feature is not in the list (e.g. not selected, but clicked), append it
            baselines.append(feature)
            select_idx = len(baselines) - 1

        self._picked_select_idx = select_idx

        # Transform all baseline geometries to DEM CRS
        src_crs = line_layer.crs()
        if src_crs != dem_crs:
            xform = QgsCoordinateTransform(src_crs, dem_crs, QgsProject.instance())
            for feat in baselines:
                geom = feat.geometry()
                if geom and not geom.isEmpty():
                    geom = QgsGeometry(geom)
                    geom.transform(xform)
                    feat.setGeometry(geom)

        # Build params
        params = {
            "strip_width": self.width_spin.value(),
            "n_profiles": self.nlines_spin.value(),
            "step_size": self.step_spin.value(),
        }

        # Force sync property collection from GUI buttons to ensure they are 100% up to date
        self._prop_collection.setProperty(PROP_STRIP_WIDTH, self.width_override.toProperty())
        self._prop_collection.setProperty(PROP_STEP_SIZE, self.step_override.toProperty())
        self._prop_collection.setProperty(PROP_N_PROFILES, self.nlines_override.toProperty())

        # Launch worker
        from .swath_worker import SwathWorker
        self._thread = QThread()
        self._worker = SwathWorker(baselines, raster, params, "offset",
                                   self._prop_collection, self._prop_defs)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self.process_btn.setEnabled(False)
        self.cancel_btn.setText(tr("取消", "Cancel"))
        self.cancel_btn.setToolTip(tr("取消当前计算", "Cancel current computation"))
        self._set_cancel_btn_style("cancel")
        self._is_processing = True
        self.progress_bar.setValue(0)

        # Show total computation info
        n_features = len(baselines)
        n_profiles = params["n_profiles"]
        total_lines = n_features * n_profiles
        self.progress_label.setText(
            tr(f"计算: {n_features} 线 × {n_profiles} 剖面 = {total_lines} 条",
               f"Computing: {n_features} × {n_profiles} = {total_lines} lines")
        )

        self._thread.start()

    def _on_finished(self, results, baseline_geoms, fields=None, field_values=None, strip_widths=None):
        self._cleanup_thread()
        if not results:
            QMessageBox.information(self, tr("横截面", "Swath"),
                                    tr("未计算出剖面。", "No profiles computed."))
            return
        
        # Store per-feature strip widths
        self._strip_widths_cache = strip_widths or []
        self._baseline_geoms_cache = baseline_geoms
        
        # Show completed status
        self.progress_bar.setValue(100)
        self.progress_label.setText(tr("已完成", "Completed"))
        
        select_idx = getattr(self, "_picked_select_idx", 0)
        self._picked_select_idx = 0
        
        self.plugin.show_dock(results, mode="offset", baseline_geoms=baseline_geoms,
                              fields=fields, field_values=field_values,
                              strip_widths=strip_widths, select_idx=select_idx)

        # Display swath band on map
        self._show_swath_bands(baseline_geoms)

        # Export swath band if checkbox is checked
        if self.export_check.isChecked():
            self._export_swath_bands(baseline_geoms)

    def _on_error(self, msg):
        self._cleanup_thread()
        QMessageBox.critical(self, tr("错误", "Swath Error"), msg)

    def _on_cancel_or_close(self):
        """Cancel processing if running, otherwise close the dock."""
        if hasattr(self, '_is_processing') and self._is_processing:
            if self._worker:
                self._worker.cancel()
        else:
            self.close()

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()

    def _set_cancel_btn_style(self, mode="close"):
        """Set cancel button style based on mode."""
        if mode == "cancel":
            self.cancel_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: none;
                    padding: 4px;
                }
                QPushButton:hover { background-color: #e53935; }
                QPushButton:pressed { background-color: #d32f2f; }
            """)
        else:  # close
            self.cancel_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196f3;
                    color: white;
                    border: none;
                    padding: 4px;
                }
                QPushButton:hover { background-color: #1e88e5; }
                QPushButton:pressed { background-color: #1565c0; }
            """)

    def _cleanup_thread(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None
        self.process_btn.setEnabled(True)
        self._is_processing = False
        self.cancel_btn.setText(tr("关闭", "Close"))
        self.cancel_btn.setToolTip(tr("关闭面板", "Close panel"))
        self._set_cancel_btn_style("close")

    def _show_swath_bands(self, baseline_geoms):
        """Display swath band polygons on the map canvas."""
        from qgis.gui import QgsRubberBand
        from qgis.core import Qgis, QgsPointXY, QgsGeometry
        from qgis.PyQt.QtGui import QColor

        # Remove old bands
        self._clear_swath_bands()

        # Store baseline geoms and show only selected one
        self._baseline_geoms_cache = baseline_geoms
        self._show_selected_band()

    def _show_selected_band(self, idx=0):
        """Show the swath band for the selected baseline."""
        from qgis.gui import QgsRubberBand
        from qgis.core import Qgis, QgsPointXY, QgsGeometry, QgsProject, QgsCoordinateTransform
        from qgis.PyQt.QtGui import QColor

        self._clear_swath_bands()

        if not self._baseline_geoms_cache:
            return
        if idx < 0 or idx >= len(self._baseline_geoms_cache):
            return

        try:
            canvas = self.plugin.iface.mapCanvas()
            # Use per-feature strip width if available, otherwise fall back to spinbox
            if self._strip_widths_cache and idx < len(self._strip_widths_cache):
                half_width = self._strip_widths_cache[idx] / 2.0
            else:
                half_width = self.width_spin.value() / 2.0

            # Get band settings from dock
            settings = {}
            if self.plugin.profile_dock:
                settings = self.plugin.profile_dock.get_settings()

            fill_color_hex = settings.get("band_fill_color", "#ff0000")
            fill_opacity = settings.get("band_fill_opacity", 30)
            stroke_color_hex = settings.get("band_stroke_color", "#ff0000")
            stroke_width = settings.get("band_stroke_width", 0.3)
            stroke_opacity = settings.get("band_stroke_opacity", 80)

            fill_color = QColor(fill_color_hex)
            fill_color.setAlphaF(fill_opacity / 100.0)
            stroke_color = QColor(stroke_color_hex)
            stroke_color.setAlphaF(stroke_opacity / 100.0)

            geom = QgsGeometry(self._baseline_geoms_cache[idx])  # copy

            # Transform from DEM CRS to project CRS for display
            dem_crs = self.dem_combo.currentLayer().crs()
            proj_crs = QgsProject.instance().crs()
            if dem_crs != proj_crs:
                xform = QgsCoordinateTransform(dem_crs, proj_crs, QgsProject.instance())
                geom.transform(xform)

            # Create flat-ended band polygon using offset lines
            band = self._create_flat_band(geom, half_width)
            if band and not band.isEmpty():
                try:
                    rb = QgsRubberBand(canvas, Qgis.GeometryType.Polygon)
                except:
                    rb = QgsRubberBand(canvas)
                rb.setToGeometry(band, None)
                rb.setFillColor(fill_color)
                rb.setStrokeColor(stroke_color)
                rb.setWidth(int(stroke_width * 10))
                try:
                    rb.setZValue(100)
                except:
                    pass
                self._swath_bands = [rb]

            canvas.refresh()
        except Exception as e:
            print(f"Swath band error: {e}")

    def _export_swath_bands(self, baseline_geoms):
        """Export swath band polygons to file or load as a temporary layer."""
        from qgis.core import (Qgis, QgsGeometry, QgsProject, QgsCoordinateTransform,
                                QgsVectorFileWriter, QgsVectorLayer, QgsFeature, QgsField)
        from qgis.PyQt.QtCore import QVariant

        try:
            output_path = self.export_path.text().strip()

            half_width = self.width_spin.value() / 2.0
            dem_crs = self.dem_combo.currentLayer().crs()
            proj_crs = QgsProject.instance().crs()

            # Create memory layer
            geom_type = "Polygon"
            uri = f"{geom_type}?crs={proj_crs.authid()}"
            layer = QgsVectorLayer(uri, "swath_band", "memory")
            provider = layer.dataProvider()
            provider.addAttributes([
                QgsField("id", QVariant.Int),
                QgsField("width", QVariant.Double),
            ])
            layer.updateFields()

            # Add features
            for idx, geom in enumerate(baseline_geoms):
                # Copy geometry
                band_geom = QgsGeometry(geom)

                # Transform from DEM CRS to project CRS
                if dem_crs != proj_crs:
                    xform = QgsCoordinateTransform(dem_crs, proj_crs, QgsProject.instance())
                    band_geom.transform(xform)

                # Create band polygon
                band = self._create_flat_band(band_geom, half_width)
                if band and not band.isEmpty():
                    feat = QgsFeature(layer.fields())
                    feat.setGeometry(band)
                    feat.setAttribute("id", idx + 1)
                    feat.setAttribute("width", self.width_spin.value())
                    provider.addFeature(feat)

            if not output_path:
                # If output path is empty, generate temporary scratch layer directly in QGIS
                layer.setName(tr("条幅范围 (临时)", "Swath Band (Temporary)"))
                QgsProject.instance().addMapLayer(layer)
                self._show_native_success_message(
                    path=None,
                    custom_msg=tr("<b>条幅范围生成成功！</b>已成功生成条幅范围临时图层并加载至地图中。",
                                  "<b>Swath Band Generated!</b> Successfully generated temporary scratch layer and loaded it into the map.")
                )
                return

            # Save to file
            error = QgsVectorFileWriter.writeAsVectorFormat(
                layer, output_path, "UTF-8", layer.crs(),
                QgsVectorFileWriter.driverForFileName(output_path)
            )

            if error[0] == QgsVectorFileWriter.NoError:
                # Also load the saved layer into QGIS
                import os
                base_name = os.path.splitext(os.path.basename(output_path))[0]
                loaded_layer = QgsVectorLayer(output_path, base_name, "ogr")
                if loaded_layer.isValid():
                    QgsProject.instance().addMapLayer(loaded_layer)
                
                self._show_native_success_message(
                    path=output_path,
                    custom_msg=tr(f"<b>条幅范围导出成功！</b>已导出并加载到地图中：<u>{os.path.normpath(output_path)}</u>",
                                  f"<b>Swath Band Exported!</b> Exported and loaded into the map: <u>{os.path.normpath(output_path)}</u>")
                )
            else:
                QMessageBox.warning(self, tr("导出失败", "Export Failed"),
                                    tr(f"导出错误: {error[1]}",
                                       f"Export error: {error[1]}"))

        except Exception as e:
            QMessageBox.critical(self, tr("导出错误", "Export Error"), str(e))

    def _show_native_success_message(self, path=None, file_type_name="", custom_msg=""):
        """Show a native QGIS message bar notification with a 'Show in Folder' button."""
        if not self.plugin or not self.plugin.iface:
            return
        
        from qgis.core import Qgis
        from qgis.PyQt.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
        from qgis.PyQt.QtCore import Qt
        import os
        import subprocess
        import sys

        iface = self.plugin.iface
        message_bar = iface.messageBar()

        # Create custom widget
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Style the label to look beautiful
        if custom_msg:
            msg_text = custom_msg
        else:
            display_path = os.path.normpath(path) if path else ""
            msg_text = tr(
                f"<b>{file_type_name} 导出成功！</b> 已将成果保存至：<u>{display_path}</u>",
                f"<b>{file_type_name} Exported Successfully!</b> Saved to: <u>{display_path}</u>"
            )
            
        label = QLabel(msg_text)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        layout.addWidget(label)

        if path:
            # Show in Folder Button
            btn = QPushButton(tr("在文件夹中显示", "Show in Folder"))
            
            # Cross-platform select file in explorer
            def open_folder():
                try:
                    abs_path = os.path.abspath(path)
                    if sys.platform.startswith('win'):
                        subprocess.run(['explorer', '/select,', os.path.normpath(abs_path)], shell=True)
                    elif sys.platform == 'darwin':
                        subprocess.run(['open', '-R', abs_path])
                    else:
                        dir_path = os.path.dirname(abs_path)
                        subprocess.run(['xdg-open', dir_path])
                except Exception as e:
                    print(f"Error opening folder: {e}")

            btn.clicked.connect(open_folder)
            layout.addWidget(btn)

        # Push to QGIS native message bar
        message_bar.pushWidget(widget, Qgis.MessageLevel.Success, 7)

    def _create_flat_band(self, line_geom, half_width):
        """Create a flat-ended band polygon from a line geometry."""
        from qgis.core import Qgis, QgsPointXY, QgsGeometry

        # Get offset lines on both sides
        offset_plus = line_geom.offsetCurve(half_width, 8, Qgis.JoinStyle.Round, 10.0)
        offset_minus = line_geom.offsetCurve(-half_width, 8, Qgis.JoinStyle.Round, 10.0)

        if offset_plus is None or offset_plus.isEmpty():
            return None
        if offset_minus is None or offset_minus.isEmpty():
            return None

        # Get points from both offset lines
        pts_plus = offset_plus.asPolyline()
        pts_minus = offset_minus.asPolyline()

        if not pts_plus or not pts_minus:
            return None

        # Reverse the minus line to close the polygon
        pts_minus.reverse()

        # Combine into a closed polygon
        polygon_pts = pts_plus + pts_minus + [pts_plus[0]]

        return QgsGeometry.fromPolygonXY([polygon_pts])

    def _clear_swath_bands(self):
        """Remove swath band rubber bands from the canvas."""
        if hasattr(self, '_swath_bands') and self._swath_bands:
            canvas = self.plugin.iface.mapCanvas()
            for rb in self._swath_bands:
                canvas.scene().removeItem(rb)
            self._swath_bands = []
            canvas.refresh()

    def closeEvent(self, event):
        self._on_cancel()
        self._cleanup_thread()
        super().closeEvent(event)
