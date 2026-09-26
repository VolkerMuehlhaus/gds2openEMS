########################################################################
#
# Copyright 2025-2026 Volker Muehlhaus and IHP PDK Authors
#
# Licensed under the GNU General Public License, Version 3.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.gnu.org/licenses/gpl-3.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
########################################################################

"""
editor_common.py

The stackup cross-section preview widget (VectorWidget) and its default color/label
helpers, extracted from setupEM's setup_common.py for use by this repo's own,
independent Stackup Editor. setup_common.py is a large module with a
gds2palace/gdspy/scipy/requests-heavy dependency footprint that this editor doesn't
need - this file carries over only the 4 symbols stackupEditor.py actually uses:
VectorWidget, epsilon_to_color, default_stackup_dielectric_label,
default_stackup_metal_label.

VectorWidget draws directly from resolved dielectric_layer/metal_layer/
stackup_material objects (attributes like .zmin/.zmax/.thickness/.name/.material/
.eps/.sigma/.Rs/.type/.is_via/.is_dielectric/.is_sheet/.get_planar_metals_inside()) -
these come from gds2openEMS's own util_stackup_reader.py, whose object model is
identical to gds2palace's in this respect (both readers are, in fact, byte-for-byte
identical copies as of this port - see openems_ihp_sg13g2's util_stackup_reader.py),
so no attribute-name adaptation was needed here.

The one real dependency change: the original used scipy.interpolate.interp1d(kind=
"linear", fill_value="extrapolate") for the z-to-screen-y mapping. gds2openEMS does
not depend on scipy, and pulling it in just for this one bounded linear interpolation
is unwarranted, so _linear_interp_extrapolate() below reimplements exactly that
behavior (piecewise-linear between the two nearest stored points, linear extrapolation
using the nearest two points beyond either end) without adding a new dependency.
"""

import numpy as np
import shiboken6
from PySide6.QtWidgets import (
    QWidget, QFrame, QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsRectItem,
    QToolTip, QHBoxLayout, QLabel, QComboBox,
)
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPolygonF
from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QTimer, Signal

from gds2openEMS import stackup_reader

INVALID_MATERIAL_COLOR = QColor(255, 0, 0, 80)

# Distinct from the regular conductor fill (QColor(230,230,230,90)), the resistor/sheet fill
# (QColor(230,130,130,90)), and INVALID_MATERIAL_COLOR above - a PEC layer is valid, just
# unlike any of those, so it gets its own recognizable "ideal conductor" look.
PEC_MATERIAL_COLOR = QColor(180, 220, 255, 140)


def _is_pec_material(materialname):
    """True if materialname is the reserved PEC keyword (case-insensitive) - a Layer that
       compute_stackup_layout() below must draw as an ideal conductor even though
       materials_list.get_by_name() deliberately returns None for it (see
       stackup_reader.PEC_MATERIAL_NAME).
    """
    return materialname is not None and materialname.strip().upper() == stackup_reader.PEC_MATERIAL_NAME.upper()


# ---------- STACKUP PREVIEW COLOR/LABEL DEFAULTS (permittivity-based) ------------------

def epsilon_to_color(erel, transparency):
    # Compute raw float components
    red   = 250 - 30 * (erel - 1)
    green = 255 - 20 * (erel - 1) + (20 / erel) + 10 * erel
    blue  = 100 + 15 * erel + (250 / erel)

    # Extra adjustment
    if 3.8 < erel < 4.5:
        red   += 50 * (erel - 3.8)
        green -= 100 * (erel - 3.8)

    # Clamp to range 0–255
    red   = min(max(red,   0), 255)
    green = min(max(green, 0), 255)
    blue  = min(max(blue,  0), 255)

    # Convert to integer RGB
    r = int(round(red))
    g = int(round(green))
    b = int(round(blue))

    return QColor(r, g, b, transparency)


def default_stackup_dielectric_label(dielectric, material):
    material_string = f'εr={material.eps:.1f}'
    if material.sigma > 1e-3:
        material_string = material_string + f' σ={material.sigma:.1f}'
    material_string = material_string + f'\n{dielectric.thickness:.2f}µm'
    return material_string


def default_stackup_metal_label(metal, material, is_sheet):
    if is_sheet:
        # sheet Rs is given in Ohm (per square) - same mΩ/Ω formatting as below
        if material.Rs < 1:
            return f'Rs={material.Rs*1e3:.1f} mΩ'
        else:
            return f'Rs={material.Rs:.2f} Ω'
    else:
        if (material.sigma > 0) and (metal.thickness > 0):
            Rs = 1 / (material.sigma*metal.thickness*1e-6)
            if Rs < 1:
                return f'Rs={Rs*1e3:.1f} mΩ'
            else:
                return f'Rs={Rs:.2f} Ω'
        else:
            return '? ' + material.type + ' ?'


# ---------- linear interpolation/extrapolation (scipy-free replacement for
#             interp1d(kind="linear", fill_value="extrapolate")) ------------------

class _LinearInterpExtrapolate:
    """Callable piecewise-linear interpolator over sorted (x, y) points, with linear
       extrapolation beyond either end - a drop-in replacement for
       scipy.interpolate.interp1d(x, y, kind="linear", fill_value="extrapolate") for the
       one bounded use VectorWidget needs (mapping a stackup z position to a screen y
       coordinate), so this module has no scipy dependency.
    Args:
        x_sorted (numpy.ndarray): x values, strictly sorted ascending, len >= 2
        y_sorted (numpy.ndarray): corresponding y values, same length as x_sorted
    """

    def __init__(self, x_sorted, y_sorted):
        self.x_sorted = x_sorted
        self.y_sorted = y_sorted

    def __call__(self, x_query):
        x_sorted = self.x_sorted
        y_sorted = self.y_sorted
        if x_query <= x_sorted[0]:
            x0, x1, y0, y1 = x_sorted[0], x_sorted[1], y_sorted[0], y_sorted[1]
        elif x_query >= x_sorted[-1]:
            x0, x1, y0, y1 = x_sorted[-2], x_sorted[-1], y_sorted[-2], y_sorted[-1]
        else:
            idx = int(np.searchsorted(x_sorted, x_query))
            x0, x1, y0, y1 = x_sorted[idx - 1], x_sorted[idx], y_sorted[idx - 1], y_sorted[idx]
        if x1 == x0:
            return y0
        t = (x_query - x0) / (x1 - x0)
        return y0 + t * (y1 - y0)


# ---------- POP UP WINDOW TO SHOW STACKUP ------------------

def _build_dielectric_tooltip(dielectric, overlap_partner_names=None):
    tooltip = (
        f"{dielectric.name}\n"
        f"Type: Dielectric\n"
        f"Material: {dielectric.material}\n"
        f"Zmin: {dielectric.zmin:.4f} µm\n"
        f"Zmax: {dielectric.zmax:.4f} µm\n"
        f"Thickness: {dielectric.thickness:.4f} µm"
    )
    if overlap_partner_names:
        # see dielectric_layers_list.find_z_overlap_pairs() / InteractiveRegionItem's
        # always-on red dashed outline - names exactly what this slab conflicts with,
        # so clicking the highlighted shape immediately explains why it's highlighted
        tooltip += "\n⚠ Overlaps: " + ", ".join(overlap_partner_names)
    return tooltip


def _build_layer_tooltip(metal):
    lines = [
        f"{metal.name} (GDSII layer {metal.layernum})",
        f"Type: {metal.type.capitalize()}",
        f"Material: {metal.material}",
        f"Zmin: {metal.zmin:.4f} µm",
        f"Zmax: {metal.zmax:.4f} µm",
    ]
    if not metal.is_sheet:
        lines.append(f"Thickness: {metal.thickness:.4f} µm")
    return "\n".join(lines)


def compute_stackup_layout(materials_list, dielectrics_list, metals_list, width, height,
                            dielectric_color_fn, dielectric_label_fn,
                            metal_label_fn, via_label_suffix_fn,
                            active_chiplet_id=None):
    """Pure layout computation for the stackup cross-section preview - no QPainter/
    widget/scene involved. Returns (draw_calls, interactive_entries):

    draw_calls: an ordered list of (QPainter method name, args) tuples. Replaying them
    in order (see render_stackup_layout()) reproduces exactly what the previous
    QWidget/paintEvent-based VectorWidget drew directly - this function is a mechanical
    move of that drawing code (same loop structure, same schematic layout math: dielectric
    slab height by metal-level count rather than physical thickness, same-zmin metals split
    side by side, linear-interpolated via/drawn-dielectric placement, rotating via x-slots),
    not a re-derivation of it, specifically to avoid subtly changing the visual layout.

    interactive_entries: one {"kind": "dielectric"|"layer", "key": name, "rect": QRectF,
    "ref": dielectric_layer/metal_layer, "tooltip": str, "chiplet_id": str|None} dict per
    dielectric slab, metal, or via box - used to build the transparent hoverable/selectable
    overlay items. "key" is always the element's Name (unique *within one chiplet's shown
    subtree plus the interposer* - not guaranteed unique across different chiplets, which is
    why VectorWidget's selection keying includes "chiplet_id" too), matching what the stackup
    editor's row_elements look up by. "chiplet_id" is None for an interposer-sourced entry,
    else the currently active chiplet's id (see active_chiplet_id below).

    active_chiplet_id (str, optional): which chiplet (dielectrics_list.chiplet_groups.chiplets[i].id)
    to show, for a stackup where detect_chiplet_groups() found more than one chiplet sharing a
    common interposer base - the interposer's own Dielectrics/Layers are always shown in
    addition, regardless of this argument. None picks the first detected chiplet. Ignored
    (as if no chiplets existed) when dielectrics_list.chiplet_groups is missing or has no
    chiplets - the ordinary, non-chiplet case, which renders exactly as before this parameter
    was added.
    """
    draw_calls = []
    interactive_entries = []

    # chiplet-aware filtering: with no branching detected (the ordinary case) or no
    # chiplet_groups at all (e.g. an in-memory dielectrics_list built by hand rather than via
    # read_substrate()/parse_substrate()), dielectrics_source/visible_layers preserve exactly
    # today's behavior - every dielectric/metal is shown, nothing is filtered.
    chiplet_groups = getattr(dielectrics_list, "chiplet_groups", None)
    dielectrics_source = dielectrics_list.dielectrics
    visible_layers = None   # None = no filtering; a set means "only these metals are visible"
    active_chiplet = None
    if chiplet_groups is not None and chiplet_groups.chiplets:
        active_chiplet = next((c for c in chiplet_groups.chiplets if c.id == active_chiplet_id),
                               chiplet_groups.chiplets[0])
        visible_dielectrics = set(chiplet_groups.interposer_dielectrics) | set(active_chiplet.dielectrics)
        visible_layers = set(chiplet_groups.interposer_layers) | set(active_chiplet.layers)
        dielectrics_source = [d for d in dielectrics_list.dielectrics if d in visible_dielectrics]

    def entry_chiplet_id(dielectric_or_metal):
        # None (interposer) unless this element is part of the currently active chiplet's
        # own subtree - deliberately checked by identity against the active chiplet's own
        # lists rather than just "a chiplet exists", so an interposer-sourced entry (shown
        # alongside the active chiplet) still correctly gets None
        if active_chiplet is None:
            return None
        if dielectric_or_metal in active_chiplet.dielectrics or dielectric_or_metal in active_chiplet.layers:
            return active_chiplet.id
        return None

    # dielectrics involved in an unexpected same-scope z-overlap (see
    # dielectric_layers_list.find_z_overlap_pairs()) - drawn with a red dashed outline
    # (InteractiveRegionItem._OVERLAP_PEN) regardless of the current chiplet selection, so
    # the problem is visible without having to switch to whichever chiplet happens to be
    # involved. Keyed by name (not object identity) to match dielectric_or_metal.name
    # elsewhere in this function; overlap_partners_by_name additionally names *which*
    # dielectric(s) it conflicts with, for the tooltip.
    overlap_partners_by_name = {}
    for a, b in dielectrics_list.find_z_overlap_pairs():
        overlap_partners_by_name.setdefault(a.name, []).append(b.name)
        overlap_partners_by_name.setdefault(b.name, []).append(a.name)

    # utility: flip y to have y=0 at bottom
    def flipy(y):
        return height - y

    def setPen(pen):
        draw_calls.append(("setPen", (pen,)))

    def setBrush(brush):
        draw_calls.append(("setBrush", (brush,)))

    def drawRect(x, y, w, h):
        draw_calls.append(("drawRect", (x, y, w, h)))

    def drawLine(x1, y1, x2, y2):
        draw_calls.append(("drawLine", (x1, y1, x2, y2)))

    def drawTextAt(x, y, text):
        draw_calls.append(("drawText", (x, y, text)))

    # utility to draw text with alignment on right side
    def drawText_right(x, y, w, h, text):
        rect = QRect(x, y - h, w, h)
        draw_calls.append(("drawText", (rect, Qt.AlignVCenter | Qt.AlignRight, text)))

    def drawText_left(x, y, w, h, text):
        rect = QRect(x, y - h, w, h)
        draw_calls.append(("drawText", (rect, Qt.AlignVCenter | Qt.AlignLeft, text)))

    # other chiplets sharing the active one's branch point (interposer dielectric) -
    # non-empty exactly when there's a sibling chiplet not currently shown, which is
    # when the "something sits beside this" gutter/stub below applies
    sibling_chiplets = []
    if active_chiplet is not None:
        sibling_chiplets = [c for c in chiplet_groups.chiplets
                            if c is not active_chiplet and c.branch_point is active_chiplet.branch_point]

    xmin = int(width * 0.02)
    # sibling-chiplet stub geometry, decided here (not down where it's drawn) since
    # xmax itself needs to leave exactly enough room for it - a fixed size relative
    # to width, not "whatever's left of a separately-chosen gutter", so there's no
    # left-over dead space between the stub and the canvas edge
    STUB_WIDTH = int(width * 0.06)
    STUB_RIGHT_MARGIN = int(width * 0.02)
    # narrow the whole drawing slightly (a touch more on the right) to leave room for
    # the sibling-chiplet stub below - applied globally (not just to the active
    # chiplet's own rows) so every x-coordinate downstream (slab width, metal
    # x-splits, via slots, text placement) stays consistent with no other change
    xmax = int(width - STUB_WIDTH - STUB_RIGHT_MARGIN) if sibling_chiplets else int(width * 0.98)

    ymin = int(height * 0.025)
    ymax = int(height * 0.975)

    penBlack = QPen(Qt.black, 1)
    penGray = QPen(QColor(134, 132, 130))
    penDarkGray = QPen(QColor(53, 50, 47))

    # get total dielectric parts, where each metal in a dielectric adds one part
    dielectric_shapes = []
    total_parts = 0
    # sorted by resolved zmin, not just reversed file/array order: a Reference-based
    # dielectric's actual position comes from resolving its Reference by name (see
    # dielectric_layers_list.resolve_references()), entirely independent of where it
    # sits in the file - so reordering it there (e.g. Move Up/Down in the Dielectric
    # Stack tab) must not change where it's drawn here, even though it does change
    # dielectrics_list.dielectrics' own array order
    dielectrics_bottom_up = sorted(dielectrics_source, key=lambda d: d.zmin)
    for dielectric in dielectrics_bottom_up:  # bottom up
        setPen(penBlack)

        metals_inside = dielectric.get_planar_metals_inside()
        # get number of unique zmin values in that list
        zmin_list = []
        for metal in metals_inside:
            if not metal.zmin in zmin_list:
                zmin_list.append(metal.zmin)
        metals_count = len(zmin_list)

        # first metal not aligned with dielectric?
        if len(metals_inside) > 0:
            if metals_inside[0].zmin > dielectric.zmin:
                metals_count = metals_count + 0.5

        parts = max(1, metals_count)
        dielectric_shape = {}
        dielectric_shape['name'] = dielectric.name
        dielectric_shape['dielectric'] = dielectric
        dielectric_shape['numparts'] = parts

        materialname = dielectric.material
        material = materials_list.get_by_name(materialname)
        if material is not None:
            # dielectric color/label are app-specific (permittivity vs. thermal conductivity)
            dielectric_shape['color'] = dielectric_color_fn(material)
        else:
            # unresolved Material reference (typo, or a transient state while the user is
            # still typing a new value in the editor) - PEC is never valid here (rejected by
            # stackup_writer.validate_stackup()), so this is always a genuine error, unlike
            # the metal/sheet branch below which also has a legitimate PEC case to handle
            dielectric_shape['color'] = INVALID_MATERIAL_COLOR
        dielectric_shape['material'] = material

        total_parts = total_parts + parts
        dielectric_shapes.append(dielectric_shape)

    # calculate height of one dielectric shape
    total_parts = max(total_parts, 1)
    part_height = int((ymax - ymin) / (total_parts))

    y = ymin
    w = xmax - xmin

    # we need to store data for original z position and the displayed y position
    stored_z = np.array([0])
    stored_y = np.array([ymin])

    for dielectric_shape in dielectric_shapes:
        h = part_height * dielectric_shape['numparts']
        dielectric = dielectric_shape['dielectric']
        color = dielectric_shape['color']
        material = dielectric_shape['material']

        if material is not None:
            material_string = dielectric_label_fn(dielectric, material)
        else:
            material_string = 'INVALID MATERIAL REFERENCE: ' + dielectric.material

        # adaptive left margin for this dielectric's metal boxes/side-labels: the
        # dielectric name is drawn at xmin+5, and the per-metal "distance to
        # boundary" labels below default to starting at xmetal-60 - for a short
        # name (the common case, e.g. "SiO2"/"EPI") that's already well clear of
        # the default xmin+120 metal-box margin, but a longer name (e.g. an
        # auto-generated chiplet dielectric name) can run into that label and
        # visually merge with it, especially in a short slab with few rows where
        # the name's own vertically-centered position lands on the same row as
        # one of those labels. Estimating the name's rendered width and widening
        # the margin only when needed keeps every existing short-name stackup
        # pixel-identical while fixing the long-name case generally, rather than
        # special-casing this one dielectric. A plain character-count estimate
        # (not QFontMetrics) deliberately keeps this function usable with no
        # QApplication/QGuiApplication instance yet constructed - QFontMetrics
        # requires one and otherwise crashes the process outright (not a
        # catchable Python exception).
        name_width = len(dielectric.name) * 7 + 10
        metal_box_left_margin = max(120, name_width + 75)
        extra_margin = metal_box_left_margin - 120

        setPen(penBlack)
        setBrush(color)
        drawRect(xmin, flipy(y), w, -h)
        interactive_entries.append({
            "kind": "dielectric",
            "key": dielectric.name,
            "rect": QRectF(xmin, flipy(y), w, -h).normalized(),
            "ref": dielectric,
            "tooltip": _build_dielectric_tooltip(dielectric, overlap_partners_by_name.get(dielectric.name)),
            "chiplet_id": entry_chiplet_id(dielectric),
            "has_overlap": dielectric.name in overlap_partners_by_name,
        })
        drawText_left(xmin + 5, flipy(y), w, h, dielectric.name)
        drawText_right(xmin, flipy(y), w - 5, h, material_string)

        if not dielectric.zmax in stored_z:
            stored_z = np.append(stored_z, dielectric.zmax)
            stored_y = np.append(stored_y, y + h)

        # get metals inside this dielectric
        metals_inside = dielectric.get_planar_metals_inside()
        # height for one dielectric segment including one metal is part_height
        if len(metals_inside) > 0:

            # there could be multiple metals starting at the same zmin: group them, so
            # that 3 or more of them (e.g. several resistor sheets on top of Activ) can
            # be drawn side by side in equal slots instead of on top of each other.
            # 1 or 2 per zmin keep their original full-width/left-right-half layout.
            same_zmin_slot = []  # (slot index, group size) per metals_inside entry
            group_start = 0
            for n in range(1, len(metals_inside) + 1):
                if n == len(metals_inside) or abs(metals_inside[n].zmin - metals_inside[group_start].zmin) >= 0.001:
                    for i in range(n - group_start):
                        same_zmin_slot.append((i, n - group_start))
                    group_start = n
            crowded_detail_level = {}  # group's first index -> (label detail level, text width)

            # draw planar metals, one after another
            ymetal = y
            for n, metal in enumerate(metals_inside):

                setPen(penBlack)

                # check if metal is aligned with dielectric zmin
                elevation = metal.zmin - dielectric.zmin
                if n == 0 and (abs(elevation) > 0.001):
                    # draw some vertical offset, not aligned with dielectric
                    ymetal = ymetal + part_height * 0.5  # slight offset

                # check if next metal is at same zmin
                next_at_same_zmin = False
                previous_at_same_zmin = False
                xmetal = xmin + metal_box_left_margin
                wmetal = w - 200 - extra_margin

                if n < len(metals_inside) - 1:
                    next_metal = metals_inside[n + 1]
                    if abs(next_metal.zmin - metal.zmin) < 0.001:
                        next_at_same_zmin = True
                        xmetal = xmin + metal_box_left_margin
                        wmetal = int(w / 2) - 100 - extra_margin
                else:
                    next_metal = None

                # for the "distance to metal above" label below: several metals
                # can share this zmin (e.g. sheet resistors drawn side by side),
                # so skip past all of them to the first one that's actually at a
                # different (higher) zmin - next_metal above is only the very next
                # list entry, which for a same-zmin sibling would wrongly give 0
                next_metal_above = None
                for candidate in metals_inside[n + 1:]:
                    if abs(candidate.zmin - metal.zmin) >= 0.001:
                        next_metal_above = candidate
                        break

                if n > 0:
                    previous_metal = metals_inside[n - 1]
                    if abs(previous_metal.zmin - metal.zmin) < 0.001:
                        xmetal = xmin + int(w / 2) + 20
                        wmetal = int(w / 2) - 100
                        previous_at_same_zmin = True

                # 3 or more metals at this zmin: equal slots across the span a single
                # full-width box uses, with a small gap between them
                slot_index, slot_count = same_zmin_slot[n]
                crowded = slot_count >= 3
                if crowded:
                    slot_gap = 20
                    span_start = xmin + metal_box_left_margin
                    span = (xmin + w - 80) - span_start
                    wmetal = (span - slot_gap * (slot_count - 1)) / slot_count
                    xmetal = span_start + slot_index * (wmetal + slot_gap)
                # left-side tick lines/labels: only for the first slot of a crowded
                # row - for the others, xmetal - 60 lands inside the slot left of it
                draw_side_ticks = not (crowded and slot_index > 0)

                material = materials_list.get_by_name(metal.material)
                if material is not None:
                    if metal.is_sheet:
                        # sheet metal that is simulated with zero extrusion
                        # (named height_box, not height, to avoid shadowing the
                        # outer "height" parameter that flipy() closes over)
                        height_box = 3
                        label_string = metal_label_fn(metal, material, True)
                    else:
                        # regular extruded metal
                        height_box = part_height / 2
                        label_string = metal_label_fn(metal, material, False)

                    # the box for this metal
                    if material.type.upper() == "CONDUCTOR":
                        setBrush(QColor(230, 230, 230, 90))
                        drawRect(xmetal, flipy(ymetal), wmetal, -int(height_box))
                    else:
                        setBrush(QColor(230, 130, 130, 90))
                        drawRect(xmetal, flipy(ymetal), wmetal, -int(height_box))
                elif _is_pec_material(metal.material):
                    # reserved PEC keyword: valid (no <Materials> entry needed/expected -
                    # materials_list.get_by_name() deliberately returns None for it), draw as
                    # an ideal conductor instead of falling into the invalid-reference case below
                    height_box = 3 if metal.is_sheet else part_height / 2
                    setBrush(PEC_MATERIAL_COLOR)
                    drawRect(xmetal, flipy(ymetal), wmetal, -int(height_box))
                    label_string = 'PEC (ideal conductor)'
                else:
                    # material assignment is invalid
                    height_box = part_height / 2
                    setBrush(INVALID_MATERIAL_COLOR)
                    drawRect(xmetal, flipy(ymetal), wmetal, -int(height_box))
                    label_string = 'INVALID MATERIAL REFERENCE: ' + metal.material

                interactive_entries.append({
                    "kind": "layer",
                    "key": metal.name,
                    "rect": QRectF(xmetal, flipy(ymetal), wmetal, -int(height_box)).normalized(),
                    "ref": metal,
                    "tooltip": _build_layer_tooltip(metal),
                    "chiplet_id": entry_chiplet_id(metal),
                })

                name_string = f"{metal.name} ({metal.layernum})"
                if crowded:
                    # narrow slot: give up detail until the text fits - the material
                    # label first, then the layer number, then shorten the name itself.
                    # Decided once for the whole group, so all slots in the row show the
                    # same level of detail. Everything dropped here is still in the hover
                    # tooltip. Width is a character-count estimate (no QFontMetrics: this
                    # layout function must work without a QApplication).
                    group_first = n - slot_index
                    if group_first not in crowded_detail_level:
                        def _text_width(text):
                            return len(text) * 6 + 10
                        available = wmetal - 20
                        level = 0  # 0: name, layer number and label; 1: no label; 2: name only
                        for member in metals_inside[group_first:group_first + slot_count]:
                            member_material = materials_list.get_by_name(member.material)
                            if member_material is not None:
                                member_label = metal_label_fn(member, member_material, member.is_sheet)
                            elif _is_pec_material(member.material):
                                member_label = 'PEC (ideal conductor)'
                            else:
                                member_label = 'INVALID MATERIAL REFERENCE: ' + member.material
                            member_name = f"{member.name} ({member.layernum})"
                            if _text_width(member_name) > available:
                                level = 2
                            elif _text_width(member_name) + _text_width(member_label) > available:
                                level = max(level, 1)
                        crowded_detail_level[group_first] = (level, available)
                    level, available = crowded_detail_level[group_first]
                    if level >= 1:
                        label_string = ""
                    if level == 2:
                        name_string = metal.name
                        max_chars = int((available - 10) / 6)
                        if len(name_string) > max_chars:
                            name_string = name_string[:max(1, max_chars - 1)] + "…"
                setPen(penBlack)
                drawText_left(xmetal + 10, flipy(ymetal), wmetal, part_height / 2, name_string)
                setPen(penGray)
                drawText_right(xmetal, flipy(ymetal), wmetal - 10, part_height / 2, label_string)
                # store the drawing position, because vias will refer to that
                if not metal.zmin in stored_z:
                    stored_z = np.append(stored_z, metal.zmin)
                    stored_y = np.append(stored_y, ymetal)
                if not metal.zmax in stored_z:
                    stored_z = np.append(stored_z, metal.zmax)
                    stored_y = np.append(stored_y, ymetal + height_box)

                setPen(penGray)
                if draw_side_ticks:
                    drawLine(xmetal - 60, flipy(ymetal), xmetal - 10, flipy(ymetal))
                # draw line at top side of metal
                if draw_side_ticks and not metal.is_sheet:
                    drawLine(xmetal - 60, flipy(ymetal + height_box), xmetal - 10, flipy(ymetal + height_box))
                    heightstring = f'{metal.thickness:.3f}µm'
                    setPen(penDarkGray)
                    drawText_left(xmetal - 60, flipy(ymetal), 50, height_box, heightstring)

                if not previous_at_same_zmin:
                    # draw height to metal above
                    if next_metal_above is not None:
                        dz = abs(next_metal_above.zmin - metal.zmax)
                        heightstring = f'{dz:.3f}µm'
                        setPen(penGray)
                        # sheet metals draw at height_box=3px, too short to fit this
                        # label without vertical clipping - give the text its own
                        # minimum box height, independent of the drawn box height
                        text_height = max(height_box, 14)
                        drawText_left(xmetal - 60, flipy(ymetal + height_box), 50, text_height, heightstring)

                if n == len(metals_inside) - 1:
                    # last metal (top metal)
                    # place text for distance to dielectric boundary

                    setPen(penBlack)
                    # a metal is registered "inside" a dielectric by its zmin alone
                    # (see util_stackup_reader.register_metals_inside()) - its zmax
                    # can legitimately extend past that dielectric's own zmax into
                    # the one(s) above (e.g. a thick metal sitting in a very thin
                    # dielectric slab), which would otherwise show as a negative,
                    # confusingly-worded "distance to the boundary above". Floor at
                    # 0 - the metal is still drawn at its correct position/height,
                    # this only affects this one label.
                    dz = max(0.0, dielectric.zmax - metal.zmax)
                    if dz > 10:
                        heightstring = f'{dz:.1f}µm'
                    else:
                        heightstring = f'{dz:.3f}µm'
                    setPen(penGray)
                    if draw_side_ticks:
                        drawTextAt(xmetal - 60, flipy(ymetal + height_box + 5), heightstring)

                if n == 0 and elevation > 0.001:
                    # metal not aligned with bottom of dielectric, add a label for offset value
                    heightstring = f'{elevation:.3f}µm'
                    setPen(penGray)
                    drawTextAt(xmetal - 60, flipy(ymetal - 10), heightstring)

                if not next_at_same_zmin:
                    # increase screen y for next metal
                    ymetal = ymetal + part_height

        y = y + h

    # sort stored positions
    if len(stored_z) > 2:
        idx = np.argsort(stored_z)
        y_sorted = stored_y[idx]
        z_sorted = stored_z[idx]
        # linear, not cubic: the z->y mapping is a layout position (screen height
        # per dielectric is set by how many metals are stacked inside it, not by
        # its physical thickness), so slope can change drastically between
        # consecutive stored points - e.g. a thick, metal-free substrate maps to
        # almost no screen height while a thin, via-packed dielectric maps to a
        # lot. A cubic spline through data like that readily overshoots (Runge's
        # phenomenon), and with unbounded extrapolation that overshoot is
        # unbounded - enough to overflow the int coordinates drawRect() needs
        # below. Linear interpolation/extrapolation is bounded by construction.
        z_to_y = _LinearInterpExtrapolate(z_sorted, y_sorted)

        if sibling_chiplets:
            # visual reminder that another chiplet sits beside the one currently shown,
            # starting at their shared interface (the branch point dielectric's top) -
            # deliberately schematic: a short, empty, open-topped outline in the gutter
            # reserved above (xmax narrowed for this), not a to-scale/detailed rendering
            # of the sibling. Open top (no top line) reads as "truncated - continues
            # beyond view" rather than a small closed box that happens to be there. "+n"
            # (n = other sibling chiplets not currently shown) is the only content inside -
            # no interior geometry, matching the "not in detail" ask.
            STUB_HEIGHT = 56
            stub_x = xmax   # flush against the main column's right edge - reads as
                             # growing out of it, right at the shared boundary line
                             # already drawn there, rather than a disconnected box
            stub_y_bottom = flipy(z_to_y(active_chiplet.branch_point.zmax))
            stub_y_top = stub_y_bottom - STUB_HEIGHT
            setPen(QPen(penGray.color(), 1, Qt.DashLine))
            setBrush(Qt.NoBrush)
            drawLine(stub_x, stub_y_bottom, stub_x, stub_y_top)                              # left
            drawLine(stub_x + STUB_WIDTH, stub_y_bottom, stub_x + STUB_WIDTH, stub_y_top)     # right
            drawLine(stub_x, stub_y_bottom, stub_x + STUB_WIDTH, stub_y_bottom)               # bottom
            # top edge deliberately omitted - see docstring above

            setPen(penGray)
            text_rect = QRect(int(stub_x), int(stub_y_top), int(STUB_WIDTH), int(STUB_HEIGHT / 2))
            draw_calls.append(("drawText", (text_rect, Qt.AlignCenter, f"+{len(sibling_chiplets)}")))

            # sketched (outline-only, no filled arrowhead) left/right chevrons hinting
            # at the Left/Right keyboard shortcut that steps through chiplets
            # (VectorWidget.keyPressEvent) - purely a discoverability nudge, not
            # clickable itself, so plain open "<"/">" strokes are enough; no need for
            # a filled/solid arrow that would suggest a button.
            setPen(QPen(penGray.color(), 1))
            chevron_cy = stub_y_bottom - 14   # bottom band, clear of the "+n" text above
            chevron_size = 5
            chevron_gap = 8
            left_cx = stub_x + STUB_WIDTH / 2 - chevron_gap
            right_cx = stub_x + STUB_WIDTH / 2 + chevron_gap
            drawLine(left_cx + chevron_size, chevron_cy - chevron_size, left_cx, chevron_cy)
            drawLine(left_cx, chevron_cy, left_cx + chevron_size, chevron_cy + chevron_size)
            drawLine(right_cx - chevron_size, chevron_cy - chevron_size, right_cx, chevron_cy)
            drawLine(right_cx, chevron_cy, right_cx - chevron_size, chevron_cy + chevron_size)

        # next we draw the vias, based on the screen position of metals that we have stored
        # via position alternates between 3 positions along x axis
        pos = 1
        w = (xmax - xmin) / 10

        setBrush(QColor(136, 192, 200, 80))
        for metal in metals_list.metals:
            if metal.is_via or metal.is_dielectric:
                if visible_layers is not None and metal not in visible_layers:
                    continue

                material = materials_list.get_by_name(metal.material)
                label_suffix = via_label_suffix_fn(metal, material)

                y1 = z_to_y(metal.zmin)
                y2 = z_to_y(metal.zmax)
                h = abs(y2 - y1)

                if pos == 1:
                    xvia = (xmax + xmin) / 2 - 4 * w / 2
                    pos = 2
                elif pos == 2:
                    xvia = (xmax + xmin) / 2 - w / 2
                    pos = 3
                else:
                    xvia = (xmax + xmin) / 2 + w
                    pos = 1

                setPen(penBlack)
                drawRect(xvia, flipy(y1), w, -h)
                interactive_entries.append({
                    "kind": "layer",
                    "key": metal.name,
                    "rect": QRectF(xvia, flipy(y1), w, -h).normalized(),
                    "ref": metal,
                    "tooltip": _build_layer_tooltip(metal),
                    "chiplet_id": entry_chiplet_id(metal),
                })
                # label near the via's upper end (baseline about one text height below the
                # top edge); a box too short for that keeps it near the lower end, as before
                drawTextAt(xvia + 5, flipy(y1 + max(h - 14, 5)),
                           f"{metal.name} ({metal.layernum})" + label_suffix)

    return draw_calls, interactive_entries


def compute_topology_overview_layout(dielectrics_list, materials_list, width, height,
                                      dielectric_color_fn, dielectric_label_fn):
    """Pure layout computation for the "topology overview" sketch: the shared/interposer
    dielectrics drawn as one full-width slab stack, with each detected chiplet's own
    dielectrics drawn as an equal-width column placed side by side on top of it - a
    NOT-to-GDS-scale sketch of "small chiplets sitting side by side on a shared dielectric
    base". Deliberately limited to dielectric blocks only (no metal/via boxes, no
    z-interpolation) - see compute_stackup_layout() for that fuller, more fragile rendering
    this is a simplified sibling of, not a variant of.

    Only meaningful for a stackup with 2+ detected chiplets (dielectrics_list.chiplet_groups.
    chiplets) - returns ([], []) otherwise, so a caller that forgets to gate on chiplet count
    gets an empty scene rather than a crash. Real gating is in the UI (see VectorWidget.
    set_topology_mode() / StackupPreviewWindow's topology toggle, which only becomes visible
    at the same 2+ chiplets threshold ChipletSwitcher already uses).

    Returns (draw_calls, interactive_entries) - same contract as compute_stackup_layout()/
    render_stackup_layout(), so this is a drop-in alternative source of draw_calls for
    StackupBackgroundItem, and interactive_entries follow the same {"kind": "dielectric",
    "key", "rect", "ref", "tooltip", "chiplet_id"} shape (kind is always "dielectric" here -
    there is no "layer" kind in this mode) so InteractiveRegionItem/VectorWidget's existing
    click/hover/selection machinery works unchanged.
    """
    chiplet_groups = getattr(dielectrics_list, "chiplet_groups", None)
    if chiplet_groups is None or len(chiplet_groups.chiplets) < 2:
        return [], []

    draw_calls = []
    interactive_entries = []

    # same draw-call-recorder-closure pattern as compute_stackup_layout() (setPen/setBrush/
    # drawRect/drawLine/flipy), duplicated locally rather than factored into a shared helper -
    # keeps compute_stackup_layout() completely untouched, zero regression risk there
    def flipy(y):
        return height - y

    def setPen(pen):
        draw_calls.append(("setPen", (pen,)))

    def setBrush(brush):
        draw_calls.append(("setBrush", (brush,)))

    def drawRect(x, y, w, h):
        draw_calls.append(("drawRect", (x, y, w, h)))

    def drawLine(x1, y1, x2, y2):
        draw_calls.append(("drawLine", (x1, y1, x2, y2)))

    def drawText_center(x, y, w, h, text):
        rect = QRect(int(x), int(y - h), int(w), int(h))
        draw_calls.append(("drawText", (rect, Qt.AlignVCenter | Qt.AlignHCenter, text)))

    penBlack = QPen(Qt.black, 1)
    penDivider = QPen(QColor(134, 132, 130), 1, Qt.DashLine)

    def dielectric_color(dielectric):
        material = materials_list.get_by_name(dielectric.material)
        return dielectric_color_fn(material) if material is not None else INVALID_MATERIAL_COLOR

    # purely cosmetic pseudo-3D extrusion: a right-side face (darker shade) on every slab,
    # and a top face (lighter shade) only on the topmost slab of each "tower" (an
    # interposer stack or one chiplet column) - a top face on every slab would just get
    # overdrawn by the slab stacked directly above it, since there's no gap there to show
    # it in; the right-side face has no such conflict since nothing else is drawn to the
    # right of a slab within its own tower. DEPTH is in pixels, not model units - purely a
    # fixed visual bevel size regardless of zoom/window size.
    DEPTH = 6

    def draw_side_face(x, y, w, h, color):
        top, bottom = (y, y + h) if h >= 0 else (y + h, y)
        right = x + w
        face = QPolygonF([
            QPointF(right, top), QPointF(right, bottom),
            QPointF(right + DEPTH, bottom - DEPTH), QPointF(right + DEPTH, top - DEPTH),
        ])
        setPen(penBlack)
        setBrush(QBrush(color.darker(130)))
        draw_calls.append(("drawPolygon", (face,)))

    def draw_top_face(x, y, w, h, color):
        top = y if h >= 0 else y + h
        face = QPolygonF([
            QPointF(x, top), QPointF(x + w, top),
            QPointF(x + w + DEPTH, top - DEPTH), QPointF(x + DEPTH, top - DEPTH),
        ])
        setPen(penBlack)
        setBrush(QBrush(color.lighter(130)))
        draw_calls.append(("drawPolygon", (face,)))

    interposer = sorted(chiplet_groups.interposer_dielectrics, key=lambda d: d.zmin)
    chiplets = chiplet_groups.chiplets

    xmin = width * 0.02
    xmax = width * 0.98 - DEPTH  # leave room for the side-face extrusion on the right edge
    w_total = xmax - xmin
    n_chiplets = len(chiplets)
    gutter = width * 0.035  # a bit more breathing room between chiplets on the carrier
    col_w = (w_total - gutter * (n_chiplets - 1)) / n_chiplets

    # HEADER_HEIGHT is reserved *above* ymax for the chiplet column header labels (drawn
    # below), not squeezed into the top margin - the header band needs real budget of its
    # own, or it clips against the scene's own top edge (y=0) at typical preview window
    # heights, since the margin alone is only ~2.5% of height. DEPTH is reserved on top of
    # that so each column's top-face extrusion has room too, above the columns but below
    # the header text (see the header draw call below, shifted up by DEPTH to clear it).
    HEADER_HEIGHT = 20
    ymin = height * 0.025
    ymax = height * 0.975 - HEADER_HEIGHT - DEPTH

    # schematic sizing: unlike compute_stackup_layout()'s "1 part per metal level" rule
    # (parts = max(1, metals_count)), no metals are drawn here at all, so every dielectric
    # simply gets 1 part
    base_parts = max(1, len(interposer))
    chiplet_parts = max(1, max(len(chiplet.dielectrics) for chiplet in chiplets))
    total_parts = base_parts + chiplet_parts
    part_height = (ymax - ymin) / total_parts
    base_height = part_height * base_parts
    # every chiplet's column gets the SAME total height (driven by whichever chiplet has the
    # most dielectrics), so all columns reach the same top y and visually "sit side by side" -
    # a chiplet with fewer dielectrics gets a few taller slabs instead of a shorter column
    column_height = part_height * chiplet_parts

    # draw interposer slabs bottom-up, full width - every slab gets a side-face extrusion,
    # but only the topmost one also gets a top face (a lower slab's "top" is immediately
    # covered by the slab stacked on it, so there's no gap there to show one in)
    y = ymin
    for i, dielectric in enumerate(interposer):
        color = dielectric_color(dielectric)
        draw_side_face(xmin, flipy(y), w_total, -part_height, color)
        setPen(penBlack)
        setBrush(color)
        drawRect(xmin, flipy(y), w_total, -part_height)
        if i == len(interposer) - 1:
            draw_top_face(xmin, flipy(y), w_total, -part_height, color)
        interactive_entries.append({
            "kind": "dielectric",
            "key": dielectric.name,
            "rect": QRectF(xmin, flipy(y), w_total, -part_height).normalized(),
            "ref": dielectric,
            "tooltip": _build_dielectric_tooltip(dielectric),
            "chiplet_id": None,
        })
        drawText_center(xmin + 5, flipy(y), w_total - 10, part_height, dielectric.name)
        y += part_height

    setPen(penDivider)
    drawLine(xmin, flipy(y), xmax, flipy(y))

    # draw each chiplet's column, side by side, starting where the interposer stack ends
    for i, chiplet in enumerate(chiplets):
        x = xmin + i * (col_w + gutter)
        chip_dielectrics = sorted(chiplet.dielectrics, key=lambda d: d.zmin)
        col_part_height = column_height / len(chip_dielectrics)

        setPen(penBlack)
        # shifted up by DEPTH so the topmost slab's top-face extrusion (drawn below)
        # doesn't overlap the label text
        drawText_center(x, flipy(y + column_height) - DEPTH, col_w, HEADER_HEIGHT, chiplet.id)

        cy = y
        for j, dielectric in enumerate(chip_dielectrics):
            color = dielectric_color(dielectric)
            draw_side_face(x, flipy(cy), col_w, -col_part_height, color)
            setPen(penBlack)
            setBrush(color)
            drawRect(x, flipy(cy), col_w, -col_part_height)
            if j == len(chip_dielectrics) - 1:
                draw_top_face(x, flipy(cy), col_w, -col_part_height, color)
            interactive_entries.append({
                "kind": "dielectric",
                "key": dielectric.name,
                "rect": QRectF(x, flipy(cy), col_w, -col_part_height).normalized(),
                "ref": dielectric,
                "tooltip": _build_dielectric_tooltip(dielectric),
                "chiplet_id": chiplet.id,
            })
            # narrow columns have no room for the wide slab's left-name/right-material
            # two-sided label - centered name only, material stays available via tooltip
            drawText_center(x + 2, flipy(cy), col_w - 4, col_part_height, dielectric.name)
            cy += col_part_height

    return draw_calls, interactive_entries


def render_stackup_layout(draw_calls, painter, width, height):
    """Replays draw_calls (from compute_stackup_layout()) onto painter - the exact
    same QPainter calls the previous paintEvent()-based VectorWidget made directly."""
    painter.fillRect(QRectF(0, 0, width, height), Qt.white)
    painter.setRenderHint(QPainter.Antialiasing)
    for method_name, args in draw_calls:
        getattr(painter, method_name)(*args)


class StackupBackgroundItem(QGraphicsItem):
    """Renders the stackup cross-section preview's static visuals (dielectric slabs,
    metal/via boxes, labels, connector lines) by replaying draw_calls captured by
    compute_stackup_layout(). Kept separate from InteractiveRegionItem so hover/
    selection support never has to re-derive any of that layout math.
    """

    def __init__(self, draw_calls, width, height):
        super().__init__()
        self._draw_calls = draw_calls
        self._width = width
        self._height = height
        self.setZValue(-1)  # stay behind the interactive overlay items

    def boundingRect(self):
        return QRectF(0, 0, self._width, self._height)

    def paint(self, painter, option, widget=None):
        render_stackup_layout(self._draw_calls, painter, self._width, self._height)


class InteractiveRegionItem(QGraphicsRectItem):
    """Transparent overlay for one dielectric slab / metal / via box: gives it a
    click-triggered info flyout and native click-to-select highlighting, without
    StackupBackgroundItem's rendering having to know anything about interactivity.

    The info flyout is shown explicitly from mousePressEvent() (QToolTip.showText()),
    not via setToolTip() - setToolTip() would make Qt show it automatically on mere
    hover, which is deliberately not wanted here: the flyout should only appear when
    a shape is actually clicked.
    """

    _HIGHLIGHT_PEN = QPen(QColor(255, 140, 0), 3)
    # a dielectric whose resolved z-range overlaps another same-scope dielectric (see
    # dielectric_layers_list.find_z_overlap_pairs()) - distinct red/dashed vs. the orange/
    # solid selection highlight so both are visually distinguishable if a slab is both
    # selected and overlapping at once. Always drawn (not just on hover/click), unlike the
    # selection highlight - this needs to be visible without the user doing anything, since
    # it's the primary, contextual signal for what would otherwise only be a status-bar line
    _OVERLAP_PEN = QPen(QColor(220, 0, 0), 2, Qt.DashLine)

    def __init__(self, rect, kind, key, ref, tooltip, chiplet_id=None, has_overlap=False):
        super().__init__(rect)
        self.setPen(Qt.NoPen)
        self.setBrush(Qt.NoBrush)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.info_text = tooltip
        self.kind = kind          # "dielectric" or "layer"
        self.key = key            # element Name, matching row_elements lookup in the editor
        self.ref = ref            # dielectric_layer or metal_layer instance
        # None (interposer) or the active chiplet's id - only used to build VectorWidget's
        # _item_lookup compound key (see _rebuild_scene()), not part of the external
        # elementSelected/select_element(kind, name) contract, which stays plain-name
        self.chiplet_id = chiplet_id
        self.has_overlap = has_overlap

    def paint(self, painter, option, widget=None):
        # unselected/non-overlapping: draw nothing, StackupBackgroundItem already drew the
        # real colors/labels underneath.
        if self.has_overlap:
            painter.setPen(self._OVERLAP_PEN)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect())
        # Selected: a highlight outline instead of Qt's default dashed selection rectangle,
        # which would look wrong here - drawn last/on top so it stays visually dominant.
        if self.isSelected():
            painter.setPen(self._HIGHLIGHT_PEN)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect())

    def mousePressEvent(self, event):
        super().mousePressEvent(event)  # keeps native click-to-select behavior
        if self.info_text:
            QToolTip.showText(event.screenPos(), self.info_text)


class VectorWidget(QGraphicsView):
    """This widget draws the stackup preview, and supports hovering a shape for a
    tooltip and clicking a shape to select it (see elementSelected/select_element).

    The color/label logic for dielectrics and metals is injected as callables
    instead of being hardcoded here, so a host application can customize it
    (e.g. a permittivity-based preview vs. a thermal-conductivity-based one):

        dielectric_color_fn(material) -> QColor
        dielectric_label_fn(dielectric, material) -> str
        metal_label_fn(metal, material, is_sheet) -> str
        via_label_suffix_fn(metal, material) -> str
    """

    # emitted when a shape is clicked/selected in the preview: (kind, key), where
    # kind is "dielectric" or "layer" and key is the element's Name
    elementSelected = Signal(str, str)

    def __init__(self, materials_list, dielectrics_list, metals_list,
                 dielectric_color_fn, dielectric_label_fn,
                 metal_label_fn, via_label_suffix_fn):
        super().__init__()
        self.materials_list = materials_list
        self.dielectrics_list = dielectrics_list
        self.metals_list = metals_list
        self.dielectric_color_fn = dielectric_color_fn
        self.dielectric_label_fn = dielectric_label_fn
        self.metal_label_fn = metal_label_fn
        self.via_label_suffix_fn = via_label_suffix_fn

        self.setRenderHint(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        # StrongFocus (not the QGraphicsView default of NoFocus/ClickFocus ambiguity
        # across styles) so a click into the view reliably grabs keyboard focus - needed
        # for keyPressEvent()'s Left/Right chiplet-switching below to ever fire
        self.setFocusPolicy(Qt.StrongFocus)

        self._item_lookup = {}         # (kind, chiplet_id, key) -> InteractiveRegionItem
        self._item_by_kind_name = {}   # (kind, key) -> InteractiveRegionItem, for select_element()
        # which chiplet to show, for a stackup with more than one detected (see
        # compute_stackup_layout()'s active_chiplet_id) - None means "let
        # compute_stackup_layout() pick the first one", not "no chiplets"; irrelevant
        # (ignored) for an ordinary, non-chiplet stackup
        self._active_chiplet_id = None
        # True shows the simplified "topology overview" sketch (compute_topology_overview_
        # layout()) instead of the normal detailed cross-section (compute_stackup_layout())
        # - see set_topology_mode()
        self._topology_mode = False
        # True only while _rebuild_scene() is restoring a previous selection
        # programmatically (see below) - distinguishes that from a genuine user click, so
        # _on_scene_selection_changed()'s "clicking a chiplet in topology mode switches to
        # it" behavior doesn't misfire just because a chiplet-owned item happened to carry
        # its selection over into a freshly-entered topology view
        self._restoring_selection = False
        # set via set_chiplet_switcher() by whoever constructs this widget, once its
        # own ChipletSwitcher exists too - lets Left/Right (see keyPressEvent below)
        # drive the same single source of truth (the switcher's combo index) as
        # clicking the combo directly does, instead of a second, separately-tracked
        # "current chiplet" that could drift out of sync with the combo's own display
        self._chiplet_switcher = None
        scene = QGraphicsScene(self)
        self.setScene(scene)
        scene.selectionChanged.connect(self._on_scene_selection_changed)

        self._rebuild_scene()

    def refresh(self, materials_list, dielectrics_list, metals_list):
        """Replaces the stackup data and rebuilds the scene - the refresh entry point
        used by the editor every time the underlying XML changes (replaces the old
        "mutate materials_list/dielectrics_list/metals_list then call .update()"
        pattern, since there's no per-shape geometry to mutate in place anymore).
        """
        self.materials_list = materials_list
        self.dielectrics_list = dielectrics_list
        self.metals_list = metals_list
        self._rebuild_scene()

    def set_active_chiplet(self, chiplet_id):
        """Switches which chiplet is shown (called by a ChipletSwitcher combo box) and
        rebuilds the scene. A no-op-safe call on a stackup with 0 or 1 chiplets - it just
        gets ignored by compute_stackup_layout(), same as any other chiplet_id would be
        for such a file.
        """
        self._active_chiplet_id = chiplet_id
        self._rebuild_scene()

    def set_chiplet_switcher(self, chiplet_switcher):
        """Links this widget to its ChipletSwitcher combo box, so Left/Right (see
        keyPressEvent()) can step it - called once by whichever window constructs both
        (see StackupEditorWindow), right after building the switcher itself with this
        widget's set_active_chiplet as its callback.
        """
        self._chiplet_switcher = chiplet_switcher

    def set_topology_mode(self, enabled):
        """Switches between the normal cross-section preview and the "topology overview"
        sketch (see compute_topology_overview_layout()) and rebuilds the scene - called by
        ChipletSwitcher when its "Topology Overview" entry (always item 0) is selected/
        deselected.
        """
        self._topology_mode = bool(enabled)
        self._rebuild_scene()

    def keyPressEvent(self, event):
        if self._chiplet_switcher is not None and event.key() in (Qt.Key_Left, Qt.Key_Right):
            # steps through the switcher's combo - "Topology Overview" plus every real
            # chiplet, in that order - as one unified list
            self._chiplet_switcher.step(-1 if event.key() == Qt.Key_Left else 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _rebuild_scene(self):
        # keep whatever was selected (by identity of (kind, chiplet_id, key), not by
        # item, since every item is recreated below) selected across the rebuild, so an
        # edit to the currently-selected layer doesn't make its preview highlight
        # vanish. Using the chiplet_id-qualified triple (not just (kind, key)) means a
        # selection made in one chiplet is deliberately NOT restored after switching to
        # a different chiplet - even if both happen to have a same-named element -
        # since re-selecting "the same name in a different, unrelated chiplet" would be
        # surprising, not helpful.
        previously_selected = self._selected_key()

        # compute_stackup_layout() is computed directly against the viewport's actual
        # pixel size (matching what the old paintEvent()-based widget did with
        # self.width()/self.height()), not a fixed logical canvas scaled to fit via
        # fitInView() - text is drawn at a plain, unscaled font size, and scaling a
        # smaller fixed canvas up/down to fit the actual (usually smaller) preview
        # window would have shrunk that text along with the boxes. Rebuilding the
        # layout on every resize (see resizeEvent below) costs a bit more than just
        # re-scaling a cached scene, but keeps text legible at any window size.
        width = max(self.viewport().width(), 1)
        height = max(self.viewport().height(), 1)

        scene = self.scene()
        scene.clear()
        self._item_lookup = {}
        self._item_by_kind_name = {}

        if self._topology_mode:
            draw_calls, interactive_entries = compute_topology_overview_layout(
                self.dielectrics_list, self.materials_list, width, height,
                self.dielectric_color_fn, self.dielectric_label_fn)
        else:
            draw_calls, interactive_entries = compute_stackup_layout(
                self.materials_list, self.dielectrics_list, self.metals_list,
                width, height,
                self.dielectric_color_fn, self.dielectric_label_fn,
                self.metal_label_fn, self.via_label_suffix_fn,
                active_chiplet_id=self._active_chiplet_id)

        scene.addItem(StackupBackgroundItem(draw_calls, width, height))

        for entry in interactive_entries:
            item = InteractiveRegionItem(entry["rect"], entry["kind"], entry["key"],
                                          entry["ref"], entry["tooltip"], entry["chiplet_id"],
                                          has_overlap=entry.get("has_overlap", False))
            scene.addItem(item)
            self._item_lookup[(entry["kind"], entry["chiplet_id"], entry["key"])] = item
            self._item_by_kind_name[(entry["kind"], entry["key"])] = item

        scene.setSceneRect(0, 0, width, height)

        if previously_selected is not None and previously_selected in self._item_lookup:
            self._restoring_selection = True
            try:
                self._item_lookup[previously_selected].setSelected(True)
            finally:
                self._restoring_selection = False

    def _selected_key(self):
        for triple, item in self._item_lookup.items():
            if item.isSelected():
                return triple
        return None

    def _on_scene_selection_changed(self):
        selected = self.scene().selectedItems()
        if not selected:
            # clicking empty background clears selection - dismiss any flyout left
            # showing from the previously-selected shape rather than stranding it
            QToolTip.hideText()
            return
        item = selected[0]
        kind, key, chiplet_id = item.kind, item.key, item.chiplet_id
        if self._restoring_selection:
            # _rebuild_scene() is merely restoring whatever was already selected before
            # the rebuild - not a fresh user click - so this must not re-fire
            # elementSelected: a listener like StackupEditorWindow._on_preview_element_
            # selected() switches the editor's active tab to Dielectrics/Layers on every
            # emission, which would otherwise happen after *any* unrelated edit anywhere
            # in the editor (e.g. adding a Variable) as long as some shape was ever
            # selected in the preview earlier - yanking the user back out of whichever
            # tab they're actually working in. Nor does it qualify for the topology-mode
            # click-switch behavior below, for the same reason.
            return
        if (self._topology_mode and chiplet_id is not None
                and self._chiplet_switcher is not None):
            # clicking a chiplet's own slab in the topology overview switches straight to
            # that chiplet's detail view (dropdown included), instead of just selecting it
            # in place (the _restoring_selection case above already excludes a
            # programmatic selection-carryover from triggering this - e.g. a chiplet-owned
            # item selected just before switching into topology mode, and also present
            # there, would otherwise immediately bounce back out of the topology view the
            # user just chose). Deferred via QTimer.singleShot(0, ...): this handler is running
            # from inside the very item/scene the switch is about to tear down (switching
            # mode rebuilds the scene), so acting immediately would touch already-deleted
            # Qt objects once control returns to InteractiveRegionItem.mouseReleaseEvent()'s
            # own remaining code. elementSelected still ends up emitted for cross-window
            # sync once the deferred re-select below runs, via the normal (non-topology)
            # path this same handler takes for that new selection.
            QTimer.singleShot(0, self._deferred_switch_to_chiplet(chiplet_id, kind, key))
            return
        self.elementSelected.emit(kind, key)

    def _deferred_switch_to_chiplet(self, chiplet_id, kind, key):
        """Returns a zero-arg callable for QTimer.singleShot(0, ...) (see
        _on_scene_selection_changed()): switches out of topology mode into chiplet_id's
        detail view via the ChipletSwitcher (so its combo reflects the change too), then
        re-selects the same (kind, key) element there, carrying the highlight across the
        mode switch. No-ops safely if this widget was destroyed (window closed) before the
        deferred call fires.
        """
        def run():
            if not shiboken6.isValid(self):
                return
            self._chiplet_switcher.set_current_chiplet(chiplet_id)
            self.select_element(kind, key)
        return run

    def select_element(self, kind, name):
        """Selects/highlights the shape for (kind, name) - kind is "dielectric" or
        "layer". Called by the editor when a table row is selected, to keep the
        preview in sync with the table (also reached from a cross-window click in the
        Layout Preview - see _forward_stackup_selection_to_layout_preview()'s reverse
        direction). A no-op if that shape is already the sole selection, so this
        doesn't bounce back into elementSelected/the editor's own selection-changed
        handling.

        The Dielectrics/Layers tables list every element in the file regardless of
        chiplet, so (kind, name) may refer to an element that belongs to a chiplet
        other than the one currently shown - in that case, switch to the chiplet that
        actually contains it first (via the attached ChipletSwitcher, so its combo box
        stays the single source of truth - see ChipletSwitcher.set_current_chiplet()),
        then select it there.
        """
        item = self._item_by_kind_name.get((kind, name))
        if item is None:
            owning_chiplet_id = self._find_owning_chiplet_id(kind, name)
            if owning_chiplet_id is not None and owning_chiplet_id != self._active_chiplet_id:
                if self._chiplet_switcher is not None:
                    self._chiplet_switcher.set_current_chiplet(owning_chiplet_id)
                else:
                    self.set_active_chiplet(owning_chiplet_id)
                item = self._item_by_kind_name.get((kind, name))
        if self.scene().selectedItems() == ([item] if item is not None else []):
            return
        self.scene().clearSelection()
        if item is not None:
            item.setSelected(True)

    def _find_owning_chiplet_id(self, kind, name):
        """Which chiplet's subtree (kind, name) belongs to, or None if it's an
        interposer element (always shown, no switch needed) or doesn't exist at all -
        used by select_element() to jump to the right chiplet before selecting.
        """
        chiplet_groups = getattr(self.dielectrics_list, "chiplet_groups", None)
        if chiplet_groups is None:
            return None
        attr = "dielectrics" if kind == "dielectric" else "layers"
        for chiplet in chiplet_groups.chiplets:
            if any(element.name == name for element in getattr(chiplet, attr)):
                return chiplet.id
        return None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_scene()


class ChipletSwitcher(QWidget):
    """Combo box + "Chiplet N of M" label for picking which chiplet a Stackup Preview
    shows in detail, for a stackup where dielectric_layers_list.detect_chiplet_groups()
    found more than one chiplet sharing a common interposer base (see
    util_stackup_reader.py). "Topology Overview" (see compute_topology_overview_layout())
    is listed as the combo's first entry, alongside the real chiplets, rather than as a
    separate control - selecting it shows every chiplet at once instead of one in detail.
    Hidden entirely (never even shown) when there are 0 or 1 chiplet groups, since neither
    per-chiplet detail switching nor a topology overview is meaningful then.
    """

    TOPOLOGY_LABEL = "Topology Overview"
    # unique per-class sentinel (not a chiplet id, which is always a real dielectric name)
    # marking "Topology Overview is/was the selection" - see set_groups()
    _TOPOLOGY = object()

    def __init__(self, on_chiplet_changed, on_topology_changed):
        """Args:
            on_chiplet_changed (callable): called with a chiplet id (str) whenever a real
              chiplet is selected - wire this straight to a VectorWidget's
              set_active_chiplet().
            on_topology_changed (callable): called with True when "Topology Overview" is
              selected, and False whenever switching away from it to a real chiplet - wire
              this straight to a VectorWidget's set_topology_mode().
        """
        super().__init__()
        self._on_chiplet_changed = on_chiplet_changed
        self._on_topology_changed = on_topology_changed
        self._chiplet_ids = []  # real chiplet ids only - combo index 0 is always Topology
                                 # Overview, so combo index i>=1 maps to _chiplet_ids[i-1]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("")
        layout.addWidget(self.label)
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_index_changed)
        layout.addWidget(self.combo, 1)
        self.setVisible(False)

    def set_groups(self, groups):
        """Call whenever the stackup is (re)loaded - groups is a stackup's
        dielectrics_list.chiplet_groups (may be None, or have zero/one chiplets, in which
        case this stays/becomes hidden and does nothing else).

        In the Stackup Editor this runs after every single edit (see _refresh_preview()),
        not just an actual file (re)load - so it keeps showing whichever selection was
        already active - a chiplet by id, or Topology Overview - if it's still valid in the
        new grouping, rather than always snapping back to the first chiplet and disorienting
        the user mid-edit. A genuinely fresh start (no previous selection at all - opening/
        creating a multi-chiplet file for the first time in this widget) instead leads with
        Topology Overview, so the viewer sees the whole picture before drilling into any one
        chiplet. Falls back to the first real chiplet (not Topology Overview) when the
        previously-active chiplet no longer exists (e.g. renamed/removed), or when Topology
        Overview was active but chiplets just dropped below 2 (no longer a meaningful choice
        - matches Topology Overview effectively "closing" the same way this whole combo
        already hides itself in that case).
        """
        chiplets = groups.chiplets if groups is not None else []
        new_ids = [chiplet.id for chiplet in chiplets]

        old_index = self.combo.currentIndex()
        if self._chiplet_ids and old_index == 0:
            previous = self._TOPOLOGY
        elif self._chiplet_ids and 1 <= old_index <= len(self._chiplet_ids):
            previous = self._chiplet_ids[old_index - 1]
        else:
            previous = None

        self._chiplet_ids = new_ids

        if previous is self._TOPOLOGY and len(self._chiplet_ids) >= 2:
            index = 0
        elif previous in self._chiplet_ids:
            index = self._chiplet_ids.index(previous) + 1
        elif previous is None and len(self._chiplet_ids) >= 2:
            # a genuinely fresh start (no previous selection at all - e.g. this file was
            # just opened/created) leads with Topology Overview, so the viewer sees the
            # whole multi-chiplet picture before drilling into any one chiplet's detail.
            # Deliberately distinct from the next branch below: a previous selection that
            # existed but became invalid mid-edit (e.g. the active chiplet was just
            # renamed/removed) still falls back to a real chiplet, not Topology Overview -
            # jumping to a whole different view mode as a side effect of an unrelated edit
            # would be more surprising than helpful there.
            index = 0
        else:
            index = 1 if self._chiplet_ids else 0

        # setCurrentIndex() is also kept inside the signals-blocked region (not just
        # clear()/addItems()) - whether it actually changes anything is unpredictable
        # (Qt only emits when the resulting index differs from whatever clear()/
        # addItems() already left it at), so relying on it to reach _on_index_changed()
        # would sometimes fire the update and sometimes silently not; the explicit calls
        # below every time this method runs are the one reliable path instead.
        self.combo.blockSignals(True)
        self.combo.clear()
        if self._chiplet_ids:
            self.combo.addItem(self.TOPOLOGY_LABEL)
            self.combo.addItems(self._chiplet_ids)
            self.combo.setCurrentIndex(index)
        self.combo.blockSignals(False)

        self.setVisible(len(chiplets) > 1)
        if chiplets:
            self._update_label(index, len(chiplets))
            self._fire(index)
        elif previous is self._TOPOLOGY:
            # no chiplets left at all (not just fewer than 2) - there's no real chiplet
            # entry left to fire _fire() with, but we still owe VectorWidget an explicit
            # exit from Topology Overview, or it would stay stuck showing a sketch for a
            # chiplet grouping that no longer exists
            self._on_topology_changed(False)

    def _on_index_changed(self, index):
        if index < 0 or index > len(self._chiplet_ids):
            return
        self._update_label(index, len(self._chiplet_ids))
        self._fire(index)

    def _fire(self, index):
        if index == 0:
            self._on_topology_changed(True)
        else:
            self._on_topology_changed(False)
            self._on_chiplet_changed(self._chiplet_ids[index - 1])

    def _update_label(self, index, total):
        if index == 0:
            self.label.setText(f"{self.TOPOLOGY_LABEL} ({total} chiplets):")
        else:
            self.label.setText(f"Chiplet {index} of {total}:")

    def step(self, direction):
        """Moves the combo box by one entry (Topology Overview counts as one), wrapping
        around at either end - called by VectorWidget.keyPressEvent() for Left(-1)/
        Right(+1). Goes through setCurrentIndex() (not a direct call to the on_*_changed
        callbacks), so this stays the single source of truth: the combo's own display
        always matches what's actually shown, however the switch was triggered. A no-op
        with 0-1 chiplets, same as the combo being hidden then.
        """
        if len(self._chiplet_ids) < 2:
            return
        total_items = len(self._chiplet_ids) + 1  # +1 for the Topology Overview entry
        new_index = (self.combo.currentIndex() + direction) % total_items
        self.combo.setCurrentIndex(new_index)

    def set_current_chiplet(self, chiplet_id):
        """Programmatically switches to a specific real chiplet by id (never to Topology
        Overview) - called by VectorWidget.select_element() when a selection made
        elsewhere (a table row, or a cross-window click from the Layout Preview) refers to
        an element that isn't part of the currently active chiplet, or is part of one while
        Topology Overview is active. Goes through setCurrentIndex(), same
        single-source-of-truth reasoning as step(). A no-op if chiplet_id isn't a currently
        known chiplet.
        """
        if chiplet_id not in self._chiplet_ids:
            return
        self.combo.setCurrentIndex(self._chiplet_ids.index(chiplet_id) + 1)
