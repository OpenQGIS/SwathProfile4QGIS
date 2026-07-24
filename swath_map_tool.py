# -*- coding: utf-8 -*-
"""
Interactive map tool for drawing a baseline polyline on the canvas.
"""

from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import Qt


class SwathDrawTool(QgsMapToolEmitPoint):
    """Left-click adds vertices; right-click finishes the line.

    On finish, calls ``callback(QgsGeometry)`` with the resulting
    polyline geometry and then deactivates itself.
    """

    def __init__(self, canvas, callback):
        super().__init__(canvas)
        self._canvas = canvas
        self._callback = callback
        self._points = []
        self._rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(255, 0, 0, 200))  # Red
        self._rubber.setWidth(2)
        self._rubber.setLineStyle(Qt.SolidLine)

    # ------------------------------------------------------------------

    def canvasReleaseEvent(self, event):
        pt = self.toMapCoordinates(event.pos())

        if event.button() == Qt.LeftButton:
            self._points.append(QgsPointXY(pt))
            self._rubber.addPoint(QgsPointXY(pt))
            if len(self._points) > 1:
                self._rubber.movePoint(QgsPointXY(pt))
        elif event.button() == Qt.RightButton:
            self._finish()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._cancel()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._finish()

    # ------------------------------------------------------------------

    def _finish(self):
        if len(self._points) >= 2:
            geom = QgsGeometry.fromPolylineXY(self._points)
            self._cleanup()
            if self._callback:
                self._callback(geom)
        else:
            self._cancel()

    def _cancel(self):
        self._cleanup()
        if self._callback:
            self._callback(None)

    def _cleanup(self):
        self._points = []
        if self._rubber is not None:
            self._rubber.reset()
            # QgsRubberBand is owned by the canvas scene; reset() is enough.
            self._rubber = None

    def deactivate(self):
        self._cleanup()
        super().deactivate()
