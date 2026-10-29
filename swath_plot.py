# -*- coding: utf-8 -*-
"""
Apple-restrained plotting helpers for swath profiles.

Design principles
-----------------
* Chart is the product - controls recede.
* Single colour family - warm/cool neutrals, no rainbow.
* Fill_between for min-max envelope (no gradient, no shadow).
* THi sub-chart uses parchment background (#f5f5f7).
* Tight typography, minimal padding.
"""

import logging

logger = logging.getLogger("SwathProfile4QGIS")

# Colour palette - restrained, warm-neutral
CLR_PROFILE = "#C8C8C8"   # light grey - individual offset lines
CLR_MAX     = "#f8ba81"   # warm orange
CLR_MIN     = "#4dd48a"   # green
CLR_MEAN    = "#01008a"   # deep blue
CLR_Q       = "#008a8c"   # teal - Q1 / Q3
CLR_RELIEF  = "#cc3333"   # muted red
CLR_THI     = "#8B4513"   # chocolate
CLR_FILL    = "#666666"   # envelope fill
CLR_GRID    = "#e0e0e0"   # hairline
CLR_PARCH   = "#f5f5f7"   # parchment

LINE_W_PROFILE = 0.8
LINE_W_STAT    = 1.2
LINE_W_MEAN    = 1.5
LINE_W_THI     = 1.0
LINE_W_RELIEF  = 1.0


def apply_restrained_style(fig):
    """Apply Apple-like restrained defaults to a matplotlib Figure."""
    fig.patch.set_facecolor("white")
    fig.set_tight_layout(True)
    try:
        import matplotlib as mpl
        # Support Chinese font display (Windows common fonts) and correct minus sign display
        mpl.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun', 'DejaVu Sans', 'sans-serif']
        mpl.rcParams['axes.unicode_minus'] = False
    except Exception as e:
        logger.debug("Failed to set matplotlib defaults: %s", e)



def draw_swath_profile(ax, sp, show_profiles=True,
                       show_min=False, show_max=False,
                       show_mean=True, show_q1=False, show_q3=False,
                       show_relief=False, colors=None, y_label="Elevation"):
    """Draw the main swath profile on axes *ax*.

    Returns the *ax* for the relief overlay (or None if relief not shown).
    """
    d = sp.distances
    ax.set_facecolor("white")

    # Use custom colors/widths or defaults
    # Width conversion: 1mm = 72/25.4 ≈ 2.835 points
    MM_TO_PT = 72.0 / 25.4
    c = colors or {}
    clr_profile = c.get("color_profiles", CLR_PROFILE)
    w_profile = c.get("width_profiles", 0.3) * MM_TO_PT
    clr_min = c.get("color_min", CLR_MIN)
    w_min = c.get("width_min", 0.5) * MM_TO_PT
    clr_max = c.get("color_max", CLR_MAX)
    w_max = c.get("width_max", 0.5) * MM_TO_PT
    clr_mean = c.get("color_mean", CLR_MEAN)
    w_mean = c.get("width_mean", 0.6) * MM_TO_PT
    clr_q1 = c.get("color_q1", CLR_Q)
    w_q1 = c.get("width_q1", 0.5) * MM_TO_PT
    clr_q3 = c.get("color_q3", CLR_Q)
    w_q3 = c.get("width_q3", 0.5) * MM_TO_PT
    clr_relief = c.get("color_relief", CLR_RELIEF)
    w_relief = c.get("width_relief", 0.4) * MM_TO_PT
    clr_fill = CLR_FILL

    # ---- Individual offset profiles (background noise) ----
    if show_profiles and sp.n_profiles > 1:
        for p in sp.profile_data:
            ax.plot(d, p, color=clr_profile, linewidth=w_profile,
                    alpha=0.6, zorder=1)

    # ---- Min/Max curves ----
    if show_min and sp.min_profile is not None:
        ax.plot(d, sp.min_profile, color=clr_min, linewidth=w_min,
                label="Min", zorder=3)
    if show_max and sp.max_profile is not None:
        ax.plot(d, sp.max_profile, color=clr_max, linewidth=w_max,
                label="Max", zorder=3)
    if show_min and show_max and sp.min_profile is not None:
        ax.fill_between(d, sp.min_profile, sp.max_profile,
                        color=clr_fill, alpha=0.12, linewidth=0, zorder=2)

    # ---- Q1-Q3 envelope ----
    if (show_q1 or show_q3) and sp.q1_profile is not None:
        if show_q1 and show_q3:
            ax.fill_between(d, sp.q1_profile, sp.q3_profile,
                            color=clr_fill, alpha=0.08, linewidth=0, zorder=2)
        if show_q1:
            ax.plot(d, sp.q1_profile, color=clr_q1, linewidth=w_q1,
                    label="Q1", zorder=3)
        if show_q3:
            ax.plot(d, sp.q3_profile, color=clr_q3, linewidth=w_q3,
                    label="Q3", zorder=3)

    # ---- Mean ----
    if show_mean and sp.mean_profile is not None:
        ax.plot(d, sp.mean_profile, color=clr_mean, linewidth=w_mean,
                label="Mean", zorder=4)

    # ---- Axis styling ----

    ax.set_ylabel(y_label, fontsize=10, labelpad=4)
    ax.tick_params(labelsize=9, direction="in", length=3, width=0.6,
                   top=False, right=False)
    for spine in ax.spines.values():
        spine.set_linewidth(0.6)
        spine.set_color("#cccccc")
    ax.grid(True, color=CLR_GRID, linewidth=0.4, alpha=0.7)

    # ---- Relief on twin axis ----
    ax_relief = None
    if show_relief and sp.relief_profile is not None:
        ax_relief = ax.twinx()
        ax_relief.plot(d, sp.relief_profile, color=clr_relief,
                       linewidth=w_relief, label="Relief", zorder=2)
        ax_relief.set_ylabel("Local relief", fontsize=9, labelpad=4,
                             color=CLR_RELIEF)
        ax_relief.tick_params(axis="y", labelsize=8, colors=CLR_RELIEF,
                              direction="in", length=3, width=0.6)
        ax_relief.spines["right"].set_color(CLR_RELIEF)
        ax_relief.spines["right"].set_linewidth(0.6)
        ax_relief.spines["top"].set_visible(False)
        ax_relief.spines["bottom"].set_visible(False)
        ax_relief.spines["left"].set_visible(False)

    return ax_relief


def draw_thi_profile(ax, sp, enhanced=False, colors=None):
    """Draw the THi sub-chart on axes *ax*."""
    thi = sp.compute_thi(enhanced=enhanced)
    d = sp.distances

    c = colors or {}
    clr_thi = c.get("color_thi", CLR_THI)
    MM_TO_PT = 72.0 / 25.4
    w_thi = c.get("width_thi", 0.4) * MM_TO_PT

    ax.set_facecolor(CLR_PARCH)
    ax.plot(d, thi, color=clr_thi, linewidth=w_thi, zorder=3)

    # Reference lines
    ax.axhline(50, color="#999999", linewidth=0.6, linestyle=(0, (4, 3)), zorder=1)
    ax.axhline(25, color=CLR_GRID, linewidth=0.4, linestyle=(0, (1, 3)), zorder=1)
    ax.axhline(75, color=CLR_GRID, linewidth=0.4, linestyle=(0, (1, 3)), zorder=1)

    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("THi*", fontsize=9, labelpad=4) if enhanced else \
        ax.set_ylabel("THi", fontsize=9, labelpad=4)

    ax.tick_params(labelsize=8, direction="in", length=3, width=0.6,
                   top=False, right=False)
    for spine in ax.spines.values():
        spine.set_linewidth(0.6)
        spine.set_color("#cccccc")
    ax.grid(True, color=CLR_GRID, linewidth=0.4, alpha=0.7)


def create_profile_figure(figsize=(12, 6), dpi=100, show_thi=False):
    """Create a Figure with appropriate subplot layout.

    Returns ``(fig, ax_main, ax_thi)`` - *ax_thi* is None when
    *show_thi* is False.
    """
    from matplotlib.figure import Figure

    fig = Figure(figsize=figsize, dpi=dpi)
    apply_restrained_style(fig)

    if show_thi:
        gs = fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.08)
        ax_main = fig.add_subplot(gs[0])
        ax_thi = fig.add_subplot(gs[1], sharex=ax_main)
    else:
        ax_main = fig.add_subplot(111)
        ax_thi = None

    return fig, ax_main, ax_thi
