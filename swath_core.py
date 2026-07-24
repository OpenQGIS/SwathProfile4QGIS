# -*- coding: utf-8 -*-
"""
Core swath-profile algorithms.

Two sampling modes are supported:

* **Offset-line mode** – generate parallel offset lines along a baseline,
  sample the DEM at each point, then compute per-position statistics
  (min, max, mean, Q1, Q3, relief, HI, THi).  Mirrors the ArcGIS
  SwathProfiler behaviour.

* **Zonal-statistics mode** – place perpendicular rectangular slices along
  the baseline, use ``QgsZonalStatistics`` to summarise the DEM within
  each slice.  Mirrors the QGIS swathProfile plugin approach.

Both modes produce a ``SwathProfile`` object that carries the computed
arrays and can be handed directly to the plotting module.
"""

import math
import numpy as np

from qgis.core import (
    Qgis,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateTransform,
    QgsProject,
    QgsFeature,
    QgsField,
    QgsVectorLayer,
)
from qgis.analysis import QgsZonalStatistics
from qgis.PyQt.QtCore import QVariant


# ======================================================================
# SwathProfile data container
# ======================================================================

class SwathProfile:
    """Holds all data for a single swath profile along one baseline."""

    def __init__(self, profile_data, distances, name="Swath profile"):
        """
        Parameters
        ----------
        profile_data : list[np.ndarray]
            Elevation arrays for each offset line / slice.
            Each array has the same length as *distances*.
        distances : np.ndarray
            1-D array of cumulative distances along the baseline.
        name : str
            Human-readable profile name.
        """
        self.name = name
        self.distances = np.asarray(distances, dtype=np.float64)
        self.profile_data = [np.asarray(p, dtype=np.float64) for p in profile_data]
        self.n_profiles = len(self.profile_data)

        # Derived statistics (populated by _compute_statistics)
        self.min_profile = None
        self.max_profile = None
        self.mean_profile = None
        self.q1_profile = None
        self.q3_profile = None
        self.relief_profile = None
        self.hi_profile = None
        self.max_relief = 0.0

        self._compute_statistics()

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def _compute_statistics(self):
        n_pts = len(self.distances)
        if n_pts == 0 or self.n_profiles == 0:
            return

        # Stack all profiles into a 2-D array  (n_profiles x n_points)
        stacked = np.vstack(self.profile_data)

        self.min_profile = np.nanmin(stacked, axis=0)
        self.max_profile = np.nanmax(stacked, axis=0)
        self.mean_profile = np.nanmean(stacked, axis=0)

        # Quartiles - match the ArcGIS position-based interpolation:
        #   q1_index = (N+1)/4,  q3_index = 3*(N+1)/4
        sorted_vals = np.sort(stacked, axis=0)
        n = self.n_profiles

        def _vectorized_percentile_pos(sorted_matrix, frac_index):
            """Interpolate at a fractional index across all points simultaneously."""
            if frac_index < 0:
                return sorted_matrix[0, :]
            if frac_index >= n - 1:
                return sorted_matrix[-1, :]
            lo = int(frac_index)
            frac = frac_index - lo
            if frac == 0:
                return sorted_matrix[lo, :]
            return sorted_matrix[lo, :] * (1.0 - frac) + sorted_matrix[lo + 1, :] * frac

        q1_idx = (n + 1) / 4.0 - 1.0   # convert to 0-based
        q3_idx = 3.0 * (n + 1) / 4.0 - 1.0

        self.q1_profile = _vectorized_percentile_pos(sorted_vals, q1_idx)
        self.q3_profile = _vectorized_percentile_pos(sorted_vals, q3_idx)

        # Relief and Hypsometric Integral
        self.relief_profile = self.max_profile - self.min_profile
        self.max_relief = float(np.nanmax(self.relief_profile)) if n_pts else 0.0

        denom = self.max_profile - self.min_profile
        safe_denom = np.where(denom == 0, 1e-5, denom)
        self.hi_profile = (self.mean_profile - self.min_profile) / safe_denom

    # ------------------------------------------------------------------
    # THi computation
    # ------------------------------------------------------------------

    def compute_thi(self, enhanced=False):
        """Return the THi profile array.

        Parameters
        ----------
        enhanced : bool
            If True, rescale HI from [0.2, 0.8] to [0, 1] before applying
            the relief-based modulation (THi*).
        """
        if self.hi_profile is None or self.max_relief == 0:
            return np.zeros_like(self.distances)

        hi = self.hi_profile.copy()
        if enhanced:
            hi = (hi - 0.2) / 0.6
            hi = np.clip(hi, 0.0, 1.0)

        # Factor: 0.2 * ln(relief / max_relief) + 1
        ratio = np.where(
            self.relief_profile > 0,
            self.relief_profile / self.max_relief,
            1e-10,
        )
        factor = 0.2 * np.log(ratio) + 1.0

        thi = ((hi - 0.5) * factor + 0.5) * 100.0
        return thi

    def smoothed(self, window_size=9):
        """Return a new SwathProfile with smoothed profile_data.

        Window size must be an odd integer >= 5.
        """
        if window_size % 2 == 0:
            window_size += 1
        if window_size < 5:
            window_size = 5

        smoothed_data = []
        for p in self.profile_data:
            smoothed_p = self._apply_sg_filter(p, window_size)
            smoothed_data.append(smoothed_p)

        return SwathProfile(smoothed_data, self.distances, self.name)

    def _apply_sg_filter(self, y, window_size):
        if len(y) < window_size:
            return y.copy()

        # Handle nan elements by interpolating them first, so nans don't propagate.
        nans = np.isnan(y)
        if np.all(nans):
            return y.copy()

        y_filled = y.copy()
        if np.any(nans):
            x = np.arange(len(y))
            non_nan_indices = x[~nans]
            non_nan_values = y[~nans]
            y_filled[nans] = np.interp(x[nans], non_nan_indices, non_nan_values)

        try:
            # Try importing scipy for Savitzky-Golay filtering
            from scipy.signal import savgol_filter
            polyorder = min(3, window_size - 2)
            if polyorder < 1:
                polyorder = 1
            smoothed = savgol_filter(y_filled, window_size, polyorder, mode='interp')
        except Exception:
            # Fallback to pure numpy moving average
            box = np.ones(window_size) / window_size
            pad_width = window_size // 2
            padded = np.pad(y_filled, pad_width, mode='edge')
            smoothed = np.convolve(padded, box, mode='valid')

        # Re-inject nan at the original positions to maintain exact out-of-bounds/nodata coverage
        smoothed[nans] = np.nan
        return smoothed



# ======================================================================
# Mode A - Offset-line sampling
# ======================================================================

def _interpolate_polyline(line_geom, distances):
    """Fast vectorized interpolation along a polyline.
    line_geom: QgsGeometry
    distances: 1D np.ndarray of distances from start
    Returns: np.ndarray of shape (N, 2) with [x, y] coordinates.
    """
    if line_geom.isMultipart():
        parts = line_geom.asMultiPolyline()
        pts = parts[0] if parts else []
    else:
        pts = line_geom.asPolyline()
    if not pts:
        return np.zeros((len(distances), 2))
    
    xy = np.array([[pt.x(), pt.y()] for pt in pts])
    dx = np.diff(xy[:, 0])
    dy = np.diff(xy[:, 1])
    seg_lengths = np.hypot(dx, dy)
    cum_dist = np.insert(np.cumsum(seg_lengths), 0, 0.0)
    
    interp_x = np.interp(distances, cum_dist, xy[:, 0])
    interp_y = np.interp(distances, cum_dist, xy[:, 1])
    return np.column_stack((interp_x, interp_y))


def generate_offset_lines(geometry, total_width, n_lines):
    """Generate parallel offset lines on both sides of *geometry*.

    Returns a list of exactly *n_lines* ``QgsGeometry`` objects evenly spaced
    across the *total_width*.
    """
    if n_lines <= 1:
        return [geometry]

    lines = []
    offsets = np.linspace(-total_width / 2.0, total_width / 2.0, n_lines)

    for dist in offsets:
        if abs(dist) < 1e-5:
            lines.append(geometry)
        else:
            offset = geometry.offsetCurve(dist, 8, Qgis.JoinStyle.Round, 10.0)
            if offset and not offset.isEmpty():
                lines.append(offset)

    return lines


def sample_dem_along_line(line_geom, raster_layer, n_points,
                          transform=None):
    """Sample *raster_layer* at *n_points* evenly spaced along *line_geom*.

    Returns ``(distances, elevations)`` as numpy arrays.
    *transform* is an optional ``QgsCoordinateTransform`` from the project
    CRS to the raster CRS.
    """
    provider = raster_layer.dataProvider()
    length = line_geom.length()
    if length <= 0 or n_points < 2:
        return np.array([0.0]), np.array([0.0])

    distances = np.linspace(0.0, length, n_points)
    elevations = np.full(n_points, np.nan)

    # Fast vectorized geometry interpolation
    xy = _interpolate_polyline(line_geom, distances)

    nodata = provider.sourceNoDataValue(1)

    for i in range(n_points):
        pt = QgsPointXY(float(xy[i, 0]), float(xy[i, 1]))
        if transform is not None:
            pt = transform.transform(pt)

        val, ok = provider.sample(pt, 1)
        if ok and val is not None:
            try:
                v = float(val)
                # Ensure it's not NaN, not NoData, and within a reasonable range
                if not math.isnan(v) and v != nodata and abs(v) < 1e10:
                    elevations[i] = v
            except (TypeError, ValueError):
                pass

    return distances, elevations


def check_coverage(baseline_geom, half_width, raster_extent):
    """Verify that the swath band falls within *raster_extent*.

    Constructs offset lines at +-*half_width* and checks that their
    endpoints are inside the raster envelope.
    """
    for sign in (1.0, -1.0):
        offset = baseline_geom.offsetCurve(half_width * sign, 8, Qgis.JoinStyle.Round, 10.0)
        if offset is None or offset.isEmpty():
            return False
        for pt in (offset.interpolate(0).asPoint(),
                   offset.interpolate(offset.length()).asPoint()):
            if (pt.x() > raster_extent.xMaximum() or
                pt.x() < raster_extent.xMinimum() or
                pt.y() > raster_extent.yMaximum() or
                pt.y() < raster_extent.yMinimum()):
                return False
    return True


def compute_offset_profile(baseline_geom, raster_layer, strip_width,
                           n_lines, n_points, transform=None,
                           progress_cb=None, cancel_cb=None):
    """Full offset-line swath computation for one baseline.

    Returns a ``SwathProfile`` or None if cancelled.
    """
    length = baseline_geom.length()
    if length <= 0 or n_points < 2:
        return SwathProfile([np.array([0.0])], np.array([0.0]))
        
    distances = np.linspace(0.0, length, n_points)

    # Generate and sample offset lines
    offset_lines = generate_offset_lines(baseline_geom, strip_width, n_lines)
    profile_data = []

    total = len(offset_lines)
    for idx, line in enumerate(offset_lines, 1):
        # Check cancellation
        if cancel_cb and cancel_cb():
            return None
        _, elev = sample_dem_along_line(line, raster_layer, n_points, transform)
        profile_data.append(elev)
        if progress_cb:
            progress_cb(idx, total)

    return SwathProfile(profile_data, distances)


# ======================================================================
# Mode B - Perpendicular slice zonal statistics
# ======================================================================

def generate_perpendicular_slices(line_geom, swath_width, sample_interval):
    """Build perpendicular rectangular slices along *line_geom*.

    Returns a list of ``(distance, QgsGeometry)`` tuples.
    Each rectangle is centred on the line, extends +-*swath_width/2*
    perpendicular to the tangent, and +-*sample_interval/2* along it.
    """
    length = line_geom.length()
    if length <= 0 or sample_interval <= 0:
        return []

    half_interval = sample_interval / 2.0
    n_slices = max(1, int(length // sample_interval))
    slices = []

    # Vectorized computation of slice centers and tangents
    distances = half_interval + np.arange(n_slices) * sample_interval
    distances = distances[distances <= length]
    if len(distances) == 0:
        return []

    d_step = max(sample_interval / 100.0, 1e-3)
    
    p0_dist = np.maximum(0.0, distances - d_step)
    p1_dist = np.minimum(length, distances + d_step)
    
    p0_xy = _interpolate_polyline(line_geom, p0_dist)
    p1_xy = _interpolate_polyline(line_geom, p1_dist)
    cx_cy = _interpolate_polyline(line_geom, distances)
    
    dx = p1_xy[:, 0] - p0_xy[:, 0]
    dy = p1_xy[:, 1] - p0_xy[:, 1]
    seg = np.hypot(dx, dy)
    
    valid = seg > 0
    if not np.any(valid):
        return []
        
    ax = np.zeros_like(dx)
    ay = np.zeros_like(dy)
    ax[valid] = dx[valid] / seg[valid]
    ay[valid] = dy[valid] / seg[valid]
    
    px = -ay
    py = ax
    
    hw = swath_width / 2.0
    hi = half_interval

    for i in range(len(distances)):
        if not valid[i]:
            continue
            
        cx, cy = cx_cy[i, 0], cx_cy[i, 1]
        _ax, _ay = ax[i], ay[i]
        _px, _py = px[i], py[i]

        corners = [
            QgsPointXY(cx - hi * _ax + hw * _px, cy - hi * _ay + hw * _py),
            QgsPointXY(cx + hi * _ax + hw * _px, cy + hi * _ay + hw * _py),
            QgsPointXY(cx + hi * _ax - hw * _px, cy + hi * _ay - hw * _py),
            QgsPointXY(cx - hi * _ax - hw * _px, cy - hi * _ay - hw * _py),
        ]
        geom = QgsGeometry.fromPolygonXY([corners])
        slices.append((distances[i], geom))

    return slices


def compute_zonal_profile(baseline_geom, raster_layer, swath_width,
                          sample_interval, progress_cb=None):
    """Zonal-statistics swath computation for one baseline.

    Returns a ``SwathProfile`` (only min/max/mean populated; Q1/Q3/THi
    are zero-filled because zonal stats don't provide per-cell arrays).
    """
    slices = generate_perpendicular_slices(
        baseline_geom, swath_width, sample_interval
    )
    if not slices:
        return SwathProfile([], np.array([]))

    crs = raster_layer.crs()
    uri = f"Polygon?crs={crs.authid()}"
    mem_layer = QgsVectorLayer(uri, "swath_slices", "memory")
    pr = mem_layer.dataProvider()
    pr.addAttributes([
        QgsField("slice_id", QVariant.Int),
        QgsField("dist_m", QVariant.Double),
    ])
    mem_layer.updateFields()

    feats = []
    for idx, (dist, geom) in enumerate(slices):
        f = QgsFeature(mem_layer.fields())
        f.setGeometry(geom)
        f.setAttributes([idx, dist])
        feats.append(f)
    pr.addFeatures(feats)
    mem_layer.updateExtents()

    stat_flags = (
        QgsZonalStatistics.Statistic.Min
        | QgsZonalStatistics.Statistic.Max
        | QgsZonalStatistics.Statistic.Mean
        | QgsZonalStatistics.Statistic.Median
        | QgsZonalStatistics.Statistic.StDev
    )
    zs = QgsZonalStatistics(mem_layer, raster_layer, "_", 1, stat_flags)
    zs.calculateStatistics(None)

    # Read results back
    distances = []
    mins = []
    maxs = []
    means = []
    for feat in mem_layer.getFeatures():
        distances.append(feat["dist_m"])
        mins.append(float(feat["_min"]) if feat["_min"] is not None else np.nan)
        maxs.append(float(feat["_max"]) if feat["_max"] is not None else np.nan)
        means.append(float(feat["_mean"]) if feat["_mean"] is not None else np.nan)

        if progress_cb:
            progress_cb(len(distances), len(slices))

    if not distances:
        return SwathProfile([], np.array([]))

    distances = np.array(distances)
    mins = np.array(mins)
    maxs = np.array(maxs)
    means = np.array(means)

    # Build profile_data so SwathProfile can compute derived stats
    profile_data = [means]  # use mean as the "centre" profile
    sp = SwathProfile(profile_data, distances)
    # Override with zonal results
    sp.min_profile = mins
    sp.max_profile = maxs
    sp.mean_profile = means
    sp.relief_profile = maxs - mins
    sp.max_relief = float(np.nanmax(sp.relief_profile)) if len(sp.relief_profile) else 0.0
    denom = np.where((maxs - mins) == 0, 1e-5, maxs - mins)
    sp.hi_profile = (means - mins) / denom
    return sp
