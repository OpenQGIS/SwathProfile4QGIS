# -*- coding: utf-8 -*-
"""
Bilingual (zh / en) helper.  Detects the QGIS user locale once at import time.
Usage::

    from .i18n import tr
    label.setText(tr("条带宽度", "Strip width"))
"""

import locale
from qgis.core import QgsSettings

# Try multiple locale detection methods
_LOCALE = ""

# Method 1: QgsSettings
try:
    _LOCALE = QgsSettings().value("locale/userLocale", "")
except Exception:
    _LOCALE = ""

# Method 2: System locale (fallback)
if not _LOCALE:
    try:
        _LOCALE = locale.getdefaultlocale()[0] or ""
    except Exception:
        _LOCALE = ""

# Method 3: Environment variable (fallback)
if not _LOCALE:
    import os
    _LOCALE = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")

_CHINESE = bool(_LOCALE and _LOCALE[:2].lower() == "zh")


def tr(zh, en, disambiguation=None):
    """Translate text using QCoreApplication.translate with SwathProfile4QGIS context.
    Falls back to inline Chinese/English check if no translation is loaded.
    """
    try:
        from qgis.PyQt.QtCore import QCoreApplication
        translated = QCoreApplication.translate("SwathProfile4QGIS", en, disambiguation)
        if translated and translated != en:
            return translated
    except Exception:
        return zh if _CHINESE else en

    return zh if _CHINESE else en
