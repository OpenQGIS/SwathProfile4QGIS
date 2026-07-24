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
except:
    pass

# Method 2: System locale (fallback)
if not _LOCALE:
    try:
        _LOCALE = locale.getdefaultlocale()[0] or ""
    except:
        pass

# Method 3: Environment variable (fallback)
if not _LOCALE:
    import os
    _LOCALE = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")

_CHINESE = bool(_LOCALE and _LOCALE[:2].lower() == "zh")


def tr(zh, en):
    """Return *zh* when the QGIS locale is Chinese, otherwise *en*."""
    return zh if _CHINESE else en
