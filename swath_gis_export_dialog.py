# -*- coding: utf-8 -*-
"""
Export dialog for SwathProfile GIS data.
"""

from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox, 
                                 QLineEdit, QCheckBox, QDialogButtonBox, QWidget,
                                 QHBoxLayout, QToolButton, QFileDialog, QRadioButton,
                                 QGroupBox, QLabel)
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.gui import QgsProjectionSelectionWidget
from qgis.core import QgsCoordinateReferenceSystem

from .i18n import tr


class SwathGisExportDialog(QDialog):
    """Dialog for configuring and executing GIS data export."""

    def __init__(self, parent=None, default_crs=None):
        super().__init__(parent)
        self.setWindowTitle(tr("导出为 GIS 矢量数据", "Export to GIS Vector Data"))
        
        self.settings = QSettings()
        
        # Form Layout
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        layout.addLayout(form_layout)

        # 1. Format
        self.format_combo = QComboBox()
        self.format_combo.addItem("GeoPackage (*.gpkg)", "GPKG")
        self.format_combo.addItem("ESRI FileGDB (*.gdb)", "OpenFileGDB")
        self.format_combo.addItem("ESRI Shapefile (*.shp)", "ESRI Shapefile")
        self.format_combo.addItem("GeoJSON (*.geojson)", "GeoJSON")
        
        # Restore last used format
        last_format = self.settings.value("SwathProfile/LastExportFormat", "GPKG")
        index = self.format_combo.findData(last_format)
        if index >= 0:
            self.format_combo.setCurrentIndex(index)
            
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        form_layout.addRow(tr("格式 (Format):", "Format:"), self.format_combo)

        # 2. File Path
        file_widget = QWidget()
        file_layout = QHBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.file_edit = QLineEdit()
        self.file_btn = QToolButton()
        self.file_btn.setText("...")
        self.file_btn.clicked.connect(self._browse_file)
        file_layout.addWidget(self.file_edit)
        file_layout.addWidget(self.file_btn)
        form_layout.addRow(tr("文件名 (File name):", "File name:"), file_widget)

        # 3. Layer Name
        self.layer_edit = QLineEdit("Profile3D")
        form_layout.addRow(tr("图层名 (Layer name):", "Layer name:"), self.layer_edit)

        # 4. CRS Selection
        self.crs_widget = QgsProjectionSelectionWidget()
        if default_crs and default_crs.isValid():
            self.crs_widget.setCrs(default_crs)
        form_layout.addRow(tr("坐标系 (CRS):", "CRS:"), self.crs_widget)

        # 5. Export Mode
        mode_group = QGroupBox(tr("投影模式", "Projection Mode"))
        mode_layout = QVBoxLayout(mode_group)
        self.radio_spatial = QRadioButton(tr("真实空间位置 (Spatial Location)", "Spatial Location"))
        self.radio_baseline = QRadioButton(tr("投影至中央基线 (Projected to Baseline)", "Projected to Baseline"))
        
        # Restore last mode
        last_mode = self.settings.value("SwathProfile/LastExportMode", "spatial")
        if last_mode == "baseline":
            self.radio_baseline.setChecked(True)
        else:
            self.radio_spatial.setChecked(True)
            
        mode_layout.addWidget(self.radio_spatial)
        mode_layout.addWidget(self.radio_baseline)
        form_layout.addRow(mode_group)

        # 6. Geometry Type
        geom_group = QGroupBox(tr("输出要素类型", "Geometry Type"))
        geom_layout = QVBoxLayout(geom_group)
        self.radio_line = QRadioButton(tr("3D 线段 (LineStringZ)", "3D LineStringZ"))
        self.radio_point = QRadioButton(tr("3D 散点 (PointZ) - 推荐在剖面工具中使用", "3D PointZ - Recommended for Profile Tool"))
        
        # Restore last geometry type
        last_geom = self.settings.value("SwathProfile/LastExportGeom", "line")
        if last_geom == "point":
            self.radio_point.setChecked(True)
        else:
            self.radio_line.setChecked(True)
            
        geom_layout.addWidget(self.radio_line)
        geom_layout.addWidget(self.radio_point)
        form_layout.addRow(geom_group)

        # 7. Smoothing
        self.smooth_combo = QComboBox()
        self.smooth_combo.addItem(tr("0 (不平滑)", "0 (No smoothing)"), 0)
        self.smooth_combo.addItem("5", 5)
        self.smooth_combo.addItem("9", 9)
        self.smooth_combo.addItem("15", 15)
        self.smooth_combo.addItem("25", 25)
        
        last_smooth = self.settings.value("SwathProfile/LastExportSmooth", 0, type=int)
        index = self.smooth_combo.findData(last_smooth)
        if index >= 0:
            self.smooth_combo.setCurrentIndex(index)
            
        form_layout.addRow(tr("曲线平滑 (Smoothing):", "Curve Smoothing:"), self.smooth_combo)

        # 7. Add to Map
        self.add_map_check = QCheckBox(tr("导出后将文件添加到地图", "Add saved file to map"))
        self.add_map_check.setChecked(self.settings.value("SwathProfile/ExportAddMap", True, type=bool))
        layout.addWidget(self.add_map_check)

        # Button Box
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Initial UI update
        self._on_format_changed()
        self.resize(500, 400)

    def _on_format_changed(self):
        """Update UI based on selected format."""
        format_data = self.format_combo.currentData()
        
        # Toggle layer name field
        if format_data in ("GPKG", "OpenFileGDB"):
            self.layer_edit.setEnabled(True)
            self.layer_edit.setPlaceholderText(tr("输入图层名称", "Enter layer name"))
        else:
            self.layer_edit.setEnabled(False)
            self.layer_edit.setPlaceholderText(tr("该格式不支持图层名", "Not applicable for this format"))
            
        # Update extension if file exists
        current_path = self.file_edit.text()
        if current_path:
            import os
            base, _ = os.path.splitext(current_path)
            if format_data == "GPKG":
                ext = ".gpkg"
            elif format_data == "OpenFileGDB":
                ext = ".gdb"
            elif format_data == "GeoJSON":
                ext = ".geojson"
            else:
                ext = ".shp"
            self.file_edit.setText(base + ext)

    def _browse_file(self):
        format_data = self.format_combo.currentData()
        
        if format_data == "GPKG":
            filter_str = "GeoPackage (*.gpkg)"
            ext = ".gpkg"
        elif format_data == "OpenFileGDB":
            filter_str = "ESRI FileGDB (*.gdb)"
            ext = ".gdb"
        elif format_data == "GeoJSON":
            filter_str = "GeoJSON (*.geojson)"
            ext = ".geojson"
        else:
            filter_str = "ESRI Shapefile (*.shp)"
            ext = ".shp"

        last_dir = self.settings.value("SwathProfile/LastExportDir", "")
        
        if format_data == "OpenFileGDB":
            # GDB is a directory
            path = QFileDialog.getExistingDirectory(self, tr("选择保存位置 (GDB 文件夹)", "Select Save Location (GDB Folder)"), last_dir)
            if path:
                if not path.endswith('.gdb'):
                    path += ".gdb"
                self.file_edit.setText(path)
        else:
            path, _ = QFileDialog.getSaveFileName(self, tr("保存矢量图层为...", "Save Vector Layer as..."), last_dir, filter_str)
            if path:
                if not path.endswith(ext):
                    path += ext
                self.file_edit.setText(path)

        if path:
            import os
            self.settings.setValue("SwathProfile/LastExportDir", os.path.dirname(path))

    def get_export_params(self):
        """Return a dictionary of configured export parameters."""
        format_data = self.format_combo.currentData()
        
        # Save settings for next time
        self.settings.setValue("SwathProfile/LastExportFormat", format_data)
        self.settings.setValue("SwathProfile/LastExportMode", "baseline" if self.radio_baseline.isChecked() else "spatial")
        self.settings.setValue("SwathProfile/LastExportGeom", "point" if self.radio_point.isChecked() else "line")
        self.settings.setValue("SwathProfile/ExportAddMap", self.add_map_check.isChecked())
        self.settings.setValue("SwathProfile/LastExportSmooth", self.smooth_combo.currentData())
        
        return {
            "format": format_data,
            "filepath": self.file_edit.text(),
            "layer_name": self.layer_edit.text(),
            "crs": self.crs_widget.crs(),
            "is_baseline": self.radio_baseline.isChecked(),
            "is_point": self.radio_point.isChecked(),
            "add_to_map": self.add_map_check.isChecked(),
            "smooth_window": self.smooth_combo.currentData()
        }