"""Parametric spec-sheet diagram for a configured aluminum case.

Draws to scale from the actual dimensions/options -- no AI image generation,
so the picture always matches the numbers exactly.
"""

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle

from pricing import CaseSpec

EDGE_COLOR = "#2b2b2b"
REINFORCE_COLOR = "#4a4a4a"
BUMPER_COLOR = "#1a1a1a"
RAIL_COLOR = "#6b6b6b"


def _dim_line(ax, x0, y0, x1, y1, label, offset=0.0, vertical=False):
    ax.annotate(
        "",
        xy=(x1, y1),
        xytext=(x0, y0),
        arrowprops=dict(arrowstyle="<->", color="#555555", lw=1),
    )
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    if vertical:
        ax.text(mx + offset, my, label, rotation=90, va="center", ha="center", fontsize=9, color="#333333")
    else:
        ax.text(mx, my + offset, label, va="center", ha="center", fontsize=9, color="#333333")


def _draw_bumpers(ax, w, h, count, inset=0.08):
    corners = [(inset * w, inset * h), (w - inset * w, inset * h),
               (inset * w, h - inset * h), (w - inset * w, h - inset * h)]
    r = min(w, h) * 0.035
    for cx, cy in corners[:max(0, min(count, 4))]:
        ax.add_patch(Circle((cx, cy), r, color=BUMPER_COLOR, zorder=5))


def _front_panel(ax, spec: CaseSpec, color_hex: str):
    w, h = spec.width_in, spec.height_in
    ax.add_patch(Rectangle((0, 0), w, h, facecolor=color_hex, edgecolor=EDGE_COLOR, lw=2))

    if spec.reinforced_opening:
        margin = min(w, h) * 0.08
        ax.add_patch(Rectangle(
            (margin, margin), w - 2 * margin, h - 2 * margin,
            facecolor="none", edgecolor=REINFORCE_COLOR, lw=3,
        ))

    if spec.bumper_count:
        _draw_bumpers(ax, w, h, spec.bumper_count)

    _dim_line(ax, 0, -h * 0.12, w, -h * 0.12, f'{w:g}"')
    _dim_line(ax, -w * 0.12, 0, -w * 0.12, h, f'{h:g}"', vertical=True)

    ax.set_xlim(-w * 0.25, w * 1.1)
    ax.set_ylim(-h * 0.25, h * 1.1)
    ax.set_title("FRONT", fontsize=10, fontweight="bold")


def _side_panel(ax, spec: CaseSpec, color_hex: str):
    d, h = spec.depth_in, spec.height_in
    ax.add_patch(Rectangle((0, 0), d, h, facecolor=color_hex, edgecolor=EDGE_COLOR, lw=2))

    if spec.mounting_flanges:
        flange_w = d * 0.12
        hole_r = flange_w * 0.18
        n_holes = 6
        for fx in (0, d - flange_w):
            ax.add_patch(Rectangle((fx, 0), flange_w, h, facecolor="#cfcfcf", edgecolor=EDGE_COLOR, lw=1.2))
            for i in range(n_holes):
                hy = h * (i + 0.5) / n_holes
                ax.add_patch(Circle((fx + flange_w / 2, hy), hole_r, facecolor="white", edgecolor=EDGE_COLOR, lw=0.8))

    if spec.handle_count:
        hx, hy = d * 0.5, h * 0.5
        ax.add_patch(Rectangle((hx - d * 0.06, hy - h * 0.08), d * 0.12, h * 0.16,
                                facecolor="#3a3a3a", edgecolor=EDGE_COLOR, lw=1))

    _dim_line(ax, 0, -h * 0.12, d, -h * 0.12, f'{d:g}"')
    _dim_line(ax, -d * 0.12, 0, -d * 0.12, h, f'{h:g}"', vertical=True)

    ax.set_xlim(-d * 0.25, d * 1.1)
    ax.set_ylim(-h * 0.25, h * 1.1)
    ax.set_title("SIDE", fontsize=10, fontweight="bold")


def _top_panel(ax, spec: CaseSpec, color_hex: str):
    w, d = spec.width_in, spec.depth_in
    ax.add_patch(Rectangle((0, 0), w, d, facecolor="#e8e8e8", edgecolor=EDGE_COLOR, lw=2))

    if spec.rack_rails:
        rail_w = w * 0.06
        for rx in (w * 0.1, w - w * 0.1 - rail_w):
            ax.add_patch(Rectangle((rx, 0), rail_w, d, facecolor=RAIL_COLOR, edgecolor=EDGE_COLOR, lw=1))
            n_notch = 8
            for i in range(n_notch):
                ny = d * (i + 0.5) / n_notch
                ax.add_patch(Rectangle((rx + rail_w * 0.15, ny - d * 0.01), rail_w * 0.7, d * 0.02,
                                        facecolor="#333333"))

    _dim_line(ax, 0, -d * 0.15, w, -d * 0.15, f'{w:g}"')
    _dim_line(ax, -w * 0.12, 0, -w * 0.12, d, f'{d:g}"', vertical=True)

    ax.set_xlim(-w * 0.25, w * 1.1)
    ax.set_ylim(-d * 0.3, d * 1.1)
    ax.set_title("TOP (open)", fontsize=10, fontweight="bold")


def draw_case(spec: CaseSpec, color_hex: str = "#b8bcc0"):
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.2))
    for ax in axes:
        ax.set_aspect("equal")
        ax.axis("off")

    _front_panel(axes[0], spec, color_hex)
    _side_panel(axes[1], spec, color_hex)
    _top_panel(axes[2], spec, color_hex)

    fig.suptitle(
        f'{spec.width_in:g}"W x {spec.height_in:g}"H x {spec.depth_in:g}"D  |  {spec.material}  |  {spec.finish}',
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return fig
