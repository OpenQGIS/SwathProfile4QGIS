# -*- coding: utf-8 -*-
"""
SwathProfile4QGIS - Swath Profile Plugin for QGIS
Generates swath profiles with offset-line sampling or zonal statistics.
"""


def classFactory(iface):
    from .swath4qgis import Swath4QGIS
    return Swath4QGIS(iface)
