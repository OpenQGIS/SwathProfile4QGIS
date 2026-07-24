# -*- coding: utf-8 -*-
"""
Dock widget for displaying swath profile charts.
"""

import csv
import os

from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QFileDialog,
    QSizePolicy, QToolBar, QDialog, QToolButton, QMenu, QInputDialog,
)
from qgis.PyQt.QtGui import QAction, QIcon
from qgis.PyQt.QtCore import Qt

from .swath_canvas import InteractiveCanvas
from .swath_plot import (
    create_profile_figure,
    draw_swath_profile,
    draw_thi_profile,
)
from .i18n import tr


def _icon(name):
    """Load icon from panel_icons folder."""
    path = os.path.join(os.path.dirname(__file__), "panel_icons", name)
    if os.path.isfile(path):
        return QIcon(path)
    return QIcon()


import math
import numpy as np

def get_nice_ticks(min_val, max_val, target_count=5):
    span = max_val - min_val
    if span <= 0:
        return [min_val], 1.0
    rough_step = span / target_count
    step_power = 10.0 ** math.floor(math.log10(rough_step))
    normalized = rough_step / step_power
    if normalized < 1.5:
        nice_step = 1.0 * step_power
    elif normalized < 3.0:
        nice_step = 2.0 * step_power
    elif normalized < 7.0:
        nice_step = 5.0 * step_power
    else:
        nice_step = 10.0 * step_power
        
    start_tick = math.ceil(min_val / nice_step) * nice_step
    ticks = []
    curr = start_tick
    while curr <= max_val + 1e-9 * span:
        ticks.append(curr)
        curr += nice_step
    if not ticks:
        ticks = [min_val]
    return ticks, nice_step


class DXFBuilder:
    def __init__(self, version="AC1015"):
        self.entities = []
        self.layers = {} # name -> color
        self.version = version

    def add_layer(self, name, color=7):
        self.layers[name] = color

    def add_line(self, start, end, layer="0", color=None):
        x1, y1 = start[0], start[1]
        z1 = start[2] if len(start) > 2 else 0.0
        x2, y2 = end[0], end[1]
        z2 = end[2] if len(end) > 2 else 0.0
        
        self.entities.append(f"0\nLINE\n8\n{layer}")
        if color is not None:
            self.entities.append(f"62\n{color}")
        self.entities.append(f"10\n{x1}\n20\n{y1}\n30\n{z1}")
        self.entities.append(f"11\n{x2}\n21\n{y2}\n31\n{z2}")

    def add_lwpolyline(self, points, layer="0", color=None, closed=False):
        n = len(points)
        self.entities.append(f"0\nLWPOLYLINE\n100\nAcDbEntity\n8\n{layer}")
        if color is not None:
            self.entities.append(f"62\n{color}")
        self.entities.append(f"100\nAcDbPolyline\n90\n{n}\n70\n{1 if closed else 0}")
        for pt in points:
            self.entities.append(f"10\n{pt[0]}\n20\n{pt[1]}")

    def add_polyline3d(self, points, layer="0", color=None):
        self.entities.append(f"0\nPOLYLINE\n8\n{layer}")
        if color is not None:
            self.entities.append(f"62\n{color}")
        self.entities.append(f"66\n1\n70\n8") # 8 = 3D Polyline
        for pt in points:
            x, y = pt[0], pt[1]
            z = pt[2] if len(pt) > 2 else 0.0
            self.entities.append(f"0\nVERTEX\n8\n{layer}\n10\n{x}\n20\n{y}\n30\n{z}\n70\n32")
        self.entities.append(f"0\nSEQEND\n8\n{layer}")

    def add_text(self, text, pt, height=10.0, rotation=0.0, layer="0", color=None, halign=0, valign=0):
        x, y = pt[0], pt[1]
        z = pt[2] if len(pt) > 2 else 0.0
        self.entities.append(f"0\nTEXT\n100\nAcDbEntity\n8\n{layer}")
        if color is not None:
            self.entities.append(f"62\n{color}")
        self.entities.append(f"100\nAcDbText\n10\n{x}\n20\n{y}\n30\n{z}\n40\n{height}\n1\n{text}")
        if rotation != 0.0:
            self.entities.append(f"50\n{rotation}")
        if halign != 0 or valign != 0:
            self.entities.append(f"72\n{halign}\n73\n{valign}")
            self.entities.append(f"11\n{x}\n21\n{y}\n31\n{z}")

    def to_string(self):
        lines = []
        lines.append(f"0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\n{self.version}\n0\nENDSEC")
        
        # TABLES (Layers)
        lines.append("0\nSECTION\n2\nTABLES\n0\nTABLE\n2\nLTYPE\n70\n1\n0\nLTYPE\n2\nCONTINUOUS\n70\n0\n3\nSolid line\n72\n65\n73\n0\n40\n0.0\n0\nENDTAB")
        lines.append("0\nTABLE\n2\nLAYER\n70\n" + str(len(self.layers)))
        for name, color in self.layers.items():
            lines.append(f"0\nLAYER\n2\n{name}\n70\n0\n62\n{color}\n6\nCONTINUOUS")
        lines.append("0\nENDTAB\n0\nENDSEC")
        
        # BLOCKS
        lines.append("0\nSECTION\n2\nBLOCKS\n0\nENDSEC")
        
        # ENTITIES
        lines.append("0\nSECTION\n2\nENTITIES")
        for ent in self.entities:
            lines.append(ent)
        lines.append("0\nENDSEC")
        
        # EOF
        lines.append("0\nEOF")
        return "\n".join(lines)


class SwathDock(QDockWidget):
    """Bottom-docked widget showing swath profile chart and controls."""

    def __init__(self, plugin, parent=None):
        super().__init__(tr("横截面剖面", "Swath Profile"), parent)
        self.plugin = plugin
        self._profiles = []
        self._baseline_geoms = []
        self._mode = "offset"
        self._current_idx = 0
        self._settings = None  # Will be initialized in _build_ui

        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.setMinimumHeight(200)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QWidget()
        self.setWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(4)

        # ==== Top: Toolbar (functional icons only) ====
        toolbar = QToolBar()
        toolbar.setIconSize(toolbar.iconSize() * 0.70)
        toolbar.setMovable(False)

        # 1. Settings
        self.act_settings = QAction(_icon("settings.svg"),
                                    tr("设置", "Settings"), self)
        self.act_settings.setToolTip(tr("线条颜色和条带样式设置", "Line colors and band style settings"))
        self.act_settings.triggered.connect(self._open_settings)
        toolbar.addAction(self.act_settings)

        # 1b. Smooth Toggle (with drop-down menu for intensity selection)
        self.btn_smooth = QToolButton()
        self.btn_smooth.setIcon(_icon("smooth.svg"))
        self.btn_smooth.setText(tr("平滑", "Smooth"))
        self.btn_smooth.setToolTip(tr("曲线平滑 (Savitzky-Golay)\n点击开启/关闭，点击下拉箭头选择强度", "Curve smoothing (Savitzky-Golay)\nClick to toggle, or click dropdown arrow to select intensity"))
        self.btn_smooth.setCheckable(True)
        self.btn_smooth.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_smooth.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_smooth.toggled.connect(self._toggle_smooth)
        
        # Build dropdown menu for smoothing intensity
        self._smooth_menu = QMenu(self)
        self._smooth_menu.aboutToShow.connect(self._update_smooth_menu_checks)
        self._smooth_actions = {}
        intensities = [
            (5, tr("低强度 (5点)", "Low (5 pts)")),
            (9, tr("中等强度 (9点)", "Medium (9 pts)")),
            (15, tr("高强度 (15点)", "High (15 pts)")),
            (25, tr("超强平滑 (25点)", "Ultra (25 pts)")),
        ]
        for size, name in intensities:
            act = QAction(name, self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, s=size: self._set_smooth_intensity(s))
            self._smooth_menu.addAction(act)
            self._smooth_actions[size] = act
            
        self.btn_smooth.setMenu(self._smooth_menu)
        toolbar.addWidget(self.btn_smooth)

        # 1c. Set Y-Axis Label
        self.act_y_label = QAction(_icon("y_axis.svg"),
                                   tr("设置纵坐标名称", "Set Y-Axis Label"), self)
        self.act_y_label.setToolTip(tr("手动设置纵坐标（Y轴）名称", "Manually set vertical coordinate (Y-axis) label"))
        self.act_y_label.triggered.connect(self._set_y_label)
        toolbar.addAction(self.act_y_label)

        toolbar.addSeparator()

        # 2. Reset view
        self.act_reset = QAction(_icon("reset_view.svg"),
                                 tr("全图显示", "Reset View"), self)
        self.act_reset.setToolTip(tr("重置缩放和平移", "Reset zoom and pan"))
        self.act_reset.triggered.connect(self._reset_view)
        toolbar.addAction(self.act_reset)

        toolbar.addSeparator()

        # 3. Pick line from map
        self.act_pick = QAction(_icon("pick_line.svg"),
                                tr("选择线", "Pick Line"), self)
        self.act_pick.setToolTip(tr("从地图视图拾取线段并生成剖面", "Pick a line from map view and generate profile"))
        self.act_pick.triggered.connect(self._pick_line_from_map)
        toolbar.addAction(self.act_pick)

        # 4. Clear swath bands
        self.act_clear = QAction(_icon("clear.svg"),
                                 tr("清除选择", "Clear"), self)
        self.act_clear.setToolTip(tr("清除地图上的条带显示", "Clear swath bands from map"))
        self.act_clear.triggered.connect(self._clear_swath_bands)
        toolbar.addAction(self.act_clear)

        toolbar.addSeparator()

        # 5. Export PNG with dropdown
        self.btn_export_png = self._create_export_button(
            "export-image.svg", tr("导出图片", "Export PNG"), "png")
        toolbar.addWidget(self.btn_export_png)

        # 6. Export PDF with dropdown
        self.btn_export_pdf = self._create_export_button(
            "export-pdf.svg", tr("导出 PDF", "Export PDF"), "pdf")
        toolbar.addWidget(self.btn_export_pdf)

        # 7. Export SVG with dropdown
        self.btn_export_svg = self._create_export_button(
            "export-svg.svg", tr("导出 SVG", "Export SVG"), "svg")
        toolbar.addWidget(self.btn_export_svg)

        # 8. Export CSV
        self.act_csv = QAction(_icon("export_csv.svg"),
                               tr("导出表格", "Export CSV"), self)
        self.act_csv.setToolTip(tr("导出数据为 CSV/TXT", "Export data as CSV/TXT"))
        self.act_csv.triggered.connect(self._export_csv)
        toolbar.addAction(self.act_csv)

        # 9. Export CAD (2D / 3D)
        self.btn_export_cad = QToolButton()
        self.btn_export_cad.setIcon(_icon("export_cad.svg"))
        self.btn_export_cad.setText(tr("导出 CAD", "Export CAD"))
        self.btn_export_cad.setToolTip(tr("导出为 AutoCAD DXF/DWG 文件 (2D/3D)", "Export as AutoCAD DXF/DWG file (2D/3D)"))
        self.btn_export_cad.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_export_cad.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup) # 点击直接弹出菜单

        cad_menu = QMenu(self)
        act_cad2d = cad_menu.addAction(tr("导出 2D CAD 剖面图", "Export 2D CAD Profile Chart"))
        act_cad2d.triggered.connect(self._export_cad_2d)
        act_cad3d = cad_menu.addAction(tr("导出 3D CAD 空间线", "Export 3D CAD Geographic Lines"))
        act_cad3d.triggered.connect(self._export_cad_3d)
        self.btn_export_cad.setMenu(cad_menu)

        toolbar.addWidget(self.btn_export_cad)

        # 10. Export GIS (SHP, GPKG, KML, etc.)
        self.btn_export_gis = QToolButton()
        self.btn_export_gis.setIcon(_icon("export-GISdata.svg"))
        self.btn_export_gis.setText(tr("导出 GIS 数据", "Export GIS Data"))
        self.btn_export_gis.setToolTip(tr("导出为 GIS 矢量数据 (SHP/GPKG/KML等)", "Export as GIS vector data (SHP/GPKG/KML etc.)"))
        self.btn_export_gis.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_export_gis.clicked.connect(self._open_gis_export_dialog)
        
        toolbar.addWidget(self.btn_export_gis)

        # Right side: profile selector
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self.points_label = QLabel("")
        self.points_label.setStyleSheet("color:#7a7a7a; font-size:11px;")
        toolbar.addWidget(self.points_label)

        # Field selector
        self.field_combo = QComboBox()
        self.field_combo.setFixedWidth(60)
        self.field_combo.currentIndexChanged.connect(self._on_field_changed)
        toolbar.addWidget(self.field_combo)

        # Value selector
        self.value_combo = QComboBox()
        self.value_combo.setFixedWidth(70)
        self.value_combo.currentIndexChanged.connect(self._on_value_changed)
        toolbar.addWidget(self.value_combo)

        vbox.addWidget(toolbar)

        # ==== Chart (expandable) ====
        self.figure, self.ax_main, self.ax_thi = create_profile_figure(
            show_thi=True
        )
        self.canvas = InteractiveCanvas(self.figure, plugin=self.plugin)
        self.canvas.setMinimumHeight(100)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        vbox.addWidget(self.canvas, 1)

        # ==== Bottom: display checkboxes with color swatches ====
        chk_row = QHBoxLayout()
        chk_row.setSpacing(10)
        self._swatches = {}  # Store swatch widgets for color updates

        def _make_chk(key, text, color, tooltip="", checked=False):
            """Create a checkbox with a color swatch. Returns (chk, swatch)."""
            container = QWidget()
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            chk = QCheckBox()
            chk.setChecked(checked)
            chk.setToolTip(tooltip)
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background:{color}; border:1px solid #999; border-radius:2px;")
            label = QLabel(text)
            label.setToolTip(tooltip)
            h.addWidget(chk)
            h.addWidget(swatch)
            h.addWidget(label)
            chk_row.addWidget(container)
            self._swatches[key] = swatch
            return chk

        self.chk_profiles = _make_chk("color_profiles", tr("偏移线", "Profiles"), "#C8C8C8",
                                       tr("显示/隐藏偏移线", "Show/hide offset lines"), True)
        self.chk_min = _make_chk("color_min", tr("最小值", "Min"), "#4dd48a",
                                  tr("显示/隐藏最小值曲线", "Show/hide min curve"), True)
        self.chk_max = _make_chk("color_max", tr("最大值", "Max"), "#f8ba81",
                                  tr("显示/隐藏最大值曲线", "Show/hide max curve"), True)
        self.chk_mean = _make_chk("color_mean", tr("均值", "Mean"), "#01008a",
                                   tr("显示/隐藏均值曲线", "Show/hide mean curve"), True)
        self.chk_q1 = _make_chk("color_q1", "Q1", "#008a8c",
                                 tr("显示/隐藏 Q1 曲线", "Show/hide Q1 curve"), True)
        self.chk_q3 = _make_chk("color_q3", "Q3", "#008a8c",
                                 tr("显示/隐藏 Q3 曲线", "Show/hide Q3 curve"), True)
        self.chk_relief = _make_chk("color_relief", tr("起伏", "Relief"), "#cc3333",
                                     tr("显示/隐藏起伏曲线", "Show/hide relief curve"))
        self.chk_thi = _make_chk("color_thi", "THi", "#8B4513",
                                  tr("显示/隐藏 THi 指数", "Show/hide THi index"))
        self.chk_enhanced = QCheckBox("THi*")
        self.chk_enhanced.setToolTip(tr("使用增强 THi 重缩放", "Use enhanced THi rescaling"))
        chk_row.addWidget(self.chk_enhanced)

        for chk in (self.chk_profiles, self.chk_min, self.chk_max,
                    self.chk_mean, self.chk_q1, self.chk_q3,
                    self.chk_relief, self.chk_thi, self.chk_enhanced):
            chk.stateChanged.connect(lambda: self._redraw(fit_view=False))
        chk_row.addStretch(1)
        vbox.addLayout(chk_row)

    def _create_export_button(self, icon_name, text, fmt):
        """Create an export button with dropdown menu."""
        btn = QToolButton()
        btn.setIcon(_icon(icon_name))
        btn.setText(text)
        btn.setToolTip(text)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup) # 点击图标直接打开菜单

        menu = QMenu(self)
        act_view = menu.addAction(tr("当前视图", "Current View"))
        act_view.triggered.connect(lambda: self._save_image(fmt, "view"))
        act_full = menu.addAction(tr("全局范围", "Full Extent"))
        act_full.triggered.connect(lambda: self._save_image(fmt, "full"))
        btn.setMenu(menu)

        return btn

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_profiles(self, profiles, mode="offset", baseline_geoms=None, fields=None, field_values=None, strip_widths=None, select_idx=0):
        self._profiles = profiles
        self._baseline_geoms = baseline_geoms or []
        self._strip_widths = strip_widths or []
        self._mode = mode
        self._current_idx = select_idx if (select_idx >= 0 and select_idx < len(profiles)) else 0
        self._fields = fields or []
        self._field_values = field_values or []

        # Populate field combo
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        for field_name in self._fields:
            self.field_combo.addItem(field_name)
        self.field_combo.blockSignals(False)

        # Populate value combo
        self._update_value_combo()

        # Hide THi checkboxes for zonal mode
        is_offset = (mode == "offset")
        self.chk_thi.setVisible(is_offset)
        self.chk_enhanced.setVisible(is_offset)
        self.chk_q1.setVisible(is_offset)
        self.chk_q3.setVisible(is_offset)
        self.chk_profiles.setVisible(is_offset)

        self._redraw(fit_view=True)

    # ------------------------------------------------------------------
    # Field / Value selectors
    # ------------------------------------------------------------------

    def _on_field_changed(self, field_idx):
        """Update value combo when field selection changes."""
        self._update_value_combo()

    def _on_value_changed(self, value_idx):
        """Update current profile when value selection changes."""
        if value_idx >= 0 and value_idx < len(self._profiles):
            self._current_idx = value_idx
            self._redraw(fit_view=True)
            # Update swath band on map
            if self.plugin.param_dock:
                self.plugin.param_dock._show_selected_band(value_idx)

    def _update_value_combo(self):
        """Update value combo based on selected field."""
        self.value_combo.blockSignals(True)
        self.value_combo.clear()

        field_idx = self.field_combo.currentIndex()
        if field_idx >= 0 and field_idx < len(self._field_values):
            values = self._field_values[field_idx]
            for val in values:
                self.value_combo.addItem(str(val))

        self.value_combo.blockSignals(False)

        # Update current index
        if self.value_combo.count() > 0:
            idx_to_set = self._current_idx if (self._current_idx >= 0 and self._current_idx < self.value_combo.count()) else 0
            self.value_combo.setCurrentIndex(idx_to_set)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _redraw(self, fit_view=False):
        if not self._profiles:
            return
        sp = self._profiles[self._current_idx]
        show_thi = self.chk_thi.isChecked() and self._mode == "offset"

        settings = self.get_settings()
        if settings.get("smooth_enabled", False):
            sp = sp.smoothed(settings.get("smooth_window", 9))

        # Determine dynamic y-axis label based on raster layer name or custom override
        y_label = tr("高程", "Elevation")
        custom_y_label = settings.get("custom_y_label", "").strip()
        if custom_y_label:
            y_label = custom_y_label
        elif self.plugin.param_dock:
            dem_layer = self.plugin.param_dock.dem_combo.currentLayer()
            if dem_layer:
                y_label = dem_layer.name()

        # Save current view limits (only if not fitting to new profile)
        xlim, ylim = None, None
        if not fit_view and self.figure.get_axes():
            ax0 = self.figure.get_axes()[0]
            cur_xlim = ax0.get_xlim()
            cur_ylim = ax0.get_ylim()
            if cur_xlim != (0.0, 1.0) and cur_ylim != (0.0, 1.0):
                xlim = cur_xlim
                ylim = cur_ylim

        self.figure.clear()
        if show_thi:
            from matplotlib.gridspec import GridSpec
            gs = GridSpec(2, 1, height_ratios=[4, 1], hspace=0.0,
                          figure=self.figure)
            ax_main = self.figure.add_subplot(gs[0])
            ax_thi = self.figure.add_subplot(gs[1], sharex=ax_main)
            # Hide main x-axis labels, THi will show them
            ax_main.tick_params(labelbottom=False)
        else:
            ax_main = self.figure.add_subplot(111)
            ax_thi = None

        try:
            draw_swath_profile(
                ax_main, sp,
                show_profiles=self.chk_profiles.isChecked(),
                show_min=self.chk_min.isChecked(),
                show_max=self.chk_max.isChecked(),
                show_mean=self.chk_mean.isChecked(),
                show_q1=self.chk_q1.isChecked(),
                show_q3=self.chk_q3.isChecked(),
                show_relief=self.chk_relief.isChecked(),
                colors=settings,
                y_label=y_label,
            )
            if ax_thi is not None:
                draw_thi_profile(ax_thi, sp,
                                enhanced=self.chk_enhanced.isChecked(),
                                colors=settings)

            # Restore view limits (only when toggling checkboxes)
            if not fit_view and xlim is not None and ylim is not None:
                new_xlim = ax_main.get_xlim()
                new_ylim = ax_main.get_ylim()
                if (xlim[0] <= new_xlim[1] and xlim[1] >= new_xlim[0] and
                    ylim[0] <= new_ylim[1] and ylim[1] >= new_ylim[0]):
                    ax_main.set_xlim(xlim)
                    ax_main.set_ylim(ylim)
        except Exception as e:
            print(f"Swath draw error: {e}")

        self.figure.tight_layout()

        # Set profile data for hover-to-map interaction
        baseline_geom = None
        swath_width = 500.0
        dem_crs = None
        proj_crs = QgsProject.instance().crs()
        if self._current_idx < len(self._baseline_geoms):
            baseline_geom = self._baseline_geoms[self._current_idx]
        # Use per-profile strip width if available, otherwise fall back to spinbox
        if self._strip_widths and self._current_idx < len(self._strip_widths):
            swath_width = self._strip_widths[self._current_idx]
        elif self.plugin.param_dock:
            swath_width = self.plugin.param_dock.width_spin.value()
        if self.plugin.param_dock:
            dem_layer = self.plugin.param_dock.dem_combo.currentLayer()
            if dem_layer:
                dem_crs = dem_layer.crs()
        scan_settings = {
            "scan_color": settings.get("scan_color", "#80cc28"),
            "scan_width": settings.get("scan_width", 1.0),
        }
        self.canvas.set_profile_data(sp, baseline_geom, swath_width, scan_settings,
                                     dem_crs, proj_crs)
        self.canvas.draw()

        # Update points count label
        n_pts = len(sp.distances) if sp.distances is not None else 0
        n_lines = sp.n_profiles if sp.n_profiles else 0
        self.points_label.setText(tr(f"节点数：{n_pts} × {n_lines}", f"Points: {n_pts} × {n_lines}"))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self):
        """Open settings dialog."""
        from .swath_settings import SwathSettingsDialog
        dlg = SwathSettingsDialog(self)
        if self._settings:
            dlg.set_settings(self._settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._settings = dlg.get_settings()
            self.btn_smooth.setChecked(self._settings.get("smooth_enabled", False))
            self._update_smooth_menu_checks()
            self._update_swatches()
            self._redraw()
            # Refresh swath band on map with new settings
            if self.plugin.param_dock:
                self.plugin.param_dock._show_selected_band(self._current_idx)

    def _toggle_smooth(self, checked):
        """Toggle smooth profile display and redraw."""
        settings = self.get_settings()
        settings["smooth_enabled"] = checked
        # Ensure button checked state is in sync
        if self.btn_smooth.isChecked() != checked:
            self.btn_smooth.blockSignals(True)
            self.btn_smooth.setChecked(checked)
            self.btn_smooth.blockSignals(False)
        self._redraw()

    def _set_smooth_intensity(self, window_size):
        """Set custom smoothing window size and trigger redraw."""
        settings = self.get_settings()
        settings["smooth_window"] = window_size
        settings["smooth_enabled"] = True
        self.btn_smooth.setChecked(True)
        self._update_smooth_menu_checks()
        self._redraw()

    def _update_smooth_menu_checks(self):
        """Update checkmarks next to smoothing menu options."""
        settings = self.get_settings()
        current_size = settings.get("smooth_window", 9)
        for size, act in self._smooth_actions.items():
            act.blockSignals(True)
            act.setChecked(size == current_size)
            act.blockSignals(False)

    def _set_y_label(self):
        """Prompt user to change the custom Y-axis label."""
        from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit
        settings = self.get_settings()
        current_label = settings.get("custom_y_label", "")
        title = tr("设置纵坐标名称", "Set Y-Axis Label")
        prompt = tr("请输入纵坐标（Y轴）名称：\n(留空则默认使用当前主视图的栅格图层名称)", 
                    "Enter Y-axis label:\n(Leave empty to use active raster layer name by default)")
        
        text, ok = QInputDialog.getText(self, title, prompt, QLineEdit.EchoMode.Normal, current_label)
        if ok:
            settings["custom_y_label"] = text.strip()
            self._redraw()

    def _update_swatches(self):
        """Update checkbox swatch colors from current settings."""
        if not self._settings:
            return
        for key, swatch in self._swatches.items():
            color = self._settings.get(key, "#999999")
            swatch.setStyleSheet(f"background:{color}; border:1px solid #999; border-radius:2px;")

    def get_settings(self):
        """Return current display settings."""
        if self._settings is None:
            from .swath_settings import SwathSettingsDialog
            self._settings = dict(SwathSettingsDialog.DEFAULTS)
            self.btn_smooth.setChecked(self._settings.get("smooth_enabled", False))
            self._update_smooth_menu_checks()
        return self._settings

    # ------------------------------------------------------------------
    # Reset view
    # ------------------------------------------------------------------

    def _reset_view(self):
        self._redraw(fit_view=True)

    # ------------------------------------------------------------------
    # Clear swath bands
    # ------------------------------------------------------------------

    def _clear_swath_bands(self):
        """Clear swath band display from map."""
        if self.plugin.param_dock:
            self.plugin.param_dock._clear_swath_bands()

    # ------------------------------------------------------------------
    # Pick line from map
    # ------------------------------------------------------------------

    def _pick_line_from_map(self):
        """Activate map tool to pick a line feature for profile generation."""
        from qgis.gui import QgsMapToolIdentifyFeature
        from qgis.core import QgsMapLayerType

        # Get current line layer from param dock
        if not self.plugin.param_dock:
            return
        
        line_layer = self.plugin.param_dock.line_combo.currentLayer()
        if not line_layer or line_layer.type() != QgsMapLayerType.VectorLayer:
            return

        canvas = self.plugin.iface.mapCanvas()
        
        # Create identify tool for the line layer
        tool = QgsMapToolIdentifyFeature(canvas, line_layer)
        tool.featureIdentified.connect(self._on_line_picked)
        tool.setLayer(line_layer)
        
        # Store reference to restore later
        self._pick_tool = tool
        self._prev_tool = canvas.mapTool()
        canvas.setMapTool(tool)

    def _on_line_picked(self, feature):
        """Handle line feature picked from map."""
        if not feature or not feature.geometry():
            return

        # Restore previous tool
        if self._prev_tool:
            self.plugin.iface.mapCanvas().setMapTool(self._prev_tool)
            self._prev_tool = None

        # Process the picked line
        if self.plugin.param_dock:
            self.plugin.param_dock._process_single_line(feature)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _show_native_success_message(self, path=None, file_type_name="", warning_text=""):
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
        display_path = os.path.normpath(path) if path else ""
        msg_text = tr(
            f"<b>{file_type_name} 导出成功！</b> 已将成果保存至：<u>{display_path}</u>",
            f"<b>{file_type_name} Exported Successfully!</b> Saved to: <u>{display_path}</u>"
        )
        if warning_text:
            msg_text += "<br/>" + warning_text
            
        label = QLabel(msg_text)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)

        if path:
            # Show in Folder Button
            btn = QPushButton(tr("在文件夹中显示", "Show in Folder"))
            
            # Cross-platform select file in explorer
            def open_folder():
                import sys
                import shutil
                import subprocess
                try:
                    abs_path = os.path.abspath(path)
                    if not os.path.exists(abs_path):
                        return
                    if sys.platform.startswith('win'):
                        explorer = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'explorer.exe')
                        if os.path.exists(explorer):
                            subprocess.run([explorer, '/select,', os.path.normpath(abs_path)], check=False)  # nosec B603
                        else:
                            subprocess.run(['explorer', '/select,', os.path.normpath(abs_path)], check=False)  # nosec B607 B603
                    elif sys.platform == 'darwin':
                        open_cmd = shutil.which('open') or '/usr/bin/open'
                        subprocess.run([open_cmd, '-R', abs_path], check=False)  # nosec B603
                    else:
                        xdg_open = shutil.which('xdg-open') or '/usr/bin/xdg-open'
                        dir_path = os.path.dirname(abs_path)
                        subprocess.run([xdg_open, dir_path], check=False)  # nosec B603
                except Exception as e:
                    print(f"Error opening folder: {e}")

            btn.clicked.connect(open_folder)
            layout.addWidget(btn)

        # Push to QGIS native message bar
        message_bar.pushWidget(widget, Qgis.MessageLevel.Success, 7)

    def _save_image(self, fmt="png", scope="view"):
        """Export chart as PNG, PDF, or SVG."""
        filters = {
            "png": ("PNG (*.png)", "swath_profile.png"),
            "pdf": ("PDF (*.pdf)", "swath_profile.pdf"),
            "svg": ("SVG (*.svg)", "swath_profile.svg"),
        }
        file_filter, default_name = filters.get(fmt, filters["png"])
        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出图像", "Export chart"), default_name, file_filter
        )
        if path:
            if scope == "view":
                # Export current view
                self.figure.savefig(path, dpi=300, bbox_inches="tight")
            else:
                # Export full extent - temporarily reset view
                for ax in self.figure.get_axes():
                    ax.autoscale()
                self.figure.savefig(path, dpi=300, bbox_inches="tight")
                # Restore previous view
                self._redraw(fit_view=False)
            self._show_native_success_message(path, tr("剖面图表", "Profile Chart"))

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出 CSV", "Export CSV"), "swath_profile.csv",
            "CSV (*.csv);;Text (*.txt)"
        )
        if not path:
            return

        sp = self._profiles[self._current_idx]
        settings = self.get_settings()
        if settings.get("smooth_enabled", False):
            sp = sp.smoothed(settings.get("smooth_window", 9))
        delimiter = ";" if path.lower().endswith(".txt") else ","

        with open(path, "w", newline="", encoding="utf-8") as fh:
            fh.write(f"{sp.name}\n")
            writer = csv.writer(fh, delimiter=delimiter)

            # Header
            header = ["X"]
            for i in range(sp.n_profiles):
                header.append(f"Y{i+1}")
            header.extend(["Min", "Max", "Mean", "Q1", "Q3", "Relief", "HI"])
            if self._mode == "offset":
                thi = sp.compute_thi(enhanced=self.chk_enhanced.isChecked())
                header.append("THi")
            else:
                thi = None
            writer.writerow(header)

            # Data rows
            for j in range(len(sp.distances)):
                row = [f"{sp.distances[j]:.4f}"]
                for p in sp.profile_data:
                    row.append(f"{p[j]:.4f}" if j < len(p) else "")
                row.append(f"{sp.min_profile[j]:.4f}")
                row.append(f"{sp.max_profile[j]:.4f}")
                row.append(f"{sp.mean_profile[j]:.4f}")
                if sp.q1_profile is not None:
                    row.append(f"{sp.q1_profile[j]:.4f}")
                    row.append(f"{sp.q3_profile[j]:.4f}")
                else:
                    row.extend(["", ""])
                row.append(f"{sp.relief_profile[j]:.4f}")
                row.append(f"{sp.hi_profile[j]:.4f}")
                if thi is not None:
                    row.append(f"{thi[j]:.4f}")
                writer.writerow(row)
        self._show_native_success_message(path, "CSV")

    def _export_cad_2d(self):
        if not self._profiles:
            return
        
        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出 2D CAD", "Export 2D CAD"), "swath_profile_2d.dxf",
            "AutoCAD DXF (*.dxf);;AutoCAD DWG (*.dwg)"
        )
        if not path:
            return

        is_dwg = path.lower().endswith(".dwg")
        if is_dwg:
            path = path[:-4] + ".dxf"

        # AutoCAD version selection
        versions = [
            "AutoCAD 2018 (AC1032)",
            "AutoCAD 2013 (AC1027)",
            "AutoCAD 2010 (AC1024)",
            "AutoCAD 2007 (AC1021)",
            "AutoCAD 2004 (AC1018)",
            "AutoCAD 2000 (AC1015)",
            "AutoCAD R12 (AC1009)"
        ]
        default_version = "AutoCAD 2000 (AC1015)"
        
        version_str, ok = QInputDialog.getItem(
            self, tr("选择 CAD 版本", "Select CAD Version"),
            tr("请选择导出的 AutoCAD 文件版本：", "Please select the AutoCAD file version to export:"),
            versions, versions.index(default_version), False
        )
        if not ok or not version_str:
            return

        version_code = "AC1015"
        if "(" in version_str and ")" in version_str:
            version_code = version_str.split("(")[-1].replace(")", "").strip()

        from qgis.PyQt.QtWidgets import QMessageBox

        sp = self._profiles[self._current_idx]
        settings = self.get_settings()
        if settings.get("smooth_enabled", False):
            sp = sp.smoothed(settings.get("smooth_window", 9))

        # Get nice ticks and layout
        y_min = float(np.nanmin([np.nanmin(p) for p in sp.profile_data] + [np.nanmin(sp.mean_profile)]))
        y_max = float(np.nanmax([np.nanmax(p) for p in sp.profile_data] + [np.nanmax(sp.mean_profile)]))
        if math.isnan(y_min) or math.isinf(y_min):
            y_min = 0.0
        if math.isnan(y_max) or math.isinf(y_max):
            y_max = 100.0

        x_max = float(sp.distances[-1])
        if x_max <= 0:
            x_max = 1.0

        x_ticks, _ = get_nice_ticks(0.0, x_max, target_count=8)
        y_ticks, _ = get_nice_ticks(y_min, y_max, target_count=6)

        x_span = x_max
        y_span = y_ticks[-1] - y_ticks[0] if len(y_ticks) > 1 else 1.0
        if y_span <= 0:
            y_span = 1.0

        dxf = DXFBuilder(version=version_code)
        
        # Add layers
        dxf.add_layer("Grid", color=8)          # Gray
        dxf.add_layer("Axes", color=7)          # White/Black
        dxf.add_layer("Text_Labels", color=7)   # White/Black
        dxf.add_layer("Profile_Mean", color=1)  # Red
        dxf.add_layer("Profile_Min", color=5)   # Blue
        dxf.add_layer("Profile_Max", color=3)   # Green
        dxf.add_layer("Profile_Q1", color=4)    # Cyan
        dxf.add_layer("Profile_Q3", color=6)    # Magenta
        dxf.add_layer("Profile_Individual", color=9) # Light Gray

        # 1. Draw Gridlines and Axes
        y_bottom = y_ticks[0]
        y_top = y_ticks[-1]
        
        # Horizontal lines and ticks
        for yt in y_ticks:
            dxf.add_line((0.0, yt), (x_max, yt), layer="Grid")
            dxf.add_text(f"{yt:.1f}", (-0.015 * x_span, yt - 0.005 * y_span), height=0.018 * y_span, layer="Text_Labels", halign=2)

        # Vertical lines and ticks
        for xt in x_ticks:
            dxf.add_line((xt, y_bottom), (xt, y_top), layer="Grid")
            dxf.add_text(f"{xt:.0f}", (xt, y_bottom - 0.03 * y_span), height=0.018 * y_span, layer="Text_Labels", halign=1)

        # Main Axes
        dxf.add_line((0.0, y_bottom), (x_max, y_bottom), layer="Axes")
        dxf.add_line((0.0, y_bottom), (0.0, y_top), layer="Axes")
        dxf.add_line((x_max, y_bottom), (x_max, y_top), layer="Axes")
        dxf.add_line((0.0, y_top), (x_max, y_top), layer="Axes")

        # Titles/Labels
        dxf.add_text("Distance (m)", (x_max / 2.0, y_bottom - 0.07 * y_span), height=0.022 * y_span, layer="Text_Labels", halign=1)
        
        y_title_text = tr("高程", "Elevation")
        custom_y_label = settings.get("custom_y_label", "").strip()
        if custom_y_label:
            y_title_text = custom_y_label
        elif self.plugin.param_dock:
            dem_layer = self.plugin.param_dock.dem_combo.currentLayer()
            if dem_layer:
                y_title_text = dem_layer.name()
        dxf.add_text(y_title_text, (-0.08 * x_span, (y_bottom + y_top) / 2.0), height=0.022 * y_span, rotation=90.0, layer="Text_Labels", halign=1)

        # 2. Draw Curves
        if self.chk_profiles.isChecked():
            for idx, p_data in enumerate(sp.profile_data):
                pts = []
                for j in range(len(sp.distances)):
                    val = p_data[j]
                    if not math.isnan(val):
                        pts.append((sp.distances[j], val))
                if len(pts) > 1:
                    dxf.add_lwpolyline(pts, layer="Profile_Individual")

        if self.chk_min.isChecked() and sp.min_profile is not None:
            pts = [(sp.distances[j], sp.min_profile[j]) for j in range(len(sp.distances)) if not math.isnan(sp.min_profile[j])]
            if len(pts) > 1:
                dxf.add_lwpolyline(pts, layer="Profile_Min")

        if self.chk_max.isChecked() and sp.max_profile is not None:
            pts = [(sp.distances[j], sp.max_profile[j]) for j in range(len(sp.distances)) if not math.isnan(sp.max_profile[j])]
            if len(pts) > 1:
                dxf.add_lwpolyline(pts, layer="Profile_Max")

        if self.chk_q1.isChecked() and sp.q1_profile is not None:
            pts = [(sp.distances[j], sp.q1_profile[j]) for j in range(len(sp.distances)) if not math.isnan(sp.q1_profile[j])]
            if len(pts) > 1:
                dxf.add_lwpolyline(pts, layer="Profile_Q1")

        if self.chk_q3.isChecked() and sp.q3_profile is not None:
            pts = [(sp.distances[j], sp.q3_profile[j]) for j in range(len(sp.distances)) if not math.isnan(sp.q3_profile[j])]
            if len(pts) > 1:
                dxf.add_lwpolyline(pts, layer="Profile_Q3")

        if self.chk_mean.isChecked() and sp.mean_profile is not None:
            pts = [(sp.distances[j], sp.mean_profile[j]) for j in range(len(sp.distances)) if not math.isnan(sp.mean_profile[j])]
            if len(pts) > 1:
                dxf.add_lwpolyline(pts, layer="Profile_Mean")

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(dxf.to_string())
            
            warning_text = ""
            if is_dwg:
                warning_text = tr(
                    "提示：由于 DWG 是私有二进制格式，已导出为通用无损的 DXF 文件。您可用 AutoCAD 直接打开此 DXF，并在软件内一键另存为 DWG 格式。",
                    "Note: As DWG is a proprietary binary format, a universal lossless DXF file has been exported. You can open this DXF in AutoCAD and save it as DWG with one click."
                )
            self._show_native_success_message(path, "2D CAD", warning_text)
        except Exception as e:
            QMessageBox.critical(self, tr("导出失败", "Export Error"), tr(f"写入 CAD 文件时出错：\n{str(e)}", f"Error writing CAD file:\n{str(e)}"))

    def _export_cad_3d(self):
        if not self._profiles:
            return
        
        if not self._baseline_geoms or self._current_idx >= len(self._baseline_geoms):
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("导出失败", "Export Error"), tr("未找到基线几何数据，无法导出 3D CAD。", "No baseline geometry found, cannot export 3D CAD."))
            return

        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出 3D CAD", "Export 3D CAD"), "swath_profile_3d.dxf",
            "AutoCAD DXF (*.dxf);;AutoCAD DWG (*.dwg)"
        )
        if not path:
            return

        is_dwg = path.lower().endswith(".dwg")
        if is_dwg:
            path = path[:-4] + ".dxf"

        # AutoCAD version selection
        versions = [
            "AutoCAD 2018 (AC1032)",
            "AutoCAD 2013 (AC1027)",
            "AutoCAD 2010 (AC1024)",
            "AutoCAD 2007 (AC1021)",
            "AutoCAD 2004 (AC1018)",
            "AutoCAD 2000 (AC1015)",
            "AutoCAD R12 (AC1009)"
        ]
        default_version = "AutoCAD 2000 (AC1015)"
        
        version_str, ok = QInputDialog.getItem(
            self, tr("选择 CAD 版本", "Select CAD Version"),
            tr("请选择导出的 AutoCAD 文件版本：", "Please select the AutoCAD file version to export:"),
            versions, versions.index(default_version), False
        )
        if not ok or not version_str:
            return

        version_code = "AC1015"
        if "(" in version_str and ")" in version_str:
            version_code = version_str.split("(")[-1].replace(")", "").strip()

        from qgis.PyQt.QtWidgets import QMessageBox
        from .swath_core import generate_offset_lines, _interpolate_polyline

        sp = self._profiles[self._current_idx]
        settings = self.get_settings()
        if settings.get("smooth_enabled", False):
            sp = sp.smoothed(settings.get("smooth_window", 9))

        baseline_geom = self._baseline_geoms[self._current_idx]
        strip_width = self._strip_widths[self._current_idx] if self._current_idx < len(self._strip_widths) else 100.0

        dxf = DXFBuilder(version=version_code)
        
        # Add layers
        dxf.add_layer("3D_Baseline_Mean", color=1)  # Red
        dxf.add_layer("3D_Baseline_Min", color=5)   # Blue
        dxf.add_layer("3D_Baseline_Max", color=3)   # Green
        dxf.add_layer("3D_Baseline_Q1", color=4)    # Cyan
        dxf.add_layer("3D_Baseline_Q3", color=6)    # Magenta
        dxf.add_layer("3D_Offset_Lines", color=9)   # Light Gray

        # Reconstruct XY coords for baseline
        xy_base = _interpolate_polyline(baseline_geom, sp.distances)

        # 1. Export baseline statistic curves
        if sp.mean_profile is not None:
            pts = [(xy_base[j, 0], xy_base[j, 1], sp.mean_profile[j]) for j in range(len(sp.distances)) if not math.isnan(sp.mean_profile[j])]
            if len(pts) > 1:
                dxf.add_polyline3d(pts, layer="3D_Baseline_Mean")

        if sp.min_profile is not None:
            pts = [(xy_base[j, 0], xy_base[j, 1], sp.min_profile[j]) for j in range(len(sp.distances)) if not math.isnan(sp.min_profile[j])]
            if len(pts) > 1:
                dxf.add_polyline3d(pts, layer="3D_Baseline_Min")

        if sp.max_profile is not None:
            pts = [(xy_base[j, 0], xy_base[j, 1], sp.max_profile[j]) for j in range(len(sp.distances)) if not math.isnan(sp.max_profile[j])]
            if len(pts) > 1:
                dxf.add_polyline3d(pts, layer="3D_Baseline_Max")

        if sp.q1_profile is not None:
            pts = [(xy_base[j, 0], xy_base[j, 1], sp.q1_profile[j]) for j in range(len(sp.distances)) if not math.isnan(sp.q1_profile[j])]
            if len(pts) > 1:
                dxf.add_polyline3d(pts, layer="3D_Baseline_Q1")

        if sp.q3_profile is not None:
            pts = [(xy_base[j, 0], xy_base[j, 1], sp.q3_profile[j]) for j in range(len(sp.distances)) if not math.isnan(sp.q3_profile[j])]
            if len(pts) > 1:
                dxf.add_polyline3d(pts, layer="3D_Baseline_Q3")

        # 2. Export individual offset lines if offset mode
        if self._mode == "offset" and sp.n_profiles > 1:
            try:
                offset_geoms = generate_offset_lines(baseline_geom, strip_width, sp.n_profiles)
                for idx, geom in enumerate(offset_geoms):
                    if idx >= len(sp.profile_data):
                        break
                    p_data = sp.profile_data[idx]
                    xy_offset = _interpolate_polyline(geom, sp.distances)
                    pts = [(xy_offset[j, 0], xy_offset[j, 1], p_data[j]) for j in range(len(sp.distances)) if not math.isnan(p_data[j])]
                    if len(pts) > 1:
                        dxf.add_polyline3d(pts, layer="3D_Offset_Lines")
            except Exception as e:
                print(f"Error generating offset lines for 3D CAD: {e}")

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(dxf.to_string())
            
            warning_text = ""
            if is_dwg:
                warning_text = tr(
                    "提示：由于 DWG 是私有二进制格式，已导出为通用无损的 DXF 文件。您可用 AutoCAD 直接打开此 DXF，并在软件内一键另存为 DWG 格式。",
                    "Note: As DWG is a proprietary binary format, a universal lossless DXF file has been exported. You can open this DXF in AutoCAD and save it as DWG with one click."
                )
            self._show_native_success_message(path, "3D CAD", warning_text)
        except Exception as e:
            QMessageBox.critical(self, tr("导出失败", "Export Error"), tr(f"写入 CAD 文件时出错：\n{str(e)}", f"Error writing CAD file:\n{str(e)}"))

    def _open_gis_export_dialog(self):
        if not self._profiles:
            return

        if not self._baseline_geoms:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("导出失败", "Export Error"), tr("未找到基线几何数据，无法导出 GIS 数据。", "No baseline geometry found, cannot export GIS data."))
            return
            
        from .swath_gis_export_dialog import SwathGisExportDialog
        from qgis.core import QgsProject
        
        crs = QgsProject.instance().crs()
        if self.plugin and self.plugin.param_dock:
            dem_layer = self.plugin.param_dock.dem_combo.currentLayer()
            if dem_layer:
                crs = dem_layer.crs()
                
        dlg = SwathGisExportDialog(self, crs)
        if dlg.exec():
            params = dlg.get_export_params()
            self._export_gis_core(params)

    def _export_gis_core(self, params):
        path = params.get("filepath")
        if not path:
            return

        from qgis.core import (QgsVectorLayer, QgsPoint, QgsLineString, QgsGeometry,
                               QgsFeature, QgsField, QgsVectorFileWriter, QgsProject)
        from qgis.PyQt.QtCore import QVariant
        from .swath_core import generate_offset_lines, _interpolate_polyline
        import math

        is_baseline_projection = params.get("is_baseline", False)
        is_point = params.get("is_point", False)
        format_data = params.get("format", "GPKG")
        layer_name = params.get("layer_name", "Profile3D")
        crs = params.get("crs")
        add_to_map = params.get("add_to_map", True)

        crs_authid = crs.authid() if crs and crs.isValid() else QgsProject.instance().crs().authid()
        geom_type = "PointZ" if is_point else "LineStringZ"
        
        layer = QgsVectorLayer(f"{geom_type}?crs={crs_authid}", "Profile3D", "memory")
        pr = layer.dataProvider()
        
        # Add attributes
        attrs = [
            QgsField("S-type", QVariant.String),
            QgsField("S-level", QVariant.Int)
        ]
        if is_point:
            attrs.append(QgsField("Distance", QVariant.Double))
            
        # Add original fields, skipping reserved primary keys like 'fid'
        skip_fields = {'fid', 'id', 'ogc_fid'}
        for field_name in self._fields:
            if field_name.lower() not in skip_fields:
                attrs.append(QgsField(field_name, QVariant.String))
            
        pr.addAttributes(attrs)
        layer.updateFields()

        layer.startEditing()
        
        smooth_window = params.get("smooth_window", 0)
        smooth_enabled = (smooth_window > 0)

        # Loop over ALL profiles/baselines
        for idx, (sp_raw, baseline_geom) in enumerate(zip(self._profiles, self._baseline_geoms)):
            sp = sp_raw.smoothed(smooth_window) if smooth_enabled else sp_raw
            strip_width = self._strip_widths[idx] if idx < len(self._strip_widths) else 100.0
            
            # Original feature attributes
            orig_attrs = {}
            for i, field_name in enumerate(self._fields):
                if field_name.lower() not in skip_fields:
                    if i < len(self._field_values) and idx < len(self._field_values[i]):
                        orig_attrs[field_name] = self._field_values[i][idx]

            xy_base = _interpolate_polyline(baseline_geom, sp.distances)

            # Calculate downsampling step to reduce nodes and speed up loading
            step = 1
            if smooth_window >= 25:
                step = 10
            elif smooth_window >= 15:
                step = 5
            elif smooth_window >= 9:
                step = 3
            elif smooth_window >= 5:
                step = 2
                
            indices = list(range(0, len(sp.distances), step))
            if indices and indices[-1] != len(sp.distances) - 1:
                indices.append(len(sp.distances) - 1)

            def add_feature_data(pts_array, z_array, type_str, level_int):
                if is_point:
                    for j in indices:
                        val = z_array[j]
                        x_val = pts_array[j, 0]
                        y_val = pts_array[j, 1]
                        if not (math.isnan(val) or math.isinf(val) or abs(val) > 1e10 or
                                math.isnan(x_val) or math.isinf(x_val) or 
                                math.isnan(y_val) or math.isinf(y_val)):
                            feat = QgsFeature(layer.fields())
                            pt = QgsPoint(float(x_val), float(y_val), float(val))
                            feat.setGeometry(QgsGeometry(pt))
                            feat.setAttribute("S-type", type_str)
                            feat.setAttribute("S-level", level_int)
                            feat.setAttribute("Distance", float(sp.distances[j]))
                            for k, v in orig_attrs.items():
                                feat.setAttribute(k, v)
                            pr.addFeature(feat)
                else:
                    line = QgsLineString()
                    added = False
                    for j in indices:
                        val = z_array[j]
                        x_val = pts_array[j, 0]
                        y_val = pts_array[j, 1]
                        if not (math.isnan(val) or math.isinf(val) or abs(val) > 1e10 or
                                math.isnan(x_val) or math.isinf(x_val) or 
                                math.isnan(y_val) or math.isinf(y_val)):
                            line.addVertex(QgsPoint(float(x_val), float(y_val), float(val)))
                            added = True
                    if added and line.numPoints() > 1:
                        feat = QgsFeature(layer.fields())
                        feat.setGeometry(QgsGeometry(line))
                        feat.setAttribute("S-type", type_str)
                        feat.setAttribute("S-level", level_int)
                        for k, v in orig_attrs.items():
                            feat.setAttribute(k, v)
                        pr.addFeature(feat)

            # 1. Export 5 characteristic lines (Level = 1)
            if sp.mean_profile is not None: add_feature_data(xy_base, sp.mean_profile, "Mean", 1)
            if sp.min_profile is not None: add_feature_data(xy_base, sp.min_profile, "Min", 1)
            if sp.max_profile is not None: add_feature_data(xy_base, sp.max_profile, "Max", 1)
            if sp.q1_profile is not None: add_feature_data(xy_base, sp.q1_profile, "Q1", 1)
            if sp.q3_profile is not None: add_feature_data(xy_base, sp.q3_profile, "Q3", 1)

            # 2. Export individual offset lines (Level = 0)
            if self._mode == "offset" and sp.n_profiles > 1:
                try:
                    offset_geoms = generate_offset_lines(baseline_geom, strip_width, sp.n_profiles)
                    for i_off, geom in enumerate(offset_geoms):
                        if i_off >= len(sp.profile_data):
                            break
                        p_data = sp.profile_data[i_off]
                        
                        if is_baseline_projection:
                            xy_coords = xy_base
                        else:
                            xy_coords = _interpolate_polyline(geom, sp.distances)
                            
                        add_feature_data(xy_coords, p_data, "Offset", 0)
                except Exception as e:
                    print(f"Error generating offset lines for GIS export: {e}")

        layer.commitChanges()

        # Save to file
        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.driverName = format_data
        if format_data in ("GPKG", "OpenFileGDB"):
            save_options.layerName = layer_name

        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            path,
            QgsProject.instance().transformContext(),
            save_options
        )
        
        # Result is a tuple (error_code, error_msg, ...)
        error_code = result[0]
        error_msg = result[1] if len(result) > 1 else ""

        if error_code == QgsVectorFileWriter.WriterError.NoError:
            self._show_native_success_message(path, "GIS 矢量数据")
            
            # Load into map if checked
            if add_to_map:
                try:
                    if format_data in ("GPKG", "OpenFileGDB"):
                        uri = f"{path}|layername={layer_name}"
                        vlayer = QgsVectorLayer(uri, layer_name, "ogr")
                    else:
                        import os
                        layer_name_fallback = os.path.splitext(os.path.basename(path))[0]
                        vlayer = QgsVectorLayer(path, layer_name_fallback, "ogr")
                        
                    if vlayer.isValid():
                        QgsProject.instance().addMapLayer(vlayer)
                except Exception as e:
                    print(f"Failed to load exported layer: {e}")
        else:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(self, tr("导出失败", "Export Error"),
                                 tr(f"写入文件失败：\n{error_msg}", f"Failed to write file:\n{error_msg}"))
    def resizeEvent(self, event):
        """Auto-fit chart when dock is resized."""
        super().resizeEvent(event)
        if self._profiles:
            self.canvas.draw_idle()

    def closeEvent(self, event):
        self.canvas._remove_map_marker()
        super().closeEvent(event)


# ======================================================================
# Help content (shared)
# ======================================================================

HELP_HTML_ZH = """
<h3 style="margin-top:0">横截面剖面</h3>

<h4>采样模式</h4>
<p><b>偏移线采样</b> — 沿基线生成平行偏移线，逐点采样 DEM。
输出连续曲线，支持完整统计分析（min/max/mean/Q1/Q3/HI/THi）。</p>
<p><b>矩形切片统计</b> — 沿基线生成垂直矩形切片，用区域统计计算
每个切片内的 DEM 统计值（min/max/mean/median/std）。</p>

<h4>参数说明</h4>
<table cellpadding="4" cellspacing="0">
<tr><td><b>条带宽度</b></td><td>剖面总宽度（地图单位）</td></tr>
<tr><td><b>步长</b></td><td>采样间距，0 = 自动（1.5× 像元大小）</td></tr>
<tr><td><b>剖面数</b></td><td>平行偏移线总数（默认 50）</td></tr>
<tr><td><b>采样间距</b></td><td>矩形切片中心间距（仅切片模式）</td></tr>
</table>

<h4>交互操作</h4>
<table cellpadding="4" cellspacing="0">
<tr><td><b>滚轮</b></td><td>缩放（以光标为中心）</td></tr>
<tr><td><b>中键拖动</b></td><td>平移视图</td></tr>
<tr><td><b>左键框选</b></td><td>放大到选区</td></tr>
<tr><td><b>右键上下</b></td><td>缩放 Y 轴</td></tr>
<tr><td><b>右键左右</b></td><td>缩放 X 轴</td></tr>
<tr><td><b>悬停</b></td><td>在地图上定位对应点</td></tr>
</table>

<h4>统计量</h4>
<table cellpadding="4" cellspacing="0">
<tr><td><b>Min / Max</b></td><td>所有偏移线的最小/最大高程</td></tr>
<tr><td><b>Mean</b></td><td>平均高程</td></tr>
<tr><td><b>Q1 / Q3</b></td><td>第 25/75 百分位数</td></tr>
<tr><td><b>Relief</b></td><td>局部起伏 = Max - Min</td></tr>
<tr><td><b>HI</b></td><td>地形起伏指数 = (Mean-Min)/(Max-Min)</td></tr>
</table>

<h4>THi 指数</h4>
<p><b>THi</b>（Transverse Hypsometric Integral）：</p>
<p style="font-family:monospace; background:#f0f0f0; padding:6px;">
THi = ((HI - 0.5) × factor + 0.5) × 100<br>
factor = 0.2 × ln(Relief / MaxRelief) + 1
</p>
<p><b>THi*</b>（增强模式）：先将 HI 从 [0.2, 0.8] 重缩放到 [0, 1]。</p>
<p>THi ≈ 50 表示地形均衡；> 50 凸起/山脊；< 50 凹陷/山谷。</p>

<h4>参考文献</h4>
<p style="font-size:11px; color:#555;">
Pérez-Peña et al. (2017). SwathProfiler and NProfiler.
<i>Computers & Geosciences</i>, 104, 150.
</p>
"""

HELP_HTML_EN = """
<h3 style="margin-top:0">Swath Profile</h3>

<h4>Sampling Modes</h4>
<p><b>Offset-line</b> — generates parallel offset lines along the baseline,
samples the DEM at each point. Produces continuous curves with full
statistics (min/max/mean/Q1/Q3/HI/THi).</p>
<p><b>Zonal statistics</b> — creates perpendicular rectangular slices along
the baseline, computes area-based DEM statistics per slice
(min/max/mean/median/std).</p>

<h4>Parameters</h4>
<table cellpadding="4" cellspacing="0">
<tr><td><b>Strip width</b></td><td>total swath width (map units)</td></tr>
<tr><td><b>Step size</b></td><td>sampling interval; 0 = auto (1.5× cell size)</td></tr>
<tr><td><b>Number of profiles</b></td><td>total parallel offset lines (default 50)</td></tr>
<tr><td><b>Sample interval</b></td><td>slice centre spacing (zonal mode only)</td></tr>
</table>

<h4>Interactions</h4>
<table cellpadding="4" cellspacing="0">
<tr><td><b>Scroll</b></td><td>Zoom centered on cursor</td></tr>
<tr><td><b>Middle drag</b></td><td>Pan view</td></tr>
<tr><td><b>Left drag</b></td><td>Zoom to selection</td></tr>
<tr><td><b>Right up/down</b></td><td>Scale Y axis</td></tr>
<tr><td><b>Right left/right</b></td><td>Scale X axis</td></tr>
<tr><td><b>Hover</b></td><td>Locate point on map</td></tr>
</table>

<h4>Statistics</h4>
<table cellpadding="4" cellspacing="0">
<tr><td><b>Min / Max</b></td><td>min/max elevation across all offset lines</td></tr>
<tr><td><b>Mean</b></td><td>mean elevation</td></tr>
<tr><td><b>Q1 / Q3</b></td><td>25th / 75th percentile</td></tr>
<tr><td><b>Relief</b></td><td>local relief = Max - Min</td></tr>
<tr><td><b>HI</b></td><td>Hypsometric Integral = (Mean-Min)/(Max-Min)</td></tr>
</table>

<h4>THi Index</h4>
<p><b>THi</b> (Transverse Hypsometric Integral):</p>
<p style="font-family:monospace; background:#f0f0f0; padding:6px;">
THi = ((HI - 0.5) × factor + 0.5) × 100<br>
factor = 0.2 × ln(Relief / MaxRelief) + 1
</p>
<p><b>THi*</b> (enhanced): rescales HI from [0.2, 0.8] to [0, 1] first.</p>
<p>THi ≈ 50 → balanced terrain; > 50 → convex/ridge; < 50 → concave/valley.</p>

<h4>Reference</h4>
<p style="font-size:11px; color:#555;">
Pérez-Peña et al. (2017). SwathProfiler and NProfiler.
<i>Computers & Geosciences</i>, 104, 150.
</p>
"""
