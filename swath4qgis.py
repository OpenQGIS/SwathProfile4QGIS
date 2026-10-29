# -*- coding: utf-8 -*-
"""
Main plugin class for SwathProfile4QGIS.
Manages toolbar actions, menu entries, and two dock widgets.
"""

import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt


def _qt_enum(group_name, value_name):
    """Resolve Qt enum across PyQt5 / PyQt6 namespace differences."""
    group = getattr(Qt, group_name, None)
    if group is not None and hasattr(group, value_name):
        return getattr(group, value_name)
    if hasattr(Qt, value_name):
        return getattr(Qt, value_name)
    raise AttributeError(f"Qt enum not found: {group_name}.{value_name}")


class Swath4QGIS:
    """Main plugin class wired into QGIS via classFactory."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.param_dock = None
        self.profile_dock = None
        self.map_tool = None
        self._prev_tool = None
        self.toolbar = None

        # Load translation matching QGIS locale
        import re
        from qgis.PyQt.QtCore import QTranslator, QLocale, QCoreApplication
        from qgis.core import QgsSettings

        # Fetch locale and sanitize to prevent path traversal
        locale_name = QgsSettings().value("locale/userLocale", QLocale.system().name())
        if locale_name is not None:
            locale_name = str(locale_name)
        else:
            locale_name = "en"
        if not re.match(r"^[a-zA-Z0-9_\-]+$", locale_name):
            locale_name = "en"

        # Normalize QGIS locale format (e.g. zh-Hans -> zh_CN, zh-Hant -> zh_TW)
        _locale_map = {
            "zh-hans": "zh_CN",
            "zh-hant": "zh_TW",
            "zh-cn":   "zh_CN",
            "zh-tw":   "zh_TW",
        }
        locale_candidates = []
        _key = locale_name.lower()
        if _key in _locale_map:
            locale_candidates.append(_locale_map[_key])
        locale_candidates.append(locale_name.replace("-", "_"))
        locale_candidates.append(locale_name.split("_")[0].split("-")[0])

        self.translator = QTranslator()
        i18n_dir = os.path.join(os.path.dirname(__file__), "i18n")
        for candidate in locale_candidates:
            if self.translator.load(f"SwathProfile4QGIS_{candidate}", i18n_dir):
                QCoreApplication.installTranslator(self.translator)
                break

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def initGui(self):
        from .i18n import tr
        icon_path = os.path.join(os.path.dirname(__file__), "icons", "icon.svg")
        self.action = QAction(
            QIcon(icon_path) if os.path.isfile(icon_path) else QIcon.fromTheme("layer-raster"),
            tr("横截面剖面", "Swath Profile"),
            self.iface.mainWindow(),
        )
        self.action.setToolTip(tr("打开横截面剖面面板", "Open swath profile panels"))
        self.action.triggered.connect(self.run)
        
        # Create a dedicated toolbar to make it movable
        self.toolbar = self.iface.addToolBar(tr("横截面剖面", "Swath Profile"))
        self.toolbar.setObjectName("SwathProfileToolbar")
        self.toolbar.addAction(self.action)
        
        self.iface.addPluginToRasterMenu(
            tr("&横截面剖面", "&Swath Profile"), self.action
        )

    def unload(self):
        from .i18n import tr
        from qgis.PyQt.QtCore import QCoreApplication
        if hasattr(self, 'translator') and self.translator is not None:
            QCoreApplication.removeTranslator(self.translator)
            self.translator = None

        # Clear swath bands before closing
        if self.param_dock is not None:
            self.param_dock._clear_swath_bands()
        if self.action:
            if self.toolbar is not None:
                self.iface.mainWindow().removeToolBar(self.toolbar)
                self.toolbar.setParent(None)
                self.toolbar.deleteLater()
                self.toolbar = None
            else:
                self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginRasterMenu(
                tr("&横截面剖面", "&Swath Profile"), self.action
            )
            self.action = None
        self._close_docks()
        self._restore_tool()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run(self):
        """Toggle both dock panels."""
        try:
            if self.param_dock is None:
                self._create_docks()
            else:
                # Check if dock is truly visible (not just behind another tab)
                if self.param_dock.isVisible() and not self.param_dock.isMinimized():
                    # Currently visible, hide both
                    self.param_dock.hide()
                    self.profile_dock.hide()
                else:
                    # Currently hidden or behind tab, show and bring to front
                    self.param_dock.show()
                    self.param_dock.raise_()
                    self.profile_dock.show()
                    self.profile_dock.raise_()
        except Exception as e:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(self.iface.mainWindow(), "Error", str(e))

    def show_dock(self, swath_profiles, mode="offset", baseline_geoms=None, fields=None, field_values=None, strip_widths=None, select_idx=0):
        """Refresh the profile dock with computed results."""
        if self.profile_dock is None:
            self._create_docks()
        self.profile_dock.load_profiles(swath_profiles, mode, baseline_geoms, fields, field_values, strip_widths, select_idx=select_idx)
        self.profile_dock.show()

    def activate_map_tool(self, callback):
        """Activate the interactive draw tool; *callback(geom)* on finish."""
        from .swath_map_tool import SwathDrawTool
        canvas = self.iface.mapCanvas()
        self._prev_tool = canvas.mapTool()
        self.map_tool = SwathDrawTool(canvas, callback)
        canvas.setMapTool(self.map_tool)

    def deactivate_map_tool(self):
        """Restore the previous map tool."""
        self._restore_tool()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_docks(self):
        """Create both dock widgets."""
        from .swath_param_dock import SwathParamDock
        from .swath_dock import SwathDock

        # Parameter dock (floating)
        from qgis.PyQt.QtCore import QTimer
        self.param_dock = SwathParamDock(self, self.iface.mainWindow())
        self.iface.addDockWidget(
            _qt_enum("DockWidgetArea", "LeftDockWidgetArea"), self.param_dock
        )
        self.param_dock.setFloating(True)
        self.param_dock.show()
        # Delay resize to let Qt layout engine finish, then force size
        QTimer.singleShot(0, lambda: self.param_dock.resize(300, 600))
        self.param_dock.move(100, 100)

        # Profile dock (bottom)
        self.profile_dock = SwathDock(self, self.iface.mainWindow())
        self.iface.addDockWidget(
            _qt_enum("DockWidgetArea", "BottomDockWidgetArea"), self.profile_dock
        )
        self.profile_dock.show()

    def _close_docks(self):
        for dock in (self.param_dock, self.profile_dock):
            if dock is not None:
                self.iface.removeDockWidget(dock)
                dock.close()
                dock.deleteLater()
        self.param_dock = None
        self.profile_dock = None

    def _restore_tool(self):
        if self.map_tool is not None:
            canvas = self.iface.mapCanvas()
            if self._prev_tool is not None:
                canvas.setMapTool(self._prev_tool)
            else:
                canvas.unsetMapTool(self.map_tool)
            self.map_tool = None
            self._prev_tool = None
