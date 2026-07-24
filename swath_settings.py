# -*- coding: utf-8 -*-
"""
Settings dialog for swath profile display options.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QColorDialog, QDoubleSpinBox,
    QGroupBox, QTabWidget, QWidget, QSizePolicy,
    QSpinBox, QCheckBox, QLineEdit,
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import Qt, pyqtSignal
from .i18n import tr


def _color_btn(initial_color, callback):
    """Create a color picker button."""
    btn = QPushButton()
    btn.setFixedSize(28, 28)
    btn.setStyleSheet(f"background:{initial_color}; border:1px solid #999; border-radius:3px;")
    btn.setProperty("color", initial_color)
    btn.clicked.connect(lambda: _pick_color(btn, callback))
    return btn


def _pick_color(btn, callback):
    """Open color dialog and update button."""
    current = QColor(btn.property("color"))
    color = QColorDialog.getColor(current, None, tr("选择颜色", "Select Color"))
    if color.isValid():
        hex_color = color.name()
        btn.setStyleSheet(f"background:{hex_color}; border:1px solid #999; border-radius:3px;")
        btn.setProperty("color", hex_color)
        callback(hex_color)


class SwathSettingsDialog(QDialog):
    """Dialog for configuring swath profile display settings."""

    settings_changed = pyqtSignal(dict)

    # Default colors and widths (mm)
    DEFAULTS = {
        "color_profiles": "#C8C8C8",
        "width_profiles": 0.2,
        "color_min": "#4dd48a",
        "width_min": 0.5,
        "color_max": "#f8ba81",
        "width_max": 0.5,
        "color_mean": "#01008a",
        "width_mean": 0.6,
        "color_q1": "#008a8c",
        "width_q1": 0.5,
        "color_q3": "#008a8c",
        "width_q3": 0.5,
        "color_relief": "#cc3333",
        "width_relief": 0.4,
        "color_thi": "#8B4513",
        "width_thi": 0.4,
        "band_fill_color": "#d64646",
        "band_fill_opacity": 20,
        "band_stroke_color": "#d64646",
        "band_stroke_width": 0.2,
        "band_stroke_opacity": 70,
        "scan_color": "#80cc28",
        "scan_width": 1.0,
        "smooth_enabled": False,
        "smooth_window": 9,
        "custom_y_label": "",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("剖面设置", "Swath Settings"))
        self.setMinimumWidth(320)
        self._settings = dict(self.DEFAULTS)
        self._color_btns = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_line_tab(), tr("线条颜色", "Line Colors"))
        tabs.addTab(self._build_band_tab(), tr("条带样式", "Band Style"))
        tabs.addTab(self._build_scan_tab(), tr("扫描线", "Scan Line"))
        layout.addWidget(tabs)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        reset_btn = QPushButton(tr("恢复默认", "Reset"))
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)
        close_btn = QPushButton(tr("关闭", "Close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _build_line_tab(self):
        """Build line color and width settings tab."""
        widget = QWidget()
        form = QFormLayout(widget)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)

        items = [
            ("profiles", tr("偏移线", "Profiles")),
            ("min", tr("最小值", "Min")),
            ("max", tr("最大值", "Max")),
            ("mean", tr("均值", "Mean")),
            ("q1", "Q1"),
            ("q3", "Q3"),
            ("relief", tr("起伏", "Relief")),
            ("thi", "THi"),
        ]

        self._width_spins = {}

        for key, label in items:
            # Container for color + width
            container = QWidget()
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)

            # Color button
            color_key = f"color_{key}"
            btn = _color_btn(self._settings[color_key], lambda c, k=color_key: self._on_color_changed(k, c))
            self._color_btns[color_key] = btn
            h.addWidget(btn)

            # Width spinbox (mm)
            width_key = f"width_{key}"
            spin = QDoubleSpinBox()
            spin.setRange(0.1, 5.0)
            spin.setSingleStep(0.1)
            spin.setDecimals(1)
            spin.setValue(self._settings[width_key])
            spin.setSuffix(" mm")
            spin.setFixedWidth(75)
            spin.valueChanged.connect(lambda v, k=width_key: self._on_setting_changed(k, v))
            self._width_spins[width_key] = spin
            h.addWidget(spin)

            form.addRow(label + ":", container)

        return widget

    def _build_band_tab(self):
        """Build band style settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Fill settings
        fill_box = QGroupBox(tr("填充", "Fill"))
        fill_form = QFormLayout(fill_box)
        fill_form.setLabelAlignment(Qt.AlignRight)

        self._band_fill_btn = _color_btn(
            self._settings["band_fill_color"],
            lambda c: self._on_setting_changed("band_fill_color", c)
        )
        fill_form.addRow(tr("颜色:", "Color:"), self._band_fill_btn)

        self._band_fill_opacity = QDoubleSpinBox()
        self._band_fill_opacity.setRange(0, 100)
        self._band_fill_opacity.setValue(self._settings["band_fill_opacity"])
        self._band_fill_opacity.setSuffix("%")
        self._band_fill_opacity.valueChanged.connect(
            lambda v: self._on_setting_changed("band_fill_opacity", v)
        )
        fill_form.addRow(tr("不透明度:", "Opacity:"), self._band_fill_opacity)
        layout.addWidget(fill_box)

        # Stroke settings
        stroke_box = QGroupBox(tr("描边", "Stroke"))
        stroke_form = QFormLayout(stroke_box)
        stroke_form.setLabelAlignment(Qt.AlignRight)

        self._band_stroke_btn = _color_btn(
            self._settings["band_stroke_color"],
            lambda c: self._on_setting_changed("band_stroke_color", c)
        )
        stroke_form.addRow(tr("颜色:", "Color:"), self._band_stroke_btn)

        self._band_stroke_width = QDoubleSpinBox()
        self._band_stroke_width.setRange(0.1, 10.0)
        self._band_stroke_width.setValue(self._settings["band_stroke_width"])
        self._band_stroke_width.setSingleStep(0.1)
        self._band_stroke_width.valueChanged.connect(
            lambda v: self._on_setting_changed("band_stroke_width", v)
        )
        stroke_form.addRow(tr("宽度:", "Width:"), self._band_stroke_width)

        self._band_stroke_opacity = QDoubleSpinBox()
        self._band_stroke_opacity.setRange(0, 100)
        self._band_stroke_opacity.setValue(self._settings["band_stroke_opacity"])
        self._band_stroke_opacity.setSuffix("%")
        self._band_stroke_opacity.valueChanged.connect(
            lambda v: self._on_setting_changed("band_stroke_opacity", v)
        )
        stroke_form.addRow(tr("不透明度:", "Opacity:"), self._band_stroke_opacity)
        layout.addWidget(stroke_box)

        layout.addStretch(1)
        return widget

    def _build_scan_tab(self):
        """Build scan line settings tab."""
        widget = QWidget()
        form = QFormLayout(widget)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)

        # Color
        self._scan_color_btn = _color_btn(
            self._settings["scan_color"],
            lambda c: self._on_setting_changed("scan_color", c)
        )
        form.addRow(tr("颜色:", "Color:"), self._scan_color_btn)

        # Width
        self._scan_width = QDoubleSpinBox()
        self._scan_width.setRange(0.1, 5.0)
        self._scan_width.setSingleStep(0.1)
        self._scan_width.setDecimals(1)
        self._scan_width.setValue(self._settings["scan_width"])
        self._scan_width.setSuffix(" mm")
        self._scan_width.valueChanged.connect(
            lambda v: self._on_setting_changed("scan_width", v)
        )
        form.addRow(tr("宽度:", "Width:"), self._scan_width)

        return widget



    def _on_color_changed(self, key, color):
        self._settings[key] = color
        self.settings_changed.emit(self._settings)

    def _on_setting_changed(self, key, value):
        self._settings[key] = value
        self.settings_changed.emit(self._settings)

    def _reset_defaults(self):
        """Reset all settings to defaults."""
        self._settings = dict(self.DEFAULTS)
        # Update color buttons
        for key, btn in self._color_btns.items():
            color = self._settings[key]
            btn.setStyleSheet(f"background:{color}; border:1px solid #999; border-radius:3px;")
            btn.setProperty("color", color)
        # Update width spinboxes
        for key, spin in self._width_spins.items():
            spin.setValue(self._settings[key])
        # Update band settings
        self._band_fill_btn.setStyleSheet(
            f"background:{self._settings['band_fill_color']}; border:1px solid #999; border-radius:3px;")
        self._band_fill_btn.setProperty("color", self._settings["band_fill_color"])
        self._band_fill_opacity.setValue(self._settings["band_fill_opacity"])
        self._band_stroke_btn.setStyleSheet(
            f"background:{self._settings['band_stroke_color']}; border:1px solid #999; border-radius:3px;")
        self._band_stroke_btn.setProperty("color", self._settings["band_stroke_color"])
        self._band_stroke_width.setValue(self._settings["band_stroke_width"])
        self._band_stroke_opacity.setValue(self._settings["band_stroke_opacity"])
        # Update scan line settings
        self._scan_color_btn.setStyleSheet(
            f"background:{self._settings['scan_color']}; border:1px solid #999; border-radius:3px;")
        self._scan_color_btn.setProperty("color", self._settings["scan_color"])
        self._scan_width.setValue(self._settings["scan_width"])



        self.settings_changed.emit(self._settings)

    def get_settings(self):
        """Return current settings dict."""
        return dict(self._settings)

    def set_settings(self, settings):
        """Load settings dict."""
        self._settings.update(settings)
        # Update UI
        for key, btn in self._color_btns.items():
            if key in self._settings:
                color = self._settings[key]
                btn.setStyleSheet(f"background:{color}; border:1px solid #999; border-radius:3px;")
                btn.setProperty("color", color)
        # Update width spinboxes
        for key, spin in self._width_spins.items():
            if key in self._settings:
                spin.setValue(self._settings[key])
        if "band_fill_color" in self._settings:
            self._band_fill_btn.setStyleSheet(
                f"background:{self._settings['band_fill_color']}; border:1px solid #999; border-radius:3px;")
            self._band_fill_btn.setProperty("color", self._settings["band_fill_color"])
        if "band_fill_opacity" in self._settings:
            self._band_fill_opacity.setValue(self._settings["band_fill_opacity"])
        if "band_stroke_color" in self._settings:
            self._band_stroke_btn.setStyleSheet(
                f"background:{self._settings['band_stroke_color']}; border:1px solid #999; border-radius:3px;")
            self._band_stroke_btn.setProperty("color", self._settings["band_stroke_color"])
        if "band_stroke_width" in self._settings:
            self._band_stroke_width.setValue(self._settings["band_stroke_width"])
        if "band_stroke_opacity" in self._settings:
            self._band_stroke_opacity.setValue(self._settings["band_stroke_opacity"])


