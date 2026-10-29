# -*- coding: utf-8 -*-
"""
Interactive matplotlib canvas for swath profile visualization.
"""

import logging
from qgis.PyQt.QtCore import QTimer

logger = logging.getLogger("SwathProfile4QGIS")
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsPointXY, QgsGeometry

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from matplotlib.patches import Rectangle


class InteractiveCanvas(FigureCanvas):
    """Matplotlib canvas with QGIS-style map interactions."""

    def __init__(self, figure, plugin=None):
        super().__init__(figure)
        self.plugin = plugin
        self._scan_rubber_band = None
        self._xform = None

        # Interaction state
        self._dragging = False
        self._drag_button = None
        self._drag_start = None
        self._rubber_band_rect = None
        self._press_xlim = None
        self._press_ylim = None

        # Crosshair lines
        self._crosshair_v = None
        self._crosshair_h = None
        self._crosshair_ax = None

        # Coordinate annotations
        self._ann_x = None
        self._ann_y = None

        # Hover tracking
        self._hover_xdata = None
        self._hover_timer = QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(16)  # ~60fps
        self._hover_timer.timeout.connect(self._update_map_marker)

        # Connect events
        self.mpl_connect('scroll_event', self._on_scroll)
        self.mpl_connect('button_press_event', self._on_press)
        self.mpl_connect('button_release_event', self._on_release)
        self.mpl_connect('motion_notify_event', self._on_motion)
        self.mpl_connect('axes_leave_event', self._on_axes_leave)

        self.setMouseTracking(True)

        # Current profile data
        self._current_sp = None
        self._baseline_geom = None
        self._swath_width = 500.0
        self._scan_settings = {}
        self._dem_crs = None
        self._proj_crs = None

    def set_profile_data(self, sp, baseline_geom=None, swath_width=500.0, scan_settings=None,
                          dem_crs=None, proj_crs=None):
        self._current_sp = sp
        self._baseline_geom = baseline_geom
        self._swath_width = swath_width
        self._scan_settings = scan_settings or {}
        self._dem_crs = dem_crs
        self._proj_crs = proj_crs
        
        # Precompute coordinate transform once to avoid expensive recreating on hover
        if dem_crs and proj_crs and dem_crs != proj_crs:
            from qgis.core import QgsCoordinateTransform, QgsProject
            self._xform = QgsCoordinateTransform(dem_crs, proj_crs, QgsProject.instance())
        else:
            self._xform = None

    # ------------------------------------------------------------------
    # Scroll zoom
    # ------------------------------------------------------------------

    def _on_scroll(self, event):
        if event.inaxes is None:
            return
        ax = event.inaxes
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        factor = 0.8 if event.button == 'up' else 1.25
        xdata, ydata = event.xdata, event.ydata
        ax.set_xlim([xdata - (xdata - xlim[0]) * factor, xdata + (xlim[1] - xdata) * factor])
        ax.set_ylim([ydata - (ydata - ylim[0]) * factor, ydata + (ylim[1] - ydata) * factor])
        self.draw_idle()

    # ------------------------------------------------------------------
    # Button press/release
    # ------------------------------------------------------------------

    def _on_press(self, event):
        if event.inaxes is None:
            return
        self._dragging = True
        self._drag_button = event.button
        self._drag_start = (event.x, event.y)
        self._press_xlim = event.inaxes.get_xlim()
        self._press_ylim = event.inaxes.get_ylim()
        if event.button == 1:
            self._rubber_band_rect = (event.xdata, event.ydata)

    def _on_release(self, event):
        if not self._dragging:
            return
        ax = event.inaxes
        if self._drag_button == 1 and self._rubber_band_rect is not None:
            if ax is not None and event.xdata is not None:
                x0, y0 = self._rubber_band_rect
                x1, y1 = event.xdata, event.ydata
                if abs(x1 - x0) > 0 and abs(y1 - y0) > 0:
                    ax.set_xlim(min(x0, x1), max(x0, x1))
                    ax.set_ylim(min(y0, y1), max(y0, y1))
                    self.draw_idle()
            self._rubber_band_rect = None
            self._remove_rubber_band()
        self._dragging = False
        self._drag_button = None
        self._drag_start = None
        self._press_xlim = None
        self._press_ylim = None

    # ------------------------------------------------------------------
    # Mouse motion
    # ------------------------------------------------------------------

    def _on_motion(self, event):
        if event.inaxes is None:
            self._remove_crosshair()
            self._remove_map_marker()
            return

        # Update crosshair
        self._update_crosshair(event.inaxes, event.xdata, event.ydata)

        # Update hover position and start hover timer (throttled at 16ms / 60fps)
        if event.xdata is not None:
            self._hover_xdata = event.xdata
            if not self._hover_timer.isActive():
                self._hover_timer.start()

        if not self._dragging:
            return

        ax = event.inaxes
        if self._drag_button == 2 and self._press_xlim is not None:
            self._do_pan(ax, event)
        elif self._drag_button == 1 and self._rubber_band_rect is not None:
            self._draw_rubber_band(event)
        elif self._drag_button == 3 and self._press_xlim is not None:
            self._do_axis_scale(ax, event)

    # ------------------------------------------------------------------
    # Crosshair
    # ------------------------------------------------------------------

    def _update_crosshair(self, ax, xdata, ydata):
        """Update crosshair reference lines and coordinate annotations."""
        # Remove old crosshair if axes changed
        if self._crosshair_ax != ax:
            self._remove_crosshair()
            self._crosshair_ax = ax

        # Create or update lines
        if self._crosshair_v is None:
            self._crosshair_v = ax.axvline(xdata, color='#888888', linewidth=1.0,
                                            linestyle='-', alpha=0.7, zorder=10)
        else:
            self._crosshair_v.set_xdata([xdata])

        if self._crosshair_h is None:
            self._crosshair_h = ax.axhline(ydata, color='#888888', linewidth=1.0,
                                            linestyle='-', alpha=0.7, zorder=10)
        else:
            self._crosshair_h.set_ydata([ydata])

        # Update coordinate annotations
        self._update_annotations(ax, xdata, ydata)

        # Force redraw on idle
        self.draw_idle()

    def _update_annotations(self, ax, xdata, ydata):
        """Update coordinate annotations near the crosshair."""
        # Remove old annotations
        for ann_attr in ('_ann_x', '_ann_y'):
            ann = getattr(self, ann_attr, None)
            if ann is not None:
                try:
                    ann.remove()
                except Exception:
                    logger.debug("Failed to remove annotation %s", ann_attr)
                setattr(self, ann_attr, None)

        # Get plot area bounds
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        mid_x = (xlim[0] + xlim[1]) / 2
        mid_y = (ylim[0] + ylim[1]) / 2

        # Format text
        x_text = f"{xdata:.1f}"
        y_text = f"{ydata:.1f} m"

        # Common style
        text_kwargs = dict(
            fontsize=9,
            fontfamily='monospace',
            fontweight='bold',
            bbox=dict(
                boxstyle="round,pad=0.2",
                facecolor="white",
                edgecolor="#999999",
                alpha=0.9,
                linewidth=0.5
            ),
            zorder=11
        )

        # X annotation - at bottom edge, near vertical line
        x_ha = 'left' if xdata < mid_x else 'right'
        try:
            self._ann_x = ax.text(
                xdata, ylim[0], f" {x_text} ",
                ha=x_ha, va='bottom',
                transform=ax.transData,
                **text_kwargs
            )
        except Exception as e:
            print(f"Annotation X error: {e}")

        # Y annotation - at right edge, near horizontal line
        y_va = 'bottom' if ydata < mid_y else 'top'
        try:
            self._ann_y = ax.text(
                xlim[1], ydata, f" {y_text} ",
                ha='right', va=y_va,
                transform=ax.transData,
                **text_kwargs
            )
        except Exception as e:
            print(f"Annotation Y error: {e}")

    def _remove_crosshair(self):
        for line in (self._crosshair_v, self._crosshair_h):
            if line is not None:
                try:
                    line.remove()
                except Exception:
                    logger.debug("Failed to remove crosshair line")
        self._crosshair_v = None
        self._crosshair_h = None

        # Remove annotations
        for ann in (self._ann_x, self._ann_y):
            if ann is not None:
                try:
                    ann.remove()
                except Exception:
                    logger.debug("Failed to remove crosshair annotation")
        self._ann_x = None
        self._ann_y = None
        self._crosshair_ax = None

    # ------------------------------------------------------------------
    # Pan
    # ------------------------------------------------------------------

    def _do_pan(self, ax, event):
        if self._drag_start is None or self._press_xlim is None:
            return
        x0, y0 = self._drag_start
        dx_pixel = event.x - x0
        dy_pixel = event.y - y0
        bbox = ax.get_window_extent()
        if bbox.width == 0 or bbox.height == 0:
            return
        x_range = self._press_xlim[1] - self._press_xlim[0]
        y_range = self._press_ylim[1] - self._press_ylim[0]
        dx_data = -dx_pixel * x_range / bbox.width
        dy_data = -dy_pixel * y_range / bbox.height
        ax.set_xlim(self._press_xlim[0] + dx_data, self._press_xlim[1] + dx_data)
        ax.set_ylim(self._press_ylim[0] + dy_data, self._press_ylim[1] + dy_data)
        self.draw_idle()

    # ------------------------------------------------------------------
    # Rubber band
    # ------------------------------------------------------------------

    def _draw_rubber_band(self, event):
        self._remove_rubber_band()
        if self._rubber_band_rect is None or event.xdata is None:
            return
        x0, y0 = self._rubber_band_rect
        x1, y1 = event.xdata, event.ydata
        ax = event.inaxes
        rect = Rectangle((min(x0, x1), min(y0, y1)), abs(x1 - x0), abs(y1 - y0),
                          linewidth=1, edgecolor='#0078D7', facecolor='#0078D7',
                          alpha=0.15, linestyle='--')
        ax.add_patch(rect)
        self._rubber_band_patch = rect
        self.draw_idle()

    def _remove_rubber_band(self):
        if hasattr(self, '_rubber_band_patch') and self._rubber_band_patch is not None:
            try:
                self._rubber_band_patch.remove()
            except Exception:
                logger.debug("Failed to remove rubber band patch")
            self._rubber_band_patch = None

    # ------------------------------------------------------------------
    # Axis scaling (right button)
    # ------------------------------------------------------------------

    def _do_axis_scale(self, ax, event):
        if self._drag_start is None or self._press_xlim is None:
            return
        x0, y0 = self._drag_start
        dx_pixel = event.x - x0
        dy_pixel = event.y - y0
        scale_x = max(0.1, min(10.0, 1.0 + dx_pixel * 0.005))
        scale_y = max(0.1, min(10.0, 1.0 - dy_pixel * 0.005))
        x_center = self._press_xlim[0] + (self._press_xlim[1] - self._press_xlim[0]) * 0.5
        y_center = self._press_ylim[0] + (self._press_ylim[1] - self._press_ylim[0]) * 0.5
        x_range = (self._press_xlim[1] - self._press_xlim[0]) * scale_x
        y_range = (self._press_ylim[1] - self._press_ylim[0]) * scale_y
        ax.set_xlim(x_center - x_range / 2, x_center + x_range / 2)
        ax.set_ylim(y_center - y_range / 2, y_center + y_range / 2)
        self.draw_idle()

    # ------------------------------------------------------------------
    # Map marker (perpendicular line)
    # ------------------------------------------------------------------

    def _on_axes_leave(self, event):
        self._remove_crosshair()
        self._remove_map_marker()

    def leaveEvent(self, event):
        """Remove markers when mouse leaves the canvas entirely."""
        self._remove_crosshair()
        self._remove_map_marker()

    def _update_map_marker(self):
        if self._current_sp is None or self._baseline_geom is None:
            return
        if self._hover_xdata is None or self.plugin is None:
            return

        dist = self._hover_xdata
        length = self._baseline_geom.length()
        if dist < 0 or dist > length:
            self._remove_map_marker()
            return

        pt = self._baseline_geom.interpolate(dist).asPoint()
        half_width = self._swath_width / 2.0

        # Calculate perpendicular direction
        delta = max(length * 0.001, 0.1)
        d1 = max(0, dist - delta)
        d2 = min(length, dist + delta)
        pt1 = self._baseline_geom.interpolate(d1).asPoint()
        pt2 = self._baseline_geom.interpolate(d2).asPoint()

        dx = pt2.x() - pt1.x()
        dy = pt2.y() - pt1.y()
        tangent_len = (dx**2 + dy**2) ** 0.5

        if tangent_len < 1e-10:
            self._remove_map_marker()
            return

        perp_x = -dy / tangent_len
        perp_y = dx / tangent_len

        p1 = QgsPointXY(pt.x() + perp_x * half_width, pt.y() + perp_y * half_width)
        p2 = QgsPointXY(pt.x() - perp_x * half_width, pt.y() - perp_y * half_width)

        # Transform from DEM CRS to project CRS for display
        if self._xform:
            geom1 = QgsGeometry.fromPointXY(p1)
            geom2 = QgsGeometry.fromPointXY(p2)
            geom1.transform(self._xform)
            geom2.transform(self._xform)
            p1 = geom1.asPoint()
            p2 = geom2.asPoint()

        self._show_map_line(p1, p2)

    def _show_map_line(self, p1, p2):
        if self.plugin is None or self.plugin.iface is None:
            return

        canvas = self.plugin.iface.mapCanvas()

        # Get scan settings
        s = self._scan_settings
        color_hex = s.get("scan_color", "#80cc28")
        width_mm = s.get("scan_width", 0.3)

        # Convert mm to pixels (approximate: 1mm ≈ 3.78px at 96dpi)
        main_width = max(1, int(width_mm * 3.78))

        if self._scan_rubber_band is None:
            from qgis.gui import QgsRubberBand
            try:
                from qgis.core import Qgis
                line_type = Qgis.GeometryType.Line
            except (ImportError, AttributeError):
                line_type = None

            try:
                self._scan_rubber_band = QgsRubberBand(canvas, line_type) if line_type else QgsRubberBand(canvas)
            except Exception:
                self._scan_rubber_band = QgsRubberBand(canvas)

        self._scan_rubber_band.setColor(QColor(color_hex))
        self._scan_rubber_band.setWidth(main_width)
        try:
            self._scan_rubber_band.setZValue(10000)
        except Exception:
            logger.debug("Failed to set scan rubber band ZValue")
        self._scan_rubber_band.reset()
        self._scan_rubber_band.addPoint(p1, False)
        self._scan_rubber_band.addPoint(p2, True)
        self._scan_rubber_band.show()

    def _remove_map_marker(self):
        if self._scan_rubber_band is not None:
            try:
                self._scan_rubber_band.reset()
                self._scan_rubber_band.hide()
            except Exception:
                logger.debug("Failed to hide scan rubber band")

    def reset_view(self):
        for ax in self.figure.get_axes():
            ax.autoscale()
            ax.set_autoscale_on(True)
        self.draw_idle()
