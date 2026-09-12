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
from PySide6.QtWidgets import (
    QWidget, QFrame, QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsRectItem,
    QToolTip,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtCore import Qt, QRect, QRectF, Signal

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
        return f'Rs={material.Rs*1e3:.1f}mΩ'
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

def _build_dielectric_tooltip(dielectric):
    return (
        f"{dielectric.name}\n"
        f"Type: Dielectric\n"
        f"Material: {dielectric.material}\n"
        f"Zmin: {dielectric.zmin:.4f} µm\n"
        f"Zmax: {dielectric.zmax:.4f} µm\n"
        f"Thickness: {dielectric.thickness:.4f} µm"
    )


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
                            metal_label_fn, via_label_suffix_fn):
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
    "ref": dielectric_layer/metal_layer, "tooltip": str} dict per dielectric slab, metal,
    or via box - used to build the transparent hoverable/selectable overlay items. "key" is
    always the element's Name (unique within <Dielectrics>/<Layers> respectively), matching
    what the stackup editor's row_elements look up by.
    """
    draw_calls = []
    interactive_entries = []

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

    xmin = int(width * 0.02)
    xmax = int(width * 0.98)

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
    dielectrics_bottom_up = sorted(dielectrics_list.dielectrics, key=lambda d: d.zmin)
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
    w = xmax - ymin

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

        setPen(penBlack)
        setBrush(color)
        drawRect(xmin, flipy(y), w, -h)
        interactive_entries.append({
            "kind": "dielectric",
            "key": dielectric.name,
            "rect": QRectF(xmin, flipy(y), w, -h).normalized(),
            "ref": dielectric,
            "tooltip": _build_dielectric_tooltip(dielectric),
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

            # there could be multiple metals starting at the same zmin

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
                xmetal = xmin + 120
                wmetal = w - 200

                if n < len(metals_inside) - 1:
                    next_metal = metals_inside[n + 1]
                    if abs(next_metal.zmin - metal.zmin) < 0.001:
                        next_at_same_zmin = True
                        xmetal = xmin + 120
                        wmetal = int(w / 2) - 100
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
                })

                setPen(penBlack)
                drawText_left(xmetal + 10, flipy(ymetal), wmetal, part_height / 2, f"{metal.name} ({metal.layernum})")
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
                drawLine(xmetal - 60, flipy(ymetal), xmetal - 10, flipy(ymetal))
                # draw line at top side of metal
                if not metal.is_sheet:
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

        # next we draw the vias, based on the screen position of metals that we have stored
        # via position alternates between 3 positions along x axis
        pos = 1
        w = (xmax - xmin) / 10

        setBrush(QColor(136, 192, 200, 80))
        for metal in metals_list.metals:
            if metal.is_via or metal.is_dielectric:

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
                })
                drawTextAt(xvia + 5, flipy(y1 + 5), f"{metal.name} ({metal.layernum})" + label_suffix)

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

    def __init__(self, rect, kind, key, ref, tooltip):
        super().__init__(rect)
        self.setPen(Qt.NoPen)
        self.setBrush(Qt.NoBrush)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.info_text = tooltip
        self.kind = kind          # "dielectric" or "layer"
        self.key = key            # element Name, matching row_elements lookup in the editor
        self.ref = ref            # dielectric_layer or metal_layer instance

    def paint(self, painter, option, widget=None):
        # unselected: draw nothing, StackupBackgroundItem already drew the real
        # colors/labels underneath. Selected: a highlight outline instead of Qt's
        # default dashed selection rectangle, which would look wrong here.
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

        self._item_lookup = {}   # (kind, key) -> InteractiveRegionItem
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

    def _rebuild_scene(self):
        # keep whatever was selected (by identity of (kind, key), not by item, since
        # every item is recreated below) selected across the rebuild, so an edit to
        # the currently-selected layer doesn't make its preview highlight vanish
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

        draw_calls, interactive_entries = compute_stackup_layout(
            self.materials_list, self.dielectrics_list, self.metals_list,
            width, height,
            self.dielectric_color_fn, self.dielectric_label_fn,
            self.metal_label_fn, self.via_label_suffix_fn)

        scene.addItem(StackupBackgroundItem(draw_calls, width, height))

        for entry in interactive_entries:
            item = InteractiveRegionItem(entry["rect"], entry["kind"], entry["key"],
                                          entry["ref"], entry["tooltip"])
            scene.addItem(item)
            self._item_lookup[(entry["kind"], entry["key"])] = item

        scene.setSceneRect(0, 0, width, height)

        if previously_selected is not None and previously_selected in self._item_lookup:
            self._item_lookup[previously_selected].setSelected(True)

    def _selected_key(self):
        for key, item in self._item_lookup.items():
            if item.isSelected():
                return key
        return None

    def _on_scene_selection_changed(self):
        selected = self.scene().selectedItems()
        if not selected:
            # clicking empty background clears selection - dismiss any flyout left
            # showing from the previously-selected shape rather than stranding it
            QToolTip.hideText()
            return
        item = selected[0]
        self.elementSelected.emit(item.kind, item.key)

    def select_element(self, kind, name):
        """Selects/highlights the shape for (kind, name) - kind is "dielectric" or
        "layer". Called by the editor when a table row is selected, to keep the
        preview in sync with the table. A no-op if that shape is already the sole
        selection, so this doesn't bounce back into elementSelected/the editor's own
        selection-changed handling.
        """
        item = self._item_lookup.get((kind, name))
        if self.scene().selectedItems() == ([item] if item is not None else []):
            return
        self.scene().clearSelection()
        if item is not None:
            item.setSelected(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_scene()
