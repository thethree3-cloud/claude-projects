"""Parametric spec-sheet diagram for a configured deep-drawn box.

Draws to scale from the actual dimensions/gauge -- no AI image generation,
so the picture always matches the numbers exactly. Same approach as
case_configurator/diagram.py, adapted for this catalog's real shape: an
open-top shell (no lid unless a cover is selected) with real bottom/side
corner radii (R1/R2) instead of sharp corners.
"""

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

from deep_draw_pricing import nutplate_count

EDGE_COLOR = "#2b2b2b"
OPEN_TOP_COLOR = "#dcdcdc"
COVER_COLOR = "#8a8f94"
NUTPLATE_COLOR = "#3a3a3a"


def _rounded_rect(ax, x, y, w, h, radius, **kwargs):
    radius = max(0.0, min(radius, min(w, h) / 2 - 1e-6))
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        **kwargs,
    ))


def _dim_line(ax, x0, y0, x1, y1, label, offset=0.0, vertical=False):
    ax.annotate(
        "", xy=(x1, y1), xytext=(x0, y0),
        arrowprops=dict(arrowstyle="<->", color="#444444", lw=1.4),
    )
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    if vertical:
        ax.text(mx + offset, my, label, rotation=90, va="center", ha="center",
                 fontsize=13, fontweight="bold", color="#222222")
    else:
        ax.text(mx, my + offset, label, va="center", ha="center",
                 fontsize=13, fontweight="bold", color="#222222")


def _elevation_panel(ax, span, height, r2_in, color_hex, cover_type, title):
    _rounded_rect(ax, 0, 0, span, height, r2_in, facecolor=color_hex, edgecolor=EDGE_COLOR, lw=2)

    if cover_type == "none":
        # Open top: show a lighter "peek into the interior" band at the rim.
        peek_h = height * 0.08
        ax.add_patch(Rectangle((r2_in * 0.6, height - peek_h), span - r2_in * 1.2, peek_h,
                                facecolor=OPEN_TOP_COLOR, edgecolor="none"))
        ax.plot([r2_in * 0.6, span - r2_in * 0.6], [height, height], color=EDGE_COLOR, lw=1, linestyle="--")
    else:
        # Covered: draw a lid cap sitting on top, slightly overhanging.
        overhang = span * 0.03
        cap_h = height * 0.06
        ax.add_patch(Rectangle((-overhang, height), span + 2 * overhang, cap_h,
                                facecolor=COVER_COLOR, edgecolor=EDGE_COLOR, lw=1.2))

    _dim_line(ax, 0, -height * 0.14, span, -height * 0.14, f'{span:g}"')
    _dim_line(ax, -span * 0.14, 0, -span * 0.14, height, f'{height:g}"', vertical=True)

    ax.set_xlim(-span * 0.3, span * 1.12)
    ax.set_ylim(-height * 0.3, height * 1.25)
    ax.set_title(title, fontsize=13, fontweight="bold")


def _top_panel(ax, width_in, length_in, r2_in, color_hex, nutplate_pattern):
    _rounded_rect(ax, 0, 0, width_in, length_in, r2_in, facecolor=OPEN_TOP_COLOR, edgecolor=EDGE_COLOR, lw=2)
    inset = min(width_in, length_in) * 0.04
    _rounded_rect(ax, inset, inset, width_in - 2 * inset, length_in - 2 * inset, max(r2_in - inset, 0),
                  facecolor=color_hex, edgecolor="none")

    if nutplate_pattern != "none":
        count = nutplate_count(width_in, length_in)
        perimeter = 2 * (width_in + length_in)
        margin = min(width_in, length_in) * 0.06
        r = min(width_in, length_in) * 0.02
        for i in range(count):
            d = (i / count) * perimeter
            if d < width_in:
                x, y = d, margin
            elif d < width_in + length_in:
                x, y = width_in - margin, d - width_in
            elif d < 2 * width_in + length_in:
                x, y = width_in - (d - width_in - length_in), length_in - margin
            else:
                x, y = margin, length_in - (d - 2 * width_in - length_in)
            ax.add_patch(Rectangle((x - r, y - r), 2 * r, 2 * r, facecolor=NUTPLATE_COLOR, zorder=5))

    _dim_line(ax, 0, -length_in * 0.15, width_in, -length_in * 0.15, f'{width_in:g}"')
    _dim_line(ax, -width_in * 0.14, 0, -width_in * 0.14, length_in, f'{length_in:g}"', vertical=True)

    ax.set_xlim(-width_in * 0.3, width_in * 1.12)
    ax.set_ylim(-length_in * 0.3, length_in * 1.12)
    ax.set_title("TOP (open)", fontsize=13, fontweight="bold")


def draw_box(width_in, length_in, height_in, r1_in, r2_in, gauge_in,
             cover_type="none", nutplate_pattern="none", color_hex="#b8bcc0"):
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.6))
    for ax in axes:
        ax.set_aspect("equal")
        ax.axis("off")

    _elevation_panel(axes[0], width_in, height_in, r2_in, color_hex, cover_type, "FRONT")
    _elevation_panel(axes[1], length_in, height_in, r2_in, color_hex, cover_type, "SIDE")
    _top_panel(axes[2], width_in, length_in, r2_in, color_hex, nutplate_pattern)

    cover_label = "no cover" if cover_type == "none" else f"{cover_type} cover"
    fig.suptitle(
        f'{width_in:g}"W x {length_in:g}"L x {height_in:g}"H  |  {gauge_in:g}" gauge  |  '
        f'R1 {r1_in:g}" / R2 {r2_in:g}"  |  {cover_label}',
        fontsize=13,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return fig
