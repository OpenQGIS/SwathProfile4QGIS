# -*- coding: utf-8 -*-
"""
Background worker thread for swath profile computation.
"""

from qgis.core import (
    QgsExpressionContext, QgsExpressionContextUtils, QgsProject,
    QgsProperty, QgsExpressionContextScope, QgsExpression
)
from qgis.PyQt.QtCore import QObject, pyqtSignal, QThread

from .i18n import tr

# Property key constants (must match swath_param_dock.py)
PROP_STRIP_WIDTH = 0
PROP_N_PROFILES = 1
PROP_STEP_SIZE = 2


class SwathWorker(QObject):
    """Runs swath computation off the main thread.

    Signals
    -------
    progress(int, str)  - percent done, message
    finished(list, list, list, list, list) - results, geoms, fields, field_values, strip_widths
    error(str)          - human-readable error message
    """

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(list, list, list, list, list)
    error = pyqtSignal(str)

    def __init__(self, baselines, raster_layer, params, mode="offset",
                 prop_collection=None, prop_defs=None):
        """
        Parameters
        ----------
        baselines : list[QgsFeature]
            Line features to process (already in DEM CRS).
        raster_layer : QgsRasterLayer
            DEM raster.
        params : dict
            Default parameter values (strip_width, step_size, n_profiles)
        mode : str
            "offset" or "zonal"
        prop_collection : QgsPropertyCollection (optional)
            Data-defined override properties
        prop_defs : dict (optional)
            Property definitions for evaluation
        """
        super().__init__()
        self._baselines = baselines
        self._raster = raster_layer
        self._params = params
        self._mode = mode
        self._cancelled = False
        self._prop_collection = prop_collection
        self._prop_defs = prop_defs

    def cancel(self):
        self._cancelled = True

    def _evaluate_property(self, key, feature, default_value):
        """Evaluate a data-defined property for a feature with robust fallbacks."""
        if not self._prop_collection:
            return default_value

        prop = self._prop_collection.property(key)
        if not prop or not prop.isActive():
            return default_value

        # Robust Python-based direct evaluation for different property types
        ptype = prop.propertyType()

        # 1. Field-based property
        if ptype == QgsProperty.FieldBasedProperty:
            field_name = prop.field()
            if feature and field_name:
                fields = feature.fields()
                idx = fields.lookupField(field_name)
                if idx >= 0:
                    val = feature.attribute(idx)
                    if val is not None and val != "":
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            pass

        # 2. Static property
        elif ptype == QgsProperty.StaticProperty:
            val = prop.staticValue()
            if val is not None and val != "":
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass

        # 3. Expression-based property
        elif ptype == QgsProperty.ExpressionBasedProperty:
            expr_str = prop.expressionString()
            if expr_str and feature:
                expr = QgsExpression(expr_str)
                context = QgsExpressionContext()
                context.appendScope(QgsExpressionContextUtils.globalScope())
                context.appendScope(QgsExpressionContextUtils.projectScope(QgsProject.instance()))
                
                # Explicitly append a dedicated feature scope
                scope = QgsExpressionContextScope()
                scope.setFields(feature.fields())
                scope.setFeature(feature)
                context.appendScope(scope)
                
                val = expr.evaluate(context)
                if val is not None and val != "":
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        pass

        # Native QGIS valueAsDouble fallback
        try:
            context = QgsExpressionContext()
            context.appendScope(QgsExpressionContextUtils.globalScope())
            context.appendScope(QgsExpressionContextUtils.projectScope(QgsProject.instance()))
            if feature:
                scope = QgsExpressionContextScope()
                scope.setFields(feature.fields())
                scope.setFeature(feature)
                context.appendScope(scope)
            
            result = prop.valueAsDouble(context, default_value)
            return result[0] if isinstance(result, tuple) else result
        except Exception as e:
            print(f"Error in native valueAsDouble evaluation: {e}")
            return default_value

    # ------------------------------------------------------------------

    def run(self):
        from .swath_core import (
            compute_offset_profile,
            compute_zonal_profile,
            generate_perpendicular_slices,
        )
        try:
            results = []
            baseline_geoms = []
            strip_widths = []
            total = len(self._baselines)

            # Collect field names from first feature
            fields = []
            field_values = []
            if self._baselines:
                first_feat = self._baselines[0]
                fields = [field.name() for field in first_feat.fields()]
                field_values = [[] for _ in fields]

            # Pre-calculate total profiles/slices across all baselines
            total_profiles = 0
            feature_n_profiles = []
            for feat in self._baselines:
                if self._mode == "offset":
                    n_prof = int(self._evaluate_property(
                        PROP_N_PROFILES, feat, self._params.get("n_profiles", 30)
                    ))
                else:
                    geom = feat.geometry()
                    if geom is None or geom.isEmpty():
                        n_prof = 0
                    else:
                        step_size = self._evaluate_property(
                            PROP_STEP_SIZE, feat, self._params.get("step_size", 3.0)
                        )
                        slices = generate_perpendicular_slices(geom, 1.0, step_size)
                        n_prof = len(slices)
                feature_n_profiles.append(n_prof)
                total_profiles += n_prof

            for idx, feat in enumerate(self._baselines):
                if self._cancelled:
                    break

                # Collect field values
                for i, field_name in enumerate(fields):
                    try:
                        val = feat[field_name]
                        field_values[i].append(str(val) if val is not None else "")
                    except:
                        field_values[i].append("")

                try:
                    name_val = feat["Name"]
                    name = str(name_val) if name_val else f"Profile {idx + 1}"
                except (KeyError, IndexError, AttributeError):
                    name = f"Profile {idx + 1}"

                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue

                # Evaluate data-defined parameters for this feature
                strip_width = self._evaluate_property(
                    PROP_STRIP_WIDTH, feat, self._params["strip_width"]
                )
                n_profiles = int(self._evaluate_property(
                    PROP_N_PROFILES, feat, self._params.get("n_profiles", 30)
                ))
                step_size = self._evaluate_property(
                    PROP_STEP_SIZE, feat, self._params.get("step_size", 3.0)
                )

                # Calculate n_points from step size
                line_length = geom.length()
                n_points = max(2, int(line_length / step_size) + 1) if step_size > 0 else 200

                completed_profiles_before = sum(feature_n_profiles[:idx])

                def _prog(i, n):
                    pct = int((completed_profiles_before + i) / max(total_profiles, 1) * 100)
                    msg = tr(
                        f"{name}：第 {completed_profiles_before + i}/{total_profiles} 条剖面",
                        f"{name}: line {completed_profiles_before + i}/{total_profiles}"
                    )
                    self.progress.emit(pct, msg)

                if self._mode == "offset":
                    sp = compute_offset_profile(
                        geom, self._raster,
                        strip_width=strip_width,
                        n_lines=n_profiles,
                        n_points=n_points,
                        progress_cb=_prog,
                        cancel_cb=lambda: self._cancelled,
                    )
                else:
                    sp = compute_zonal_profile(
                        geom, self._raster,
                        swath_width=strip_width,
                        sample_interval=step_size,
                        progress_cb=_prog,
                    )

                # Check if cancelled during computation
                if sp is None:
                    break

                sp.name = name
                results.append(sp)
                baseline_geoms.append(geom)
                strip_widths.append(strip_width)
                
                completed_profiles_so_far = sum(feature_n_profiles[:idx + 1])
                pct = int(completed_profiles_so_far / max(total_profiles, 1) * 100)
                self.progress.emit(pct, name)

            self.finished.emit(results, baseline_geoms, fields, field_values, strip_widths)

        except Exception as exc:
            self.error.emit(str(exc))
