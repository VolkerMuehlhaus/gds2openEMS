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
stackupEditor.py

GUI editor for openEMS stackup XML files (see doc/XML_stackup_format.md):
Variables, Materials, the Dielectric stack, drawn Layers, and DerivedLayers
(boolean layer operations), with a live cross-section preview reusing
editor_common.VectorWidget. This is a standalone tool (no host application to be
opened from) - run it directly (`python stackupEditor.py [file.xml]`) or via the
`stackupEditor` console script installed with this package (see main() below and
pyproject.toml).

Ported from setupEM's stackupEditor.py (which targets gds2palace's Palace-format
stackup reader) to work against this repo's own, independently-maintained
gds2openEMS.stackup_reader. Per this workspace's convention (see CLAUDE.md), the
two editors are duplicated, not shared/symlinked.

Tables (thermal conductivity lookups) is not editable here. Loading goes
through this package's own stackup_writer.load_stackup_tree(), which preserves
XML comments, and only Variable/Material/Dielectric/Layer/Substrate/DerivedLayer
elements are ever touched, so Tables - and any comments in it - round-trips
untouched on save.
"""

import argparse
import ast
import copy
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import shiboken6
from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QLineEdit, QPlainTextEdit, QLabel, QFileDialog, QMessageBox,
    QColorDialog, QMenuBar, QInputDialog, QCompleter, QStyledItemDelegate, QStyleFactory,
)
from PySide6.QtGui import (
    QColor, QFontMetrics, QKeySequence, QAction, QFontDatabase,
    QSyntaxHighlighter, QTextCharFormat, QFont,
)
from PySide6.QtCore import Qt, QTimer, Signal, QStringListModel, QSettings

from gds2openEMS import stackup_reader

# __package__ is None/"" when this module was loaded outside the stackup_editor package
# (e.g. stackupEditor.py run directly), so relative import fails - same dual-mode
# pattern used throughout this package's own modules for their sibling imports.
if __package__ in (None, ""):
  import stackup_writer
  import momentum_import
else:
  from . import stackup_writer
  from . import momentum_import

# __package__ is None/"" when this file is run directly rather than imported
# as part of the stackup_editor package, so relative import fails.
if __package__ in (None, ""):
    from editor_common import (
        VectorWidget, ChipletSwitcher, epsilon_to_color,
        default_stackup_dielectric_label, default_stackup_metal_label,
    )
else:
    from .editor_common import (
        VectorWidget, ChipletSwitcher, epsilon_to_color,
        default_stackup_dielectric_label, default_stackup_metal_label,
    )

# QSettings scope for the "Open Recent" file list. Kept distinct from setupEM's own
# stackupEditor (which uses RECENT_FILES_APP="StackupEditor" under the same org) even
# though the file format is structurally identical - these edit openEMS-format
# stackups from a separate venv/toolchain, and mixing recent-file histories between
# the two editors would be confusing (e.g. a Palace-format file added to this app's
# recent list, or vice versa).
RECENT_FILES_ORG = "muehlhaus.com"
RECENT_FILES_APP = "OpenEMSStackupEditor"
RECENT_FILES_KEY = "recentFiles"
MAX_RECENT_FILES = 10


# ------------------------------------------------------------------
# Column specs: (attribute, header label, kind)
# kind in {"text", "computed", "materialtype", "layertype", "materialref",
#          "operationtype", "operands", "color", "variabletype", "referenceedge",
#          "dielectricref", "layerref_or_dielectricref", "tableref"}
# ------------------------------------------------------------------

# sentinel shown in the Type combo for "no Type set" (inferred from Value, the XML's own
# default when Type is omitted - see XML_stackup_format.md's <Variables> section); mapped back
# to "" (removes the attribute) when selected - never written to the XML. Same pattern as
# REFERENCE_NONE_LABEL below, just defined here since VARIABLE_TYPE_CHOICES needs it earlier.
VARIABLE_TYPE_AUTO_LABEL = "(auto)"
VARIABLE_TYPE_CHOICES = [VARIABLE_TYPE_AUTO_LABEL, "number", "string"]

VARIABLE_COLUMNS = [
    ("Name", "Name", "text"),
    ("Value", "Value", "text"),
    ("Type", "Type", "variabletype"),
    ("ResolvedValue", "Resolved Value", "computed"),
]

MATERIAL_COLUMNS = [
    ("Name", "Name", "text"),
    ("Type", "Type", "materialtype"),
    ("Permittivity", "Permittivity", "text"),
    ("DielectricLossTangent", "Loss Tangent", "text"),
    ("Conductivity", "Conductivity (S/m)", "text"),
    ("Rs", "Rs (Ohm/sq)", "text"),
    ("Density", "Density", "text"),
    ("ThermalConductivity", "Thermal Cond.", "text"),
    ("ThermalConductivityTable", "Thermal Table", "tableref"),
    ("Color", "Color", "color"),
]

DIELECTRIC_COLUMNS = [
    ("Name", "Name", "text"),
    ("Material", "Material", "materialref"),
    ("Reference", "Reference (optional)", "dielectricref"),
    ("ReferenceEdge", "Ref. Edge", "referenceedge"),
    ("Thickness", "Thickness", "text"),
    ("Zmin", "Zmin", "text"),
    ("Zmax", "Zmax", "text"),
    ("ResultZmin", "Zmin (resulting)", "computed"),
    ("ResultZmax", "Zmax (resulting)", "computed"),
    ("Boundary", "Optional Boundary (GDS layer #)", "text"),
]

LAYER_COLUMNS = [
    ("Name", "Name", "text"),
    ("Layer", "GDSII Layer #", "text"),
    ("Type", "Type", "layertype"),
    ("Material", "Material", "materialref"),
    ("Reference", "Reference (optional)", "layerref_or_dielectricref"),
    ("ReferenceEdge", "Ref. Edge", "referenceedge"),
    ("Zmin", "Zmin", "text"),
    ("Zmax", "Zmax", "text"),
    ("Thickness", "Thickness (resulting)", "computed"),
    ("ResultZmin", "Zmin (resulting)", "computed"),
    ("ResultZmax", "Zmax (resulting)", "computed"),
]

TABLE_COLUMNS = [
    ("Name", "Table name", "text"),
    ("PointCount", "Number of data points", "computed"),
]

POINT_COLUMNS = [
    ("Temperature", "Temperature (K)", "text"),
    ("Value", "Value", "text"),
]

REFERENCE_EDGE_CHOICES = ["Top", "Bottom"]

# sentinel shown in the Reference combo for "no Reference set" (absolute positioning);
# mapped back to "" (removes the attribute) when selected - never written to the XML
REFERENCE_NONE_LABEL = "(none)"


def _build_variables_list(variable_elements):
    """Resolve the current (possibly mid-edit) Variables tab state into a
       stackup_reader.variables_list, for the other tabs' live-preview compute functions to
       resolve "="-expressions against. Raises on invalid/circular data - callers wrap their
       own reader calls in try/except (Exception, SystemExit) already, so this is meant to
       propagate and blank their computed columns the same way an invalid Reference chain
       already does.
    """
    variables = stackup_reader.variables_list()
    for element in variable_elements:
        variables.append(stackup_reader.variable(element))
    variables.resolve_all()
    return variables


_INT_EXPRESSION_ATTRS = {"Layer", "Boundary"}


def _resolve_all_expressions(root, variables):
    """Rewrites every "="-expression attribute anywhere in the tree to its resolved
       literal value, in place - used by _convert_to_legacy_format() so a
       schemaVersion="2.0" file (predating <Variables>/"=" expressions) never contains
       one. "Layer" (on <Layer>/<DerivedLayer>/<Operand>) and "Boundary" (on
       <Dielectric>) are GDSII layer numbers and go through resolve_int_attr()'s
       integer-value check instead of the generic resolve_attr(). Raises/exits the
       same way resolve_attr()/resolve_int_attr() themselves do on an undefined
       variable or invalid expression.
    """
    for element in root.iter():
        for key, value in list(element.attrib.items()):
            if not (isinstance(value, str) and value.startswith("=")):
                continue
            if key in _INT_EXPRESSION_ATTRS:
                resolved = stackup_reader.resolve_int_attr(element, key, variables)
            else:
                resolved = stackup_reader.resolve_attr(element, key, None, variables)
            element.set(key, resolved)


def _format_resolved_variable_value(value):
    """Format a resolved Variable value (float or str, per util_stackup_reader.variable.value)
       as literal text for direct use in an XML attribute - a whole-number float (e.g. 134.0,
       the common case for something like a GDSII layer number) is written without a
       trailing ".0", matching how such values are normally hand-typed in this format.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _substitute_variable_in_expression(value, deleted_name, resolved_value):
    """Rewrites a single "="-expression attribute value, replacing every bare reference to
       deleted_name with its resolved literal value - used when a Variable is deleted, so
       every remaining use of it keeps working instead of becoming a dangling reference to
       an undefined variable. If the whole expression was just that one variable reference
       (the common case - also the ONLY case possible for a string-typed variable, which
       XML_stackup_format.md only allows as the sole token of an expression), the result
       collapses to a plain literal (no leading "="); otherwise "=" and the surrounding
       expression structure are kept, with just that one identifier replaced by a numeric
       constant.
    Returns:
        string: the new attribute value, unchanged if deleted_name doesn't appear in it
    Raises:
        SyntaxError: if value isn't a well-formed expression - callers should skip on this,
          same as elsewhere in this module (should not happen for an already-valid file)
    """
    expr_tree = ast.parse(value[1:], mode="eval")
    if isinstance(expr_tree.body, ast.Name) and expr_tree.body.id == deleted_name:
        return _format_resolved_variable_value(resolved_value)

    if not any(isinstance(node, ast.Name) and node.id == deleted_name for node in ast.walk(expr_tree)):
        return value

    # whole-number float -> int, same "no trailing .0" cleanup as the sole-token case above -
    # only reachable with a number-valued resolved_value: a string variable can only appear as
    # the sole token of an expression (see docstring), so it never reaches this branch
    constant_value = int(resolved_value) if isinstance(resolved_value, float) and resolved_value.is_integer() else resolved_value

    class _ReplaceName(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == deleted_name:
                return ast.copy_location(ast.Constant(value=constant_value), node)
            return node

    new_tree = _ReplaceName().visit(expr_tree)
    ast.fix_missing_locations(new_tree)
    return "=" + ast.unparse(new_tree.body)


def _resolve_variable_uses(root, deleted_name, resolved_value, skip_element):
    """Walks every attribute anywhere in the tree (Materials, Dielectrics, Layers, other
       Variables, Substrate, DerivedLayers, Tables) and rewrites every reference to
       deleted_name via _substitute_variable_in_expression(), in place. skip_element is the
       <Variable> about to be removed itself - excluded so its own Value isn't rewritten
       right before it's deleted.
    """
    for element in root.iter():
        if element is skip_element:
            continue
        for key, value in list(element.attrib.items()):
            if not (isinstance(value, str) and value.startswith("=")):
                continue
            try:
                new_value = _substitute_variable_in_expression(value, deleted_name, resolved_value)
            except SyntaxError:
                continue
            if new_value != value:
                element.set(key, new_value)


def _compute_variable_values(elements):
    """Read-only ResolvedValue column for the Variables tab: each row's evaluated value,
       annotated with the resolved type in brackets (e.g. "0.96 (number)", "SG13G2
       (string)") since a "="-expression's result type isn't always obvious from Value
       alone. Blank while the current (possibly mid-edit) data can't resolve yet - same
       defensive pattern as _compute_dielectric_zpositions/_compute_layer_zpositions.
    """
    try:
        variables = _build_variables_list(elements)
    except (Exception, SystemExit):
        return {}
    computed = {}
    for element, var in zip(elements, variables.variables):
        resolved_type = "number" if isinstance(var.value, float) else "string"
        computed[id(element)] = {"ResolvedValue": f"{var.value} ({resolved_type})"}
    return computed


def _compute_layer_thickness(elements):
    """Read-only Thickness column for the Layers tab: Zmax - Zmin, recomputed
       whenever either changes. Blank while Zmin/Zmax aren't both valid numbers yet
       (e.g. mid-edit), rather than raising.
    """
    computed = {}
    for element in elements:
        try:
            thickness = float(element.get("Zmax")) - float(element.get("Zmin"))
            text = f"{thickness:.4f}"
        except (TypeError, ValueError):
            text = ""
        computed[id(element)] = {"Thickness": text}
    return computed


def _compute_table_point_counts(elements):
    """Read-only "Number of data points" column for the Thermal Tables tab: how many
       <Point> children each <Table> currently has, so the master list stays informative
       without needing to open each table in the detail editor to see its size.
    """
    return {id(element): {"PointCount": f"{len(element.findall('Point'))} data points"} for element in elements}


def _compute_layer_zpositions(elements, dielectrics_elements, variables, offset=0.0):
    """Read-only ResultZmin/ResultZmax columns for the Layers tab: the absolute
       resolved z-position for every row, whether it's plain absolute Zmin/Zmax or
       Reference-based (offset from a Dielectric/Layer edge) - this is the main
       point of Reference-based positioning, so it stays visible regardless of which
       kind a given row uses. Runs the same resolution the reader uses
       (dielectric_layers_list.calculate_zpositions() +
       metal_layers_list.resolve_references() + metal_layers_list.add_offset())
       over the current (possibly mid-edit) Dielectrics/Layers tab state. Returns {}
       - blanking those columns - if the current data isn't complete/valid enough to
       resolve yet (including a dangling/ambiguous/circular Reference, which the
       reader reports via exit(1) rather than a normal exception - see
       _refresh_preview() for the same pattern).
    Args:
        variables (stackup_reader.variables_list): current Variables tab state, resolved -
            see _build_variables_list() - for resolving any "="-expression among these
            Dielectrics'/Layers' attributes.
        offset (float): the file's <Substrate Offset>, if any. Only applied when no
            Layer uses Reference, exactly like parse_substrate() does - Reference and
            a nonzero Offset are mutually exclusive (see validate_stackup()), so a
            file with any Reference-based Layer never reaches add_offset() there either.
    """
    try:
        dielectrics_list = stackup_reader.dielectric_layers_list()
        for element in dielectrics_elements:
            dielectrics_list.append(stackup_reader.dielectric_layer(element, variables), None)
        dielectrics_list.calculate_zpositions()

        metals_list = stackup_reader.metal_layers_list()
        for element in elements:
            metals_list.append(stackup_reader.metal_layer(element, variables))
        metals_list.resolve_references(dielectrics_list)
        if offset and not metals_list.has_references():
            metals_list.add_offset(offset)
    except (Exception, SystemExit):
        return {}

    computed = {}
    for element, metal in zip(elements, metals_list.metals):
        computed[id(element)] = {
            "ResultZmin": f"{metal.zmin:.4f}" if metal.zmin is not None else "",
            "ResultZmax": f"{metal.zmax:.4f}" if metal.zmax is not None else "",
        }
    return computed


# ------------------------------------------------------------------
# Derived Layers tab: boolean/resize operations on other layers (see
# derived_layers.md). Operands are edited as one comma-separated column rather
# than a variable number of sub-columns - AND/OR/XOR/NOT take 2+ operands
# (unbounded), SIZE takes exactly 1, so a fixed set of "Operand1/2/3..."
# columns would either not scale or waste space depending on the row. Order
# is preserved left-to-right as typed, which matters for NOT (first operand
# minus all the following ones).
# ------------------------------------------------------------------

DERIVED_LAYER_COLUMNS = [
    ("Name", "Name", "text"),
    ("Layer", "Target Layer #", "text"),
    ("Operation", "Operation", "operationtype"),
    ("Oversize", "Oversize", "text"),
    ("Operands", "Operands (GDSII layer numbers)", "operands"),
]


# ------------------------------------------------------------------
# Materials tab: some columns don't apply to every Material Type, and
# showing their (meaningless) default value is just noise. These attributes
# are silently omitted from the XML for the types they don't apply to - the
# reader already falls back to the same default (Permittivity=1,
# DielectricLossTangent=0, Conductivity=0, Density=1, ThermalConductivity=0)
# when the attribute is absent, so omitting it changes nothing functionally.
# ------------------------------------------------------------------

_MATERIAL_NOT_APPLICABLE_ATTRS = {
    "CONDUCTOR": {"Permittivity", "DielectricLossTangent", "Rs"},
    "DIELECTRIC": {"Rs","Conductivity"},
    "SEMICONDUCTOR": {"Rs"},
    "RESISTOR": {"Permittivity", "DielectricLossTangent", "Conductivity",
                 "Density", "ThermalConductivity", "ThermalConductivityTable"},
}


def _material_not_applicable(element, attr):
    mtype = (element.get("Type") or "").upper()
    return attr in _MATERIAL_NOT_APPLICABLE_ATTRS.get(mtype, ())


def _strip_not_applicable_material_attrs(element):
    mtype = (element.get("Type") or "").upper()
    for attr in _MATERIAL_NOT_APPLICABLE_ATTRS.get(mtype, ()):
        if attr in element.attrib:
            del element.attrib[attr]


def _material_blank_if_default(element, attr, value):
    # Dielectric materials always carry a Conductivity attribute in practice
    # (usually "0", the default) - not wrong, just clutter; still editable in
    # case an unusual lossy dielectric needs a nonzero value.
    mtype = (element.get("Type") or "").upper()
    if mtype == "DIELECTRIC" and attr == "Conductivity":
        return value in ("", "0", "0.0")
    return False


# ------------------------------------------------------------------
# Dielectric Stack tab: a dielectric is positioned one of three ways - absolute
# (explicit Zmin/Zmax), Reference-relative (offset from another Dielectric's edge,
# Thickness sizing it by default), or implicit (Thickness-stacked on its neighbors,
# top-to-bottom, by dielectric_layers_list.calculate_zpositions()). The "resulting"
# columns show the computed position in all three cases, so the effective z-range is
# always visible; Zmin/Zmax/Thickness are grayed out for whichever mode isn't that
# row's actual source of truth.
# ------------------------------------------------------------------

def _dielectric_position_mode(element):
    if element.get("Reference"):
        return "reference"
    if element.get("Zmin") and element.get("Zmax"):
        return "absolute"
    return "thickness"


def _dielectric_gray_fn(element, attr):
    mode = _dielectric_position_mode(element)
    if attr == "Thickness":
        return mode == "absolute"  # unused/ignored once Zmin+Zmax fix the position
    return False


def _compute_dielectric_zpositions(elements, variables):
    """Runs the same resolution the reader uses (dielectric_layers_list.calculate_zpositions(),
       covering absolute/Reference/implicit-stacked dielectrics alike) over the current (possibly
       mid-edit) Dielectric elements, so the "resulting" columns show real effective z-positions.
       Returns {} - blanking those columns - if the current data isn't complete/valid enough to
       compute yet, including a dangling/ambiguous/circular Reference, which the reader reports
       via exit(1) rather than a normal exception - see _refresh_preview() for the same pattern.
    Args:
        variables (stackup_reader.variables_list): current Variables tab state, resolved - see
            _build_variables_list() - for resolving any "="-expression among these attributes.
    """
    try:
        dielectrics_list = stackup_reader.dielectric_layers_list()
        for element in elements:
            dielectrics_list.append(stackup_reader.dielectric_layer(element, variables), None)
        dielectrics_list.calculate_zpositions()
    except (Exception, SystemExit):
        return {}

    computed = {}
    for element, dielectric in zip(elements, dielectrics_list.dielectrics):
        computed[id(element)] = {
            "ResultZmin": f"{dielectric.zmin:.4f}" if dielectric.zmin is not None else "",
            "ResultZmax": f"{dielectric.zmax:.4f}" if dielectric.zmax is not None else "",
        }
    return computed


class NoScrollComboBox(QComboBox):
    """QComboBox that ignores the mouse wheel, so scrolling the table this combo
       sits in doesn't silently change the combo's value when the cursor happens
       to pass over it - only an actual dropdown click can change the selection.
    """

    def wheelEvent(self, event):
        event.ignore()


class _CommitOnFocusOutTextEdit(QPlainTextEdit):
    """QPlainTextEdit that emits editingFinished (like QLineEdit) when it loses
       focus, so a free-text field commits as one edit on focus-out rather than
       one undo-snapshot per keystroke.
    """

    editingFinished = Signal()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()


class _XmlSyntaxHighlighter(QSyntaxHighlighter):
    """Basic XML syntax highlighter for the read-only XML Preview tab: tag names,
       attribute names, quoted attribute values, and comments (including multi-line
       ones, e.g. a multi-line File Description stamped as a header comment) each get
       their own color. Re-run by Qt automatically whenever setPlainText() replaces
       the document's whole text, which is the only way this text ever changes -
       there is no interactive editing to keep up with.
    """

    _COMMENT_BLOCK_STATE = 1

    def __init__(self, document):
        super().__init__(document)

        def make_format(color, bold=False, italic=False):
            text_format = QTextCharFormat()
            text_format.setForeground(QColor(color))
            if bold:
                text_format.setFontWeight(QFont.Bold)
            text_format.setFontItalic(italic)
            return text_format

        self._tag_format = make_format("#0000AA", bold=True)
        self._attr_name_format = make_format("#880000")
        self._attr_value_format = make_format("#008000")
        self._decl_format = make_format("#555555", italic=True)
        self._comment_format = make_format("#808080", italic=True)

        self._tag_pattern = re.compile(r"</?\s*([A-Za-z_][\w.:-]*)")
        self._attr_name_pattern = re.compile(r"\b([A-Za-z_][\w.:-]*)(?=\s*=\s*\")")
        self._attr_value_pattern = re.compile(r'"[^"]*"')
        self._decl_pattern = re.compile(r"<\?.*?\?>")

    def highlightBlock(self, text):
        # applied first - any accidental match inside a comment's own text (e.g. a
        # File Description that happens to mention "<Layer>") is overwritten by the
        # comment formatting pass at the end, which always wins
        for match in self._decl_pattern.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._decl_format)
        for match in self._tag_pattern.finditer(text):
            self.setFormat(match.start(1), match.end(1) - match.start(1), self._tag_format)
        for match in self._attr_name_pattern.finditer(text):
            self.setFormat(match.start(1), match.end(1) - match.start(1), self._attr_name_format)
        for match in self._attr_value_pattern.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._attr_value_format)

        # multi-line <!-- comment --> spans: start at column 0 while continuing a
        # comment from the previous block (previousBlockState() is unaffected by
        # anything done in this call, so it still reflects that block's own result)
        self.setCurrentBlockState(0)
        start = 0 if self.previousBlockState() == self._COMMENT_BLOCK_STATE else text.find("<!--")
        while start >= 0:
            end = text.find("-->", start)
            if end == -1:
                self.setFormat(start, len(text) - start, self._comment_format)
                self.setCurrentBlockState(self._COMMENT_BLOCK_STATE)
                break
            length = end - start + len("-->")
            self.setFormat(start, length, self._comment_format)
            start = text.find("<!--", start + length)


def _unique_name(existing_names, base):
    if base not in existing_names:
        return base
    n = 2
    while f"{base}{n}" in existing_names:
        n += 1
    return f"{base}{n}"


class _VariableCompletionDelegate(QStyledItemDelegate):
    """QStyledItemDelegate that attaches a QCompleter to a "text" cell's editor, offering
       "=name" completions for every currently-declared Variable - lets a user start typing
       "=" and see/select a matching variable name from a popup, in any cell that might hold
       a "="-prefixed expression (Materials/Dielectrics/Layers/DerivedLayers numeric columns,
       and Variables' own Value column for variable-referencing-variable formulas).

       The completer's word list is rebuilt fresh every time an editor is created (i.e. every
       time a cell is actually opened for editing), not cached - so it can never go stale as
       variables are added/renamed/removed, with no separate refresh call needed.
    """

    def __init__(self, variable_names_fn, parent=None):
        super().__init__(parent)
        self.variable_names_fn = variable_names_fn

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            names = self.variable_names_fn() or []
            completer = QCompleter(["=" + name for name in names], editor)
            completer.setCaseSensitivity(Qt.CaseSensitive)
            completer.setFilterMode(Qt.MatchStartsWith)
            editor.setCompleter(completer)
        return editor


# ------------------------------------------------------------------
# Generic table editor for one XML element type (Material / Dielectric / Layer)
# ------------------------------------------------------------------

class ElementTableEditor(QWidget):
    """Editable QTableWidget bound to a list of same-tag XML elements. Each row is
       kept in lockstep with its Element via self.row_elements (parallel list, not
       stored in the table itself, since some columns use cell widgets).
    """

    _GRAY = QColor(235, 235, 235)
    _COMPUTED_TEXT = QColor(0, 128, 0)
    _INVALID_TEXT = QColor("darkred")

    def __init__(self, columns, container_fn, add_fn, remove_fn, default_attrs_fn, on_changed,
                 move_fn=None, material_choices_fn=None, type_choices=None,
                 strip_fn=None, not_applicable_fn=None, blank_if_default_fn=None,
                 reload_on_attr_change=frozenset(), compute_fn=None, gray_fn=None,
                 pre_set_attr_fn=None, reference_choices_fn=None,
                 header_tooltips=None, operand_lookup_fn=None, variable_names_fn=None,
                 invalid_fn=None, table_choices_fn=None, reorder_fn=None,
                 descending_attrs=frozenset()):
        """container_fn(root) -> list[Element]: fetches the current rows to display,
           re-called by reload() so the editor can refresh itself after any structural
           change (add/remove/move) without the caller having to re-fetch and hand
           back the list every time.

           strip_fn(element): called once per row on every reload, to silently drop
             attributes that don't apply given the row's current values (e.g. a
             Conductor material's Permittivity) so the XML doesn't accumulate
             meaningless defaults - the reader already defaults them on read.
           not_applicable_fn(element, attr) -> bool: for "text" columns, forces a
             blank, read-only display (the value is fixed at its default and not
             user-editable in this row's context).
           blank_if_default_fn(element, attr, value) -> bool: for "text" columns,
             shows blank instead of a value that's just the (uninteresting) default,
             while leaving the cell normally editable.
           reload_on_attr_change: attribute names whose change should trigger a full
             self.reload() (e.g. "Type", since it changes which columns apply).
           compute_fn(elements) -> {id(element): {attr: display_str}}: called once per
             reload() (not per row, since e.g. dielectric z-stacking needs the whole
             ordered list at once), feeding "computed" kind columns - values that are
             derived, not stored as an XML attribute, and therefore always read-only.
           gray_fn(element, attr) -> bool: tints a "text" or "computed" cell's
             background gray without affecting whether it's editable - use this
             (instead of not_applicable_fn) when a column is still meaningful/editable
             but just isn't the row's current source of truth (e.g. absolute Zmin/Zmax
             on a row that's actually using Thickness-based auto-stacking).
           pre_set_attr_fn(element, attr, new_value) -> bool: called before a "text"
             column's value is applied, with the element still unmodified (so the
             hook can read the old value itself); if it returns True it has fully
             handled applying the change (and any side effects, e.g. a confirmation
             dialog with cross-tab consequences) and the normal element.set()/attrib
             deletion is skipped; False means apply the value normally.
           reference_choices_fn() -> list[str]: choices for the "layerref_or_dielectricref"/
             "dielectricref" kinds. For Layers this combines two different element containers
             (Dielectrics + Layers) - unlike material_choices_fn, which only ever spans one; for
             Dielectrics it's Dielectric names only (a Dielectric's Reference can't target a
             Layer - Layers are resolved after Dielectrics).
           table_choices_fn() -> list[str]: declared Table names, for the "tableref" kind
             (Materials' ThermalConductivityTable column).
           header_tooltips: {attr: tooltip text} for columns whose header label alone
             could be misread (e.g. Zmin/Zmax meaning different things depending on
             whether the row uses Reference).
           operand_lookup_fn() -> {layer number string: layer name}: for the "operands"
             kind, used to build a per-cell tooltip resolving each GDSII layer number to
             its Layers-tab Name where possible, falling back to the bare number for
             whichever operands don't resolve (e.g. a pure intermediate derived layer
             with no <Layer> entry of its own).
           variable_names_fn() -> list[str], optional: current declared Variable names, used
             to attach a QCompleter to every "text" column's editor (see
             _VariableCompletionDelegate) - lets a user type "=" and pick a matching variable
             from a popup instead of typing the full name. Omit for a tab where this doesn't
             make sense (there currently isn't one, but the param stays optional for safety).
           invalid_fn(element, attr) -> bool: for "text" columns, marks a cell's text
             (not background, unlike gray_fn) dark red - used for the one specific
             field whose edit was what just made the whole file invalid (see
             StackupEditorWindow._is_invalid_field()), so the user's eye lands on the
             actual cause instead of just the generic status line/Save error list.
           reorder_fn(root, ordered_elements): reorders the underlying XML elements
             to match ordered_elements, enabling click-a-header-to-sort (by that
             column's current value) on every "text"/"computed" column. This is a
             one-time reorder, not a persistent "stay sorted" mode - editing/adding
             rows afterward doesn't re-sort, so a new row being filled in doesn't
             jump around before it's finished. Omit to leave headers unclickable.
           descending_attrs: attribute names that should sort largest-first when
             their header is clicked (e.g. a z-position column, so the physically
             topmost layer lands at the top of the list) - every other numeric
             column sorts smallest-first. A row whose value can't be parsed as a
             number always sorts last, regardless of direction.
        """
        super().__init__()
        self.columns = columns
        self.container_fn = container_fn
        self.add_fn = add_fn
        self.remove_fn = remove_fn
        self.move_fn = move_fn
        self.default_attrs_fn = default_attrs_fn
        self.material_choices_fn = material_choices_fn
        self.operand_lookup_fn = operand_lookup_fn
        self.reference_choices_fn = reference_choices_fn
        self.table_choices_fn = table_choices_fn
        self.type_choices = type_choices or []
        self.on_changed = on_changed
        self.strip_fn = strip_fn
        self.not_applicable_fn = not_applicable_fn
        self.blank_if_default_fn = blank_if_default_fn
        self.reload_on_attr_change = reload_on_attr_change
        self.compute_fn = compute_fn
        self.gray_fn = gray_fn
        self.invalid_fn = invalid_fn
        self.pre_set_attr_fn = pre_set_attr_fn
        self.reorder_fn = reorder_fn
        self.descending_attrs = descending_attrs

        self.root = None
        self.row_elements = []
        self._computed = {}
        self._loading = False

        layout = QVBoxLayout()

        self.table = QTableWidget()
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([c[1] for c in columns])
        if header_tooltips:
            for col, (attr, _header, _kind) in enumerate(columns):
                tooltip = header_tooltips.get(attr)
                if tooltip:
                    self.table.horizontalHeaderItem(col).setToolTip(tooltip)
        if reorder_fn is not None:
            # click-to-sort only makes sense for a plain value column - "text"
            # (e.g. Name) or "computed" (e.g. the resolved ResultZmin), not a
            # combo-box/button kind - append to any header_tooltips text already set
            for col, (attr, _header, kind) in enumerate(columns):
                if kind in ("text", "computed"):
                    item = self.table.horizontalHeaderItem(col)
                    hint = ("Click to sort by this column (largest first)"
                            if attr in descending_attrs else "Click to sort by this column")
                    item.setToolTip(f"{item.toolTip()}\n{hint}" if item.toolTip() else hint)
            self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        for col in range(len(columns)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        # the last column stretches to fill leftover width (above) - its header label
        # defaults to centered like every other column, which reads oddly once it's
        # sitting in a much wider column than its text needs; left-align just this one -
        # except on the Materials tab, whose last column is a small Color swatch button,
        # not a stretched text value, so its header stays centered like the button below it
        if columns is not MATERIAL_COLUMNS:
            last_header_item = self.table.horizontalHeaderItem(len(columns) - 1)
            if last_header_item:
                last_header_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.itemChanged.connect(self._on_item_changed)

        if variable_names_fn:
            # kept as an attribute (not just a local) so the delegate - which the table only
            # holds a Qt-level reference to - isn't garbage-collected on the Python side
            self._completion_delegate = _VariableCompletionDelegate(variable_names_fn, self.table)
            for col, (_attr, _header, kind) in enumerate(columns):
                if kind == "text":
                    self.table.setItemDelegateForColumn(col, self._completion_delegate)

        layout.addWidget(self.table)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add")
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(self._on_add_clicked)
        button_row.addWidget(self.add_button)

        self.remove_button = QPushButton("Remove")
        self.remove_button.setAutoDefault(False)
        self.remove_button.clicked.connect(self._on_remove_clicked)
        button_row.addWidget(self.remove_button)

        if self.move_fn is not None:
            self.up_button = QPushButton("Move Up")
            self.up_button.setAutoDefault(False)
            self.up_button.clicked.connect(lambda: self._on_move_clicked(-1))
            button_row.addWidget(self.up_button)

            self.down_button = QPushButton("Move Down")
            self.down_button.setAutoDefault(False)
            self.down_button.clicked.connect(lambda: self._on_move_clicked(+1))
            button_row.addWidget(self.down_button)

        button_row.addStretch()
        layout.addLayout(button_row)

        self.setLayout(layout)

    # ---------- data binding ----------

    def set_root(self, root):
        self.root = root
        self.reload()

    def reload(self):
        self._loading = True
        self.table.setRowCount(0)
        self.row_elements = list(self.container_fn(self.root)) if self.root is not None else []
        self._computed = self.compute_fn(self.row_elements) if self.compute_fn else {}
        self.table.setRowCount(len(self.row_elements))
        for row, element in enumerate(self.row_elements):
            self._populate_row(row, element)
        self._loading = False

    def _populate_row(self, row, element):
        if self.strip_fn:
            self.strip_fn(element)
        for col, (attr, _header, kind) in enumerate(self.columns):
            value = element.get(attr, "")
            if kind == "text":
                not_applicable = bool(self.not_applicable_fn and self.not_applicable_fn(element, attr))
                blank = not_applicable or bool(self.blank_if_default_fn and self.blank_if_default_fn(element, attr, value))
                item = QTableWidgetItem("" if blank else value)
                if not_applicable:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setBackground(self._GRAY)
                elif self.gray_fn and self.gray_fn(element, attr):
                    item.setBackground(self._GRAY)
                if self.invalid_fn and self.invalid_fn(element, attr):
                    item.setForeground(self._INVALID_TEXT)
                self.table.setItem(row, col, item)
            elif kind == "computed":
                # computed cells are always derived/read-only - marked with green text
                # instead of gray_fn's background dimming, which is for editable-but-
                # currently-inapplicable "text" cells, a different situation
                computed_value = self._computed.get(id(element), {}).get(attr, "")
                item = QTableWidgetItem(computed_value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setForeground(self._COMPUTED_TEXT)
                self.table.setItem(row, col, item)
            elif kind == "color":
                self._make_color_cell(row, col, element, attr, value)
            elif kind in ("materialtype", "layertype", "operationtype", "referenceedge"):
                choices = REFERENCE_EDGE_CHOICES if kind == "referenceedge" else self.type_choices
                self._make_combo_cell(row, col, element, attr, value, choices, editable=False)
            elif kind == "variabletype":
                self._make_combo_cell(row, col, element, attr, value or VARIABLE_TYPE_AUTO_LABEL,
                                       self.type_choices, editable=False,
                                       value_out_fn=lambda text: "" if text == VARIABLE_TYPE_AUTO_LABEL else text)
            elif kind == "materialref":
                choices = self.material_choices_fn() if self.material_choices_fn else []
                self._make_combo_cell(row, col, element, attr, value, choices, editable=True)
            elif kind in ("layerref_or_dielectricref", "dielectricref"):
                choices = [REFERENCE_NONE_LABEL] + (self.reference_choices_fn() if self.reference_choices_fn else [])
                self._make_combo_cell(row, col, element, attr, value or REFERENCE_NONE_LABEL, choices, editable=True,
                                       value_out_fn=lambda text: "" if text == REFERENCE_NONE_LABEL else text)
            elif kind == "tableref":
                not_applicable = bool(self.not_applicable_fn and self.not_applicable_fn(element, attr))
                choices = [REFERENCE_NONE_LABEL] + (self.table_choices_fn() if self.table_choices_fn else [])
                self._make_combo_cell(row, col, element, attr, value or REFERENCE_NONE_LABEL, choices, editable=True,
                                       value_out_fn=lambda text: "" if text == REFERENCE_NONE_LABEL else text,
                                       enabled=not not_applicable)
            elif kind == "operands":
                operand_numbers = stackup_writer.get_operand_layers(element)
                item = QTableWidgetItem(", ".join(operand_numbers))
                if self.operand_lookup_fn and operand_numbers:
                    lookup = self.operand_lookup_fn()
                    item.setToolTip(", ".join(lookup.get(num, num) for num in operand_numbers))
                self.table.setItem(row, col, item)

    def _make_combo_cell(self, row, col, element, attr, value, choices, editable, value_out_fn=None, enabled=True):
        combo = NoScrollComboBox()
        combo.setEditable(editable)
        combo.setEnabled(enabled)
        items = list(choices)
        if value and value not in items:
            items = [value] + items
        combo.addItems(items)
        if value:
            combo.setCurrentText(value)

        def _emit(text, el=element, a=attr):
            self._set_attr(el, a, value_out_fn(text) if value_out_fn else text)

        combo.currentTextChanged.connect(_emit)
        self.table.setCellWidget(row, col, combo)

    def _make_color_cell(self, row, col, element, attr, value):
        button = QPushButton(("#" + value) if value else "(choose)")
        button.setAutoDefault(False)
        self._style_color_button(button, value)

        def pick_color(_checked=False, el=element, a=attr, btn=button):
            initial = QColor("#" + value) if value else QColor("white")
            color = QColorDialog.getColor(initial, self)
            if color.isValid():
                hexcode = color.name().lstrip("#")
                btn.setText("#" + hexcode)
                self._style_color_button(btn, hexcode)
                self._set_attr(el, a, hexcode)

        button.clicked.connect(pick_color)
        self.table.setCellWidget(row, col, button)

    def _style_color_button(self, button, hex_value):
        if hex_value:
            button.setStyleSheet(f"background-color: #{hex_value};")
        else:
            button.setStyleSheet("")

    # ---------- edit handlers ----------

    def _set_attr(self, element, attr, value):
        if self._loading:
            return
        if self.pre_set_attr_fn and self.pre_set_attr_fn(element, attr, value):
            pass  # hook fully handled applying the value (and any side effects)
        elif value == "":
            if attr in element.attrib:
                del element.attrib[attr]
        else:
            element.set(attr, value)
        # only a "text" column is a free-typed value that can plausibly be "the"
        # cause of a validation error by itself (see invalid_fn/_populate_row) -
        # combo/color cells are constrained to picked choices, not blamed here
        kind = next((k for a, _h, k in self.columns if a == attr), None)
        edited_field = (element, attr) if kind == "text" else None
        if attr in self.reload_on_attr_change:
            # deferred: this may be firing from inside the very cell widget (e.g. a
            # combo box) that reload() is about to tear down and recreate, so let the
            # current signal/event finish unwinding first
            QTimer.singleShot(0, lambda ef=edited_field: self._reload_and_notify(ef))
        else:
            self.on_changed(edited_field=edited_field)

    def _reload_and_notify(self, edited_field=None):
        self.reload()
        self.on_changed(edited_field=edited_field)

    def _set_operands(self, element, text):
        if self._loading:
            return
        layer_numbers = [part.strip() for part in text.split(",") if part.strip() != ""]
        stackup_writer.set_operands(element, layer_numbers)
        self.on_changed()

    def _on_item_changed(self, item):
        if self._loading:
            return
        row = item.row()
        col = item.column()
        if row >= len(self.row_elements):
            return
        attr, _header, kind = self.columns[col]
        element = self.row_elements[row]
        if kind == "operands":
            self._set_operands(element, item.text())
        else:
            self._set_attr(element, attr, item.text())

    def _on_add_clicked(self):
        if self.root is None:
            return
        attrs = self.default_attrs_fn()
        self.add_fn(self.root, **attrs)
        self.reload()
        self.on_changed(structural=True)

    def _on_remove_clicked(self):
        selected = self.table.selectedIndexes()
        if not selected:
            return
        row = selected[0].row()
        if row >= len(self.row_elements):
            return
        element = self.row_elements[row]
        self.remove_fn(self.root, element)
        self.reload()
        self.on_changed(structural=True)

    def _on_move_clicked(self, direction):
        selected = self.table.selectedIndexes()
        if not selected or self.move_fn is None:
            return
        row = selected[0].row()
        if row >= len(self.row_elements):
            return
        element = self.row_elements[row]
        self.move_fn(self.root, element, direction)
        self.reload()
        new_row = row + direction
        if 0 <= new_row < self.table.rowCount():
            self.table.selectRow(new_row)
        self.on_changed(structural=True)

    def _on_header_clicked(self, col):
        # a one-time reorder (see reorder_fn's docstring above), not a persistent
        # sort mode - reload() below rebuilds the table from the new element
        # order, but nothing here keeps re-sorting it as values change afterward
        if self.reorder_fn is None or not self.row_elements:
            return
        attr, _header, kind = self.columns[col]

        def sort_key(element):
            if kind == "computed":
                text = self._computed.get(id(element), {}).get(attr, "")
            else:
                text = element.get(attr, "") or ""
            try:
                value = float(text)
                if attr in self.descending_attrs:
                    value = -value
                return (0, value)
            except (TypeError, ValueError):
                # non-numeric (e.g. Name) or blank (e.g. a row whose Z couldn't be
                # resolved) - sort after every numeric value, regardless of direction
                return (1, text)

        ordered = sorted(self.row_elements, key=sort_key)
        if ordered == self.row_elements:
            return
        self.reorder_fn(self.root, ordered)
        self.reload()
        self.on_changed(structural=True)


# ------------------------------------------------------------------
# Separate, resizable preview window (the editing tables need the space more
# than a squeezed-in preview pane does)
# ------------------------------------------------------------------

class StackupPreviewWindow(QWidget):
    """Own top-level window for the live stackup cross-section preview, so it
       gets real screen space instead of sharing the editor window with the
       editing tables. Reuses the same VectorWidget instance as the editor -
       updates happen by calling that widget's refresh(), so this window
       doesn't need any refresh logic of its own.

    Deliberately NOT WA_DeleteOnClose: this window's layout owns the shared
    VectorWidget (addWidget() reparents it), so destroying this window on
    close would destroy that widget too, breaking the editor that still
    references it. Closing (the X button) just hides the window instead.

    Deliberately constructed with NO Qt parent (see StackupEditorWindow,
    which passes none): on Windows, any widget with a Qt parent gets a native
    "owner" window set, and an owned window always stays above its owner
    regardless of focus - the preview would permanently float over the
    editor. Neither QDialog(parent, Qt.Window) nor QWidget(parent, Qt.Window)
    stopped this in testing; only removing the parent relationship entirely
    did. Without a Qt parent there is no automatic cascade-delete when the
    editor closes, so StackupEditorWindow.closeEvent() explicitly calls
    deleteLater() on this window instead of relying on Qt object-tree cleanup.
    """

    def __init__(self, vector_widget, parent=None, chiplet_switcher=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Stackup Preview")
        self.resize(700, 900)

        # vector_widget is a QGraphicsView, already self-scrolling - no QScrollArea
        # wrapper needed (or wanted: it would nest a second set of scrollbars).
        layout = QVBoxLayout()
        if chiplet_switcher is not None:
            layout.addWidget(chiplet_switcher)
        layout.addWidget(vector_widget)
        self.setLayout(layout)

    def closeEvent(self, event):
        event.ignore()
        self.hide()


# ------------------------------------------------------------------
# Main editor window
# ------------------------------------------------------------------

class StackupEditorWindow(QDialog):
    """Non-modal editor window for stackup XML files. The live cross-section
       preview lives in its own StackupPreviewWindow (see above) rather than
       being embedded here, so both windows can be sized/moved independently.
    """

    UNDO_LEVELS = 3

    def __init__(self, MainWindow, initial_filename=None):
        super().__init__()
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("openEMS Stackup Editor")
        # wide enough that the toolbar (with the filename label at its max width)
        # never needs to grow the window to fit - Qt otherwise auto-grows a
        # top-level widget up to its layout's minimum size on relayout
        self.resize(1150, 700)
        self.MainWindow = MainWindow

        self.tree = None
        self.current_filename = None

        # bounded multi-level undo: _last_snapshot is always an independent deep
        # copy of the tree as it was right before the most recent change;
        # _undo_stack holds up to UNDO_LEVELS such snapshots, oldest first, each
        # one what Undo restores to. See _record_undo_point()/undo(). No redo -
        # only stepping further back is supported.
        self._last_snapshot = None
        self._undo_stack = []

        # tracks whether the file was valid as of the last revalidation, and which
        # (element, attr) field - if any - is currently blamed for making it invalid
        # (only ever set to the field whose own edit flipped valid->invalid; cleared
        # again as soon as the file is valid, however that happened). See
        # _revalidate_and_refresh()/_is_invalid_field(), reset in _reset_undo_baseline()
        # for the same "new starting point, not an edit" reason undo state resets there.
        self._was_valid = True
        self._invalid_field = None

        # asked once per loaded/new file (reset in new_file()/_load_file()): whether to
        # write auto-assigned implicit-Dielectric-stacking References into the XML at
        # Save time (see _maybe_offer_explicit_dielectric_references())
        self._asked_about_implicit_dielectric_references = False

        # schemaVersion as of the last successful load/save (reset in new_file()/
        # _load_file(), refreshed in _save_to() on success) - lets save() notice when a
        # plain Save would silently upgrade an old-format ("2.0") file on disk to the
        # newer format (e.g. after Convert to Reference position format bumps it to
        # "3.0"), so it can offer Save As instead of overwriting quietly
        self._loaded_schema_version = None

        outer_layout = QVBoxLayout()

        # ---------- menu bar ----------
        # QMenuBar works as a normal widget here even though this is a QDialog, not a
        # QMainWindow - QLayout.setMenuBar() below reserves it a dedicated full-width row
        # at the very top, same visual result as QMainWindow's built-in menu bar.
        self.menu_bar = QMenuBar()

        # kept as self.*_menu (not just locals) so the Python-side wrapper stays alive
        # for the lifetime of the window, matching the QMenuBar's C++ ownership of them
        self.file_menu = self.menu_bar.addMenu("&File")

        self.new_action = QAction("&New", self)
        self.new_action.triggered.connect(self.new_file)
        self.file_menu.addAction(self.new_action)

        self.open_action = QAction("&Open...", self)
        self.open_action.setShortcut(QKeySequence.Open)
        self.open_action.triggered.connect(self.open_file_dialog)
        self.file_menu.addAction(self.open_action)

        self.recent_menu = self.file_menu.addMenu("Open &Recent")
        self._populate_recent_menu()

        self.file_menu.addSeparator()

        self.import_menu = self.file_menu.addMenu("&Import")

        self.import_subst_action = QAction("ADS Momentum (*.subst + materials.matdb)...", self)
        self.import_subst_action.triggered.connect(self._import_momentum_subst)
        self.import_menu.addAction(self.import_subst_action)

        self.import_ltd_action = QAction("ADS Momentum (*.ltd)...", self)
        self.import_ltd_action.triggered.connect(self._import_momentum_ltd)
        self.import_menu.addAction(self.import_ltd_action)

        self.file_menu.addSeparator()

        self.save_action = QAction("&Save", self)
        self.save_action.setShortcut(QKeySequence.Save)
        self.save_action.triggered.connect(lambda: self.save())
        self.file_menu.addAction(self.save_action)

        self.saveas_action = QAction("Save &As...", self)
        self.saveas_action.setShortcut(QKeySequence.SaveAs)
        self.saveas_action.triggered.connect(self.save_as_dialog)
        self.file_menu.addAction(self.saveas_action)

        self.edit_menu = self.menu_bar.addMenu("&Edit")

        self.undo_action = QAction("&Undo", self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.setEnabled(False)
        self.undo_action.triggered.connect(self.undo)
        self.edit_menu.addAction(self.undo_action)

        self.tools_menu = self.menu_bar.addMenu("&Tools")

        self.convert_to_reference_action = QAction("Convert to Reference position format", self)
        self.convert_to_reference_action.triggered.connect(self._on_convert_to_reference_clicked)
        self.tools_menu.addAction(self.convert_to_reference_action)

        self.convert_to_legacy_action = QAction("Convert to legacy format", self)
        self.convert_to_legacy_action.triggered.connect(self._on_convert_to_legacy_clicked)
        self.tools_menu.addAction(self.convert_to_legacy_action)

        self.view_menu = self.menu_bar.addMenu("&View")

        self.preview_action = QAction("Show &Preview", self)
        self.preview_action.triggered.connect(self._open_preview_window)
        self.view_menu.addAction(self.preview_action)

        outer_layout.setMenuBar(self.menu_bar)

        # ---------- filename row ----------
        file_row = QHBoxLayout()
        self.filename_label = QLabel("(no file loaded)")
        # cap the width so a long path can't force the window to grow; the full
        # path is still available as a tooltip and via _set_filename_label()'s eliding
        self.filename_label.setMaximumWidth(400)
        file_row.addWidget(self.filename_label)
        file_row.addStretch()
        outer_layout.addLayout(file_row)

        # ---------- variables / materials / dielectrics / layers tabs ----------
        self.variables_editor = ElementTableEditor(
            VARIABLE_COLUMNS,
            container_fn=self._variables_container,
            add_fn=lambda root, **attrs: stackup_writer.add_variable(root, **attrs),
            remove_fn=self._remove_variable_and_resolve_uses,
            default_attrs_fn=self._default_variable_attrs,
            on_changed=self._on_variables_changed,
            type_choices=VARIABLE_TYPE_CHOICES,
            compute_fn=_compute_variable_values,
            # ResolvedValue depends on both - must live-refresh
            reload_on_attr_change={"Value", "Type"},
            variable_names_fn=self._variable_names,
            invalid_fn=self._is_invalid_field,
        )

        variables_tab = QWidget()
        variables_layout = QVBoxLayout()
        variables_hint = QLabel(
            "To use variables on the other tabs, start typing \"=\" ")
        variables_hint.setWordWrap(True)
        variables_layout.addWidget(variables_hint)
        variables_layout.addWidget(self.variables_editor)
        variables_tab.setLayout(variables_layout)

        self.materials_editor = ElementTableEditor(
            MATERIAL_COLUMNS,
            container_fn=self._materials_container,
            add_fn=lambda root, **attrs: stackup_writer.add_material(root, **attrs),
            remove_fn=stackup_writer.remove_material,
            default_attrs_fn=self._default_material_attrs,
            on_changed=self._on_materials_changed,
            type_choices=list(stackup_writer.VALID_MATERIAL_TYPES),
            strip_fn=_strip_not_applicable_material_attrs,
            not_applicable_fn=_material_not_applicable,
            blank_if_default_fn=_material_blank_if_default,
            reload_on_attr_change={"Type"},
            header_tooltips={
                attr: "Numeric value, or \"=expression\" referencing a Variable"
                for attr in ("Permittivity", "DielectricLossTangent", "Conductivity", "Rs",
                             "Density", "ThermalConductivity")
            },
            table_choices_fn=self._table_names,
            variable_names_fn=self._variable_names,
            invalid_fn=self._is_invalid_field,
        )

        self.dielectrics_editor = ElementTableEditor(
            DIELECTRIC_COLUMNS,
            container_fn=self._dielectrics_container,
            add_fn=lambda root, **attrs: stackup_writer.add_dielectric(root, **attrs),
            remove_fn=stackup_writer.remove_dielectric,
            move_fn=stackup_writer.move_dielectric,
            default_attrs_fn=self._default_dielectric_attrs,
            on_changed=self._on_dielectrics_changed,
            material_choices_fn=self._dielectric_material_choices,
            reference_choices_fn=self._dielectric_names,
            gray_fn=_dielectric_gray_fn,
            compute_fn=self._compute_dielectric_zpositions_bound,
            # these four drive the resulting-Zmin/Zmax computation and the
            # position-mode gray-out state, so they must live-refresh
            reload_on_attr_change={"Thickness", "Zmin", "Zmax", "Reference", "ReferenceEdge"},
            pre_set_attr_fn=self._handle_dielectric_thickness_change,
            header_tooltips={
                "Zmin": "Absolute position, or offset from Reference if set - or \"=expression\" referencing a Variable",
                "Zmax": "Absolute position, or offset from Reference if set - or \"=expression\" referencing a Variable",
                "Thickness": "Numeric value, or \"=expression\" referencing a Variable",
            },
            variable_names_fn=self._variable_names,
            invalid_fn=self._is_invalid_field,
        )

        self.layers_editor = ElementTableEditor(
            LAYER_COLUMNS,
            container_fn=self._layers_container,
            add_fn=lambda root, **attrs: stackup_writer.add_layer(root, **attrs),
            remove_fn=stackup_writer.remove_layer,
            default_attrs_fn=self._default_layer_attrs,
            on_changed=self._on_changed,
            material_choices_fn=self._layer_material_choices,
            reference_choices_fn=self._reference_target_names,
            type_choices=list(stackup_writer.VALID_LAYER_TYPES),
            compute_fn=self._compute_layer_zpositions_and_thickness,
            # Thickness/ResultZmin/ResultZmax are derived from these - must live-refresh
            reload_on_attr_change={"Zmin", "Zmax", "Reference", "ReferenceEdge"},
            header_tooltips={
                "Zmin": "Absolute position, or offset from Reference if set - or \"=expression\" referencing a Variable",
                "Zmax": "Absolute position, or offset from Reference if set - or \"=expression\" referencing a Variable",
            },
            variable_names_fn=self._variable_names,
            invalid_fn=self._is_invalid_field,
            reorder_fn=stackup_writer.reorder_layers,
            descending_attrs={"ResultZmin", "ResultZmax"},
        )

        layers_tab = QWidget()
        layers_layout = QVBoxLayout()
        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel("Substrate Z-offset applied to all layers (0 = none):"))
        self.offset_edit = QLineEdit()
        self.offset_edit.setFixedWidth(100)
        self.offset_edit.editingFinished.connect(self._on_offset_edited)
        offset_row.addWidget(self.offset_edit)
        offset_row.addStretch()
        layers_layout.addLayout(offset_row)
        layers_layout.addWidget(self.layers_editor)
        layers_tab.setLayout(layers_layout)
        # saved as an attribute (unlike the other plain tab containers) because
        # _on_preview_element_selected() needs to switch to it by widget identity -
        # self.layers_editor itself is not the tab's widget, layers_tab is
        self.layers_tab = layers_tab

        self.derived_layers_editor = ElementTableEditor(
            DERIVED_LAYER_COLUMNS,
            container_fn=self._derived_layers_container,
            add_fn=lambda root, **attrs: stackup_writer.add_derived_layer(root, **attrs),
            remove_fn=stackup_writer.remove_derived_layer,
            default_attrs_fn=self._default_derived_layer_attrs,
            on_changed=self._on_changed,
            type_choices=list(stackup_writer.VALID_DERIVED_OPERATIONS),
            operand_lookup_fn=self._layer_name_by_number,
            variable_names_fn=self._variable_names,
            invalid_fn=self._is_invalid_field,
        )

        derived_layers_tab = QWidget()
        derived_layers_layout = QVBoxLayout()
        operands_hint = QLabel(
            "Operands: comma-separated layer numbers (native GDSII or another "
            "Derived Layer's target). Order matters for NOT (first minus the rest).")
        operands_hint.setWordWrap(True)
        derived_layers_layout.addWidget(operands_hint)
        derived_layers_layout.addWidget(self.derived_layers_editor)
        derived_layers_tab.setLayout(derived_layers_layout)

        self.tables_editor = ElementTableEditor(
            TABLE_COLUMNS,
            container_fn=self._tables_container,
            add_fn=lambda root, **attrs: stackup_writer.add_table(root, **attrs),
            remove_fn=stackup_writer.remove_table,
            default_attrs_fn=self._default_table_attrs,
            on_changed=self._on_tables_changed,
            compute_fn=_compute_table_point_counts,
            variable_names_fn=self._variable_names,
            invalid_fn=self._is_invalid_field,
        )
        self.tables_editor.table.itemSelectionChanged.connect(
            lambda: QTimer.singleShot(0, self._guarded(self._sync_points_editor_from_table_selection)))
        # left-align (default QHeaderView alignment is centered) - these headers read as
        # labels ("Table name", "Number of data points"), not numbers, so left reads better
        self.tables_editor.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.points_editor = ElementTableEditor(
            POINT_COLUMNS,
            container_fn=lambda table_el: list(table_el.findall("Point")) if table_el is not None else [],
            add_fn=stackup_writer.add_point,
            remove_fn=stackup_writer.remove_point,
            default_attrs_fn=self._default_point_attrs,
            on_changed=self._on_points_changed,
            header_tooltips={
                attr: "Numeric value, or \"=expression\" referencing a Variable"
                for attr in ("Temperature", "Value")
            },
            variable_names_fn=self._variable_names,
            invalid_fn=self._is_invalid_field,
        )
        self.points_editor.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        tables_tab = QWidget()
        tables_layout = QVBoxLayout()
        tables_hint = QLabel(
            "Named temperature/thermal-conductivity lookup tables, referenced from a "
            "Material's \"Thermal Table\" column. Select a table below to view/edit its "
            "points. Points are sorted by Temperature automatically when the file is saved.")
        tables_hint.setWordWrap(True)
        tables_layout.addWidget(tables_hint)
        tables_layout.addWidget(QLabel("Tables:"))
        self.tables_editor.setMaximumHeight(160)   # short list; points can be 15-20+ per table
        tables_layout.addWidget(self.tables_editor)
        tables_layout.addWidget(QLabel("Points in selected table:"))
        tables_layout.addWidget(self.points_editor)
        tables_tab.setLayout(tables_layout)

        description_tab = QWidget()
        description_layout = QVBoxLayout()
        description_hint = QLabel(
            "Free-text description of this file. Saved as a comment at the top of "
            "the XML output, below the editor's own stamp.")
        description_hint.setWordWrap(True)
        description_layout.addWidget(description_hint)
        self.description_edit = _CommitOnFocusOutTextEdit()
        self.description_edit.editingFinished.connect(self._on_description_edited)
        description_layout.addWidget(self.description_edit)
        description_tab.setLayout(description_layout)

        xml_preview_tab = QWidget()
        xml_preview_layout = QVBoxLayout()
        self.xml_preview_edit = QPlainTextEdit()
        self.xml_preview_edit.setReadOnly(True)
        self.xml_preview_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.xml_preview_edit.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self._xml_preview_highlighter = _XmlSyntaxHighlighter(self.xml_preview_edit.document())
        xml_preview_layout.addWidget(self.xml_preview_edit)
        xml_preview_tab.setLayout(xml_preview_layout)
        self.xml_preview_tab = xml_preview_tab

        self.tabs = QTabWidget()
        self.tabs.addTab(variables_tab, "Variables")
        self.tabs.addTab(self.materials_editor, "Materials")
        self.tabs.addTab(self.dielectrics_editor, "Dielectric Stack")
        self.tabs.addTab(layers_tab, "Layers")
        self.tabs.addTab(derived_layers_tab, "Derived Layers")
        self.tabs.addTab(tables_tab, "Thermal Tables")
        self.tabs.addTab(description_tab, "File Description")
        self.tabs.addTab(xml_preview_tab, "XML Preview")
        self.tabs.setCurrentWidget(self.materials_editor)   # Variables is first in tab order,
                                                             # but Materials is what opens by default
        self.tabs.currentChanged.connect(self._on_tab_changed)

        outer_layout.addWidget(self.tabs)

        # ---------- status ----------
        self.status_label = QLabel("")
        outer_layout.addWidget(self.status_label)

        self.setLayout(outer_layout)

        # the VectorWidget itself lives in the (separate, hide-on-close) preview
        # window; keep the instance here since it's what _refresh_preview() mutates
        self.vector_widget = VectorWidget(
            stackup_reader.stackup_materials_list(),
            stackup_reader.dielectric_layers_list(),
            stackup_reader.metal_layers_list(),
            dielectric_color_fn=self.MainWindow.stackup_dielectric_color,
            dielectric_label_fn=self.MainWindow.stackup_dielectric_label,
            metal_label_fn=self.MainWindow.stackup_metal_label,
            via_label_suffix_fn=self.MainWindow.stackup_via_label_suffix,
        )
        self.vector_widget.setMinimumSize(600, 800)
        self.chiplet_switcher = ChipletSwitcher(self.vector_widget.set_active_chiplet)
        self.vector_widget.set_chiplet_switcher(self.chiplet_switcher)

        # two-way sync between the preview graphics and the Dielectric Stack/Layers
        # tables: clicking a shape in the preview selects its row (and switches to
        # its tab); selecting a row highlights the matching shape in the preview.
        # Deferred via QTimer.singleShot(0, ...), same pattern already used for the
        # Tables<->Points sync above (_sync_points_editor_from_table_selection) -
        # avoids reentering Qt's selection/item machinery synchronously from
        # within a signal it's still emitting. Wrapped in self._guarded(...): this
        # window can be closed in the interval between scheduling one of these and
        # the timer actually firing, which would otherwise hit a RuntimeError from
        # touching an already-deleted Qt widget.
        self.vector_widget.elementSelected.connect(
            lambda kind, name: QTimer.singleShot(
                0, self._guarded(lambda: self._on_preview_element_selected(kind, name))))
        self.dielectrics_editor.table.itemSelectionChanged.connect(
            lambda: QTimer.singleShot(0, self._guarded(self._on_dielectrics_row_selected)))
        self.layers_editor.table.itemSelectionChanged.connect(
            lambda: QTimer.singleShot(0, self._guarded(self._on_layers_row_selected)))

        # created once and kept for the editor's lifetime, but deliberately with
        # no Qt parent (see StackupPreviewWindow docstring) - cleaned up explicitly
        # in closeEvent() below rather than via Qt's parent-child auto-delete
        self.preview_window = StackupPreviewWindow(self.vector_widget, chiplet_switcher=self.chiplet_switcher)
        self.preview_window.move(self.x() + self.width() + 20, self.y())

        if initial_filename and os.path.isfile(initial_filename):
            self._load_file(initial_filename)
        else:
            self.new_file()

        self._open_preview_window()

    def _guarded(self, fn):
        """Wraps fn (called with no arguments) so it's a no-op if this window (or
           its vector_widget) has already been destroyed - guards every
           QTimer.singleShot(0, ...) deferred call in this file, since this window
           can be closed in the interval between scheduling one and the timer
           actually firing, which would otherwise raise "Internal C++ object
           already deleted" from touching self.tabs/self.tree/etc. on a dead widget.

           Checks vector_widget separately from self: it lives in preview_window,
           which has no Qt parent relationship to this window (see
           StackupPreviewWindow's docstring) and is torn down via its own
           deleteLater() call in closeEvent() below - a separate deferred-deletion
           chain that isn't guaranteed to finish strictly after (or before) this
           window's own WA_DeleteOnClose teardown, so self being still-valid at the
           moment this runs does not guarantee vector_widget still is too.
        """
        def wrapper():
            if shiboken6.isValid(self) and shiboken6.isValid(self.vector_widget):
                fn()
        return wrapper

    def _open_preview_window(self):
        self.preview_window.show()
        self.preview_window.raise_()
        self.preview_window.activateWindow()

    def closeEvent(self, event):
        # preview_window has no Qt parent (see its docstring), so it won't be
        # cascade-deleted when this dialog is destroyed - clean it up explicitly.
        # deleteLater() bypasses StackupPreviewWindow's own closeEvent override
        # (which just hides it), since that override only intercepts close(), not
        # deleteLater()
        self.preview_window.hide()
        self.preview_window.deleteLater()
        super().closeEvent(event)

    # ---------- default attrs for new rows ----------

    def _default_variable_attrs(self):
        names = self._variable_names()
        return {
            "Name": _unique_name(names, "NewVariable"),
            "Value": "0",
        }

    def _default_material_attrs(self):
        names = self._material_names()
        return {
            "Name": _unique_name(names, "NewMaterial"),
            "Type": "Conductor",
            # Permittivity/DielectricLossTangent deliberately omitted: not
            # applicable to Conductor, stripped right back out on reload anyway
            "Conductivity": "0",
            "Color": "808080",
        }

    def _default_dielectric_attrs(self):
        names = [d.get("Name") for d in self._dielectrics_container(self.tree.getroot())]
        materials = self._material_names()
        return {
            "Name": _unique_name(names, "NewDielectric"),
            "Material": materials[0] if materials else "",
            "Thickness": "1.0",
        }

    def _handle_dielectric_thickness_change(self, element, attr, new_value):
        """pre_set_attr_fn for the Dielectrics editor: when a non-absolute (implicit-stacked
           or Reference-based) dielectric's Thickness actually changes, its resulting
           Zmax moves by the same delta - offer to apply that same delta to
           every drawn Layer whose z-position is affected: layers entirely
           above the (old) Zmax are shifted (Zmin and Zmax both += delta);
           layers that straddle it (Zmin at/below, Zmax above - e.g. a via, or
           a backside connection like "LBE") are stretched instead, so their
           anchored bottom end stays put while their top end tracks the shift.
           Layers entirely below or inside this dielectric are left alone.
           Returns True once it has applied the Thickness value itself
           (handled unconditionally, whether or not there were layers to
           adjust / the user accepted).
        """
        if attr != "Thickness" or self.tree is None or _dielectric_position_mode(element) == "absolute":
            return False

        old_text = element.get("Thickness")
        try:
            old_thickness = float(old_text) if old_text else None
            new_thickness = float(new_value) if new_value else None
        except ValueError:
            return False  # not valid numbers (yet) - let normal handling/validation deal with it
        if old_thickness is None or new_thickness is None or old_thickness == new_thickness:
            # nothing to shift for (cleared, unparseable, or a no-op edit) - still
            # need to apply the raw value ourselves, since we're telling the caller
            # this hook fully handled it
            if new_value:
                element.set("Thickness", new_value)
            elif "Thickness" in element.attrib:
                del element.attrib["Thickness"]
            return True

        root = self.tree.getroot()
        try:
            variables = _build_variables_list(self._variables_container(root))
            old_positions = _compute_dielectric_zpositions(self._dielectrics_container(root), variables)
        except (Exception, SystemExit):
            old_positions = {}  # couldn't resolve current data - handled below (skip the offer)
        old_zmax_text = old_positions.get(id(element), {}).get("ResultZmax")

        element.set("Thickness", new_value)  # apply the actual edit either way

        if not old_zmax_text:
            return True  # couldn't determine the old boundary (invalid data elsewhere) - skip the offer
        old_zmax = float(old_zmax_text)
        delta = new_thickness - old_thickness

        # <Layer> Zmin/Zmax are in a local frame and only land in the same
        # coordinate space as the dielectric stack once the optional <Substrate
        # Offset> is applied (see util_stackup_reader.metal_layers_list.add_offset)
        # - comparing raw, un-offset values against a dielectric's Zmax would
        # misjudge which layers are actually above it whenever Offset != 0, which
        # is the common case (the whole metal stack floating above Substrate).
        offset_el = stackup_writer.get_substrate_offset_element(root)
        try:
            offset = float(offset_el.get("Offset")) if offset_el is not None else 0.0
        except (TypeError, ValueError):
            offset = 0.0

        # Three cases, classified purely by z-geometry (not Layer Type - e.g. "LBE"
        # is Type="dielectric" in some stackup files and Type="via" in others, but
        # has the same straddling geometry either way and needs the same handling):
        #   - entirely at/above the old top boundary -> shift (Zmin and Zmax both += delta)
        #   - straddles it (Zmin below/inside, Zmax above, e.g. a via or LBE-like
        #     backside connection reaching up through this dielectric into the
        #     next one) -> stretch: its far (Zmax) end tracks the shift, its near
        #     (Zmin) end stays anchored to what's below, which hasn't moved
        #   - entirely below/inside -> untouched
        epsilon = 1e-5
        layers_above = []
        layers_straddling = []
        for layer_el in self._layers_container(root):
            if layer_el.get("Reference"):
                # Reference-based layers' Zmin/Zmax are offsets from their reference
                # edge, not positions - adding Offset to them is meaningless, and they
                # already auto-track this dielectric's new Thickness via
                # resolve_references() once it's re-run, so this shift/stretch
                # heuristic must not touch them (that would double-count the movement)
                continue
            try:
                layer_zmin = float(layer_el.get("Zmin")) + offset
                layer_zmax = float(layer_el.get("Zmax")) + offset
            except (TypeError, ValueError):
                continue
            if layer_zmin >= old_zmax - epsilon:
                layers_above.append(layer_el)
            elif layer_zmax > old_zmax + epsilon:
                layers_straddling.append(layer_el)

        if not layers_above and not layers_straddling:
            return True

        length_unit = (root.find("ELayers").get("LengthUnit") or "").strip()
        message_parts = [f"This dielectric's Thickness changed by {delta:+.4f}{length_unit}.\n"]
        if layers_above:
            names = ", ".join(layer_el.get("Name") or "<unnamed>" for layer_el in layers_above)
            message_parts.append(
                f"\n{len(layers_above)} layer(s) positioned above it will be SHIFTED "
                f"by the same amount:\n{names}\n")
        if layers_straddling:
            names = ", ".join(layer_el.get("Name") or "<unnamed>" for layer_el in layers_straddling)
            message_parts.append(
                f"\n{len(layers_straddling)} layer(s) reach from below/inside it to "
                f"above it (e.g. a via) and will be STRETCHED by the same amount, "
                f"keeping their bottom (Zmin) anchored:\n{names}\n")
        message_parts.append("\nApply these changes, so they stay in the same position "
                              "relative to this dielectric?")

        reply = QMessageBox.question(
            self, "Shift/stretch layers above?", "".join(message_parts),
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            for layer_el in layers_above:
                layer_el.set("Zmin", f"{float(layer_el.get('Zmin')) + delta:.4f}")
                layer_el.set("Zmax", f"{float(layer_el.get('Zmax')) + delta:.4f}")
            for layer_el in layers_straddling:
                layer_el.set("Zmax", f"{float(layer_el.get('Zmax')) + delta:.4f}")
            self.layers_editor.reload()

        return True

    def _default_layer_attrs(self):
        names = [l.get("Name") for l in self._layers_container(self.tree.getroot())]
        materials = self._material_names()
        return {
            "Name": _unique_name(names, "NewLayer"),
            "Type": "conductor",
            "Material": materials[0] if materials else "",
            "Zmin": "0",
            "Zmax": "1",
            "Layer": "900",
        }

    def _default_derived_layer_attrs(self):
        names = [dl.get("Name") for dl in self._derived_layers_container(self.tree.getroot())]
        return {
            "Name": _unique_name(names, "NewDerivedLayer"),
            "Layer": self._next_free_target_layer(),
            "Operation": "AND",
            # Operands deliberately left for the user to fill in - there's no
            # sensible default set of layers to combine, unlike e.g. a new
            # Material where "just pick the first material" is a harmless stand-in
        }

    def _default_table_attrs(self):
        return {
            "Name": _unique_name(self._table_names(), "NewTable"),
            # Points deliberately left for the user to add - same reasoning as
            # DerivedLayer's Operands above: no sensible default curve to start from
        }

    def _default_point_attrs(self):
        # avoid colliding with the currently-shown table's existing Temperatures - a
        # fixed default (e.g. always "0") would immediately trip the duplicate-Temperature
        # validation error the moment "Add" is clicked twice in a row
        existing = []
        for el in self.points_editor.row_elements:
            try:
                existing.append(float(el.get("Temperature")))
            except (TypeError, ValueError):
                pass
        next_temperature = max(existing) + 10 if existing else 25
        return {"Temperature": f"{next_temperature:g}", "Value": "0"}

    def _next_free_target_layer(self):
        # simple collision-avoidance so a freshly added row already has a usable
        # target number: highest layer/derived-layer number in use, plus one
        root = self.tree.getroot()
        used = set()
        for el in self._layers_container(root):
            try:
                used.add(int(el.get("Layer")))
            except (TypeError, ValueError):
                pass
        for el in self._derived_layers_container(root):
            try:
                used.add(int(el.get("Layer")))
            except (TypeError, ValueError):
                pass
        candidate = 900
        while candidate in used:
            candidate += 1
        return str(candidate)

    def _variable_names(self):
        if self.tree is None:
            return []
        return [v.get("Name") for v in self._variables_container(self.tree.getroot()) if v.get("Name")]

    def _remove_variable_and_resolve_uses(self, root, element):
        """remove_fn for variables_editor: before actually deleting the <Variable>, resolves
           every remaining use of it (anywhere in the tree, including other Variables' own
           Value) to its current literal value via _resolve_variable_uses() - so deleting a
           variable never leaves a dangling "="-expression reference to an undefined name
           behind. Falls back to a plain removal (no substitution) if the current data can't
           be resolved right now (e.g. already mid-edit invalid) - same "don't block on this"
           reasoning used elsewhere for compute_fn/pre_set_attr_fn hooks.
        """
        name = element.get("Name")
        if name:
            try:
                variables = _build_variables_list(self._variables_container(root))
                var = variables.get_by_name(name)
                if var is not None:
                    _resolve_variable_uses(root, name, var.value, skip_element=element)
            except (Exception, SystemExit):
                pass
        stackup_writer.remove_variable(root, element)

    def _material_names(self):
        if self.tree is None:
            return []
        return [m.get("Name") for m in self._materials_container(self.tree.getroot()) if m.get("Name")]

    def _dielectric_material_choices(self):
        # AIR is always usable without a <Materials> entry (stackup_reader.parse_substrate()
        # injects a default) - offer it in the dropdown even when the file doesn't define one
        names = self._material_names()
        if not any(n.upper() == "AIR" for n in names):
            names = names + ["AIR"]
        return names

    def _layer_material_choices(self):
        # PEC and AIR are both usable on a Layer without a <Materials> entry - offer them in
        # the dropdown even when the file doesn't define one (see stackup_reader.PEC_MATERIAL_NAME
        # and the built-in default AIR material in stackup_reader.parse_substrate())
        names = self._material_names()
        extras = []
        if not any(n.upper() == stackup_reader.PEC_MATERIAL_NAME.upper() for n in names):
            extras.append(stackup_reader.PEC_MATERIAL_NAME)
        if not any(n.upper() == "AIR" for n in names):
            extras.append("AIR")
        return names + extras

    def _layer_names(self):
        if self.tree is None:
            return []
        return [l.get("Name") for l in self._layers_container(self.tree.getroot()) if l.get("Name")]

    def _dielectric_names(self):
        if self.tree is None:
            return []
        return [d.get("Name") for d in self._dielectrics_container(self.tree.getroot()) if d.get("Name")]

    def _table_names(self):
        if self.tree is None:
            return []
        return [t.get("Name") for t in self._tables_container(self.tree.getroot()) if t.get("Name")]

    def _layer_name_by_number(self):
        # for the Derived Layers tab's Operands tooltip: a GDSII layer number used as an
        # operand doesn't always have a Layers-tab entry (a pure intermediate derived
        # layer legitimately doesn't need one - see XML_stackup_format.md), so this is a
        # best-effort lookup, not a complete mapping
        if self.tree is None:
            return {}
        return {l.get("Layer"): l.get("Name") for l in self._layers_container(self.tree.getroot())
                if l.get("Layer") and l.get("Name")}

    def _reference_target_names(self):
        # a Layer's Reference choices span two different element containers (unlike
        # material_choices_fn, which only ever spans Materials); a Dielectric's Reference
        # is Dielectric-only, so it just uses _dielectric_names() directly (see its wiring
        # in dielectrics_editor's construction)
        return self._layer_names() + self._dielectric_names()

    def _compute_dielectric_zpositions_bound(self, elements):
        # _compute_dielectric_zpositions() needs the current Variables tab state to resolve
        # any "="-expression, but ElementTableEditor's compute_fn contract only ever calls
        # compute_fn(elements) - this bound wrapper fetches that extra context from self,
        # same reason _compute_layer_zpositions_and_thickness below wraps its own module
        # function instead of wiring it in directly.
        root = self.tree.getroot() if self.tree is not None else None
        variable_elements = self._variables_container(root) if root is not None else []
        try:
            variables = _build_variables_list(variable_elements)
        except (Exception, SystemExit):
            return {}
        return _compute_dielectric_zpositions(elements, variables)

    def _compute_layer_zpositions_and_thickness(self, elements):
        root = self.tree.getroot() if self.tree is not None else None
        dielectrics_elements = self._dielectrics_container(root) if root is not None else []
        variable_elements = self._variables_container(root) if root is not None else []
        offset_el = stackup_writer.get_substrate_offset_element(root) if root is not None else None
        try:
            offset = float(offset_el.get("Offset")) if offset_el is not None else 0.0
        except (TypeError, ValueError):
            offset = 0.0
        computed = _compute_layer_thickness(elements)
        try:
            variables = _build_variables_list(variable_elements)
        except (Exception, SystemExit):
            return computed
        for key, values in _compute_layer_zpositions(elements, dielectrics_elements, variables, offset).items():
            computed.setdefault(key, {}).update(values)
        return computed

    # ---------- container accessors (Element -> list[Element]) ----------

    @staticmethod
    def _variables_container(root):
        variables_el = stackup_writer.get_variables_element(root)
        return variables_el.findall("Variable") if variables_el is not None else []

    @staticmethod
    def _materials_container(root):
        materials_el = stackup_writer.get_materials_element(root)
        return materials_el.findall("Material") if materials_el is not None else []

    @staticmethod
    def _dielectrics_container(root):
        dielectrics_el = stackup_writer.get_dielectrics_element(root)
        return dielectrics_el.findall("Dielectric") if dielectrics_el is not None else []

    @staticmethod
    def _layers_container(root):
        layers_el = stackup_writer.get_layers_element(root)
        return layers_el.findall("Layer") if layers_el is not None else []

    @staticmethod
    def _derived_layers_container(root):
        derived_el = stackup_writer.get_derived_layers_element(root)
        return derived_el.findall("DerivedLayer") if derived_el is not None else []

    @staticmethod
    def _tables_container(root):
        tables_el = stackup_writer.get_tables_element(root)
        return tables_el.findall("Table") if tables_el is not None else []

    # ---------- file actions ----------

    # ---------- recent files ----------

    @staticmethod
    def _recent_files():
        files = QSettings(RECENT_FILES_ORG, RECENT_FILES_APP).value(RECENT_FILES_KEY, [])
        # QSettings collapses a saved one-item list back to a bare string on read -
        # a well-known quirk of the native (registry/plist) backends
        if isinstance(files, str):
            files = [files] if files else []
        return list(files)

    def _add_recent_file(self, filename):
        filename = os.path.abspath(filename)
        files = [f for f in self._recent_files() if os.path.normcase(f) != os.path.normcase(filename)]
        files.insert(0, filename)
        QSettings(RECENT_FILES_ORG, RECENT_FILES_APP).setValue(RECENT_FILES_KEY, files[:MAX_RECENT_FILES])
        self._populate_recent_menu()

    def _remove_recent_file(self, filename):
        filename = os.path.abspath(filename)
        files = [f for f in self._recent_files() if os.path.normcase(f) != os.path.normcase(filename)]
        QSettings(RECENT_FILES_ORG, RECENT_FILES_APP).setValue(RECENT_FILES_KEY, files)
        self._populate_recent_menu()

    def _clear_recent_files(self):
        QSettings(RECENT_FILES_ORG, RECENT_FILES_APP).setValue(RECENT_FILES_KEY, [])
        self._populate_recent_menu()

    def _populate_recent_menu(self):
        self.recent_menu.clear()
        files = self._recent_files()
        if not files:
            empty_action = QAction("(none)", self)
            empty_action.setEnabled(False)
            self.recent_menu.addAction(empty_action)
            return
        for filename in files:
            action = QAction(filename, self)
            action.triggered.connect(lambda checked=False, f=filename: self._open_recent_file(f))
            self.recent_menu.addAction(action)
        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent Files", self)
        clear_action.triggered.connect(self._clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def _open_recent_file(self, filename):
        if not os.path.isfile(filename):
            QMessageBox.warning(
                self, "File not found",
                f"Could not find {filename}.\n\nIt will be removed from the recent files list.")
            self._remove_recent_file(filename)
            return
        self._load_file(filename)

    def _set_filename_label(self, text):
        # full text always available on hover; visible label is elided (never
        # wrapped) so a long path can't force the window/toolbar to grow
        self.filename_label.setToolTip(text)
        metrics = QFontMetrics(self.filename_label.font())
        elided = metrics.elidedText(text, Qt.ElideMiddle, self.filename_label.maximumWidth())
        self.filename_label.setText(elided)

    def new_file(self):
        self.tree = stackup_writer.new_stackup_tree()
        self.current_filename = None
        self._set_filename_label("(new, unsaved)")
        self._asked_about_implicit_dielectric_references = False
        self._loaded_schema_version = self.tree.getroot().get("schemaVersion")
        self._reload_all_editors()
        self._reset_undo_baseline()
        self._revalidate_and_refresh()
        self._refresh_xml_preview_if_active()

    def open_file_dialog(self):
        previous_dir = os.path.dirname(self.current_filename) if self.current_filename else ""
        filename, _ = QFileDialog.getOpenFileName(self, "Open Stackup XML File", previous_dir, "*.xml;;*.*")
        if filename:
            self._load_file(filename)

    def _load_file(self, filename):
        try:
            self.tree = stackup_writer.load_stackup_tree(filename)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load {filename}:\n{e}")
            return
        self.current_filename = filename
        self._set_filename_label(filename)
        self._asked_about_implicit_dielectric_references = False
        self._loaded_schema_version = self.tree.getroot().get("schemaVersion")
        self._reload_all_editors()
        self._reset_undo_baseline()
        self._revalidate_and_refresh()
        self._refresh_xml_preview_if_active()
        self._add_recent_file(filename)

    # ---------- import from ADS Momentum ----------

    def _prompt_air_thickness(self):
        """Asks for the thickness of the open-boundary AIR region above the stack -
           both ADS Momentum source formats leave this undefined (Momentum treats it
           as an unbounded half-space), but the target schema needs a finite value to
           bound the simulation domain.
        Returns:
            float or None: the entered thickness, or None if the user cancelled
        """
        value, ok = QInputDialog.getDouble(
            self, "Top Air Thickness",
            "Thickness of the open-boundary AIR region above the stack (um):",
            300.0, 0.0, 1000000.0, decimals=2)
        return value if ok else None

    def _show_import_warnings(self, warnings):
        if not warnings:
            QMessageBox.information(self, "Import complete", "Stackup imported successfully.")
            return
        QMessageBox.information(
            self, "Import warnings",
            "Imported with warnings:\n\n" + "\n".join(f"- {w}" for w in warnings))

    def _apply_import_result(self, result, source_label):
        # current_filename deliberately left None, same as new_file() - an imported
        # stackup is unsaved content the user should explicitly Save As, never
        # something that could silently overwrite an existing file
        self.tree = result.tree
        self.current_filename = None
        self._set_filename_label(f"(imported from {source_label}, unsaved)")
        self._asked_about_implicit_dielectric_references = False
        self._loaded_schema_version = self.tree.getroot().get("schemaVersion")
        self._reload_all_editors()
        self._reset_undo_baseline()
        self._revalidate_and_refresh()
        self._refresh_xml_preview_if_active()
        self._show_import_warnings(result.warnings)

    def _import_momentum_subst(self):
        previous_dir = os.path.dirname(self.current_filename) if self.current_filename else ""
        subst_path, _ = QFileDialog.getOpenFileName(
            self, "Import ADS Momentum Substrate", previous_dir, "*.subst;;*.*")
        if not subst_path:
            return

        # per the *.subst format, a companion materials.matdb is always expected in
        # the same folder - looked up automatically rather than asked for separately
        matdb_path = os.path.join(os.path.dirname(subst_path), "materials.matdb")
        if not os.path.isfile(matdb_path):
            QMessageBox.critical(
                self, "Error",
                f"Could not find materials.matdb next to {os.path.basename(subst_path)}.\n\n"
                "A *.subst file always requires a materials.matdb in the same folder.")
            return

        air_thickness = self._prompt_air_thickness()
        if air_thickness is None:
            return

        try:
            result = momentum_import.import_subst(subst_path, matdb_path, air_thickness)
        except Exception as e:
            QMessageBox.critical(self, "Import failed", f"Could not import {subst_path}:\n{e}")
            return

        self._apply_import_result(result, os.path.basename(subst_path))

    def _import_momentum_ltd(self):
        previous_dir = os.path.dirname(self.current_filename) if self.current_filename else ""
        ltd_path, _ = QFileDialog.getOpenFileName(
            self, "Import ADS Momentum Technology", previous_dir, "*.ltd;;*.*")
        if not ltd_path:
            return

        air_thickness = self._prompt_air_thickness()
        if air_thickness is None:
            return

        try:
            result = momentum_import.import_ltd(ltd_path, air_thickness)
        except Exception as e:
            QMessageBox.critical(self, "Import failed", f"Could not import {ltd_path}:\n{e}")
            return

        self._apply_import_result(result, os.path.basename(ltd_path))

    def _reload_all_editors(self):
        root = self.tree.getroot()
        self.variables_editor.set_root(root)
        self.materials_editor.set_root(root)
        self.dielectrics_editor.set_root(root)
        self.layers_editor.set_root(root)
        self.derived_layers_editor.set_root(root)
        self.tables_editor.set_root(root)
        # new tree = new Elements, so nothing "the same Table" to rebind the detail
        # editor to - always reset it explicitly rather than relying on
        # itemSelectionChanged firing with the right timing during the reload above
        self.points_editor.set_root(None)

        offset_el = stackup_writer.get_substrate_offset_element(root)
        self.offset_edit.setText(offset_el.get("Offset") if offset_el is not None else "0")

        # setPlainText() does not touch focus, so this does not trigger
        # _on_description_edited() (which only fires on focus-out)
        self.description_edit.setPlainText(stackup_writer.get_file_description(root))

    def save(self):
        if self.tree is None:
            return False
        if not self.current_filename:
            return self.save_as_dialog()

        current_schema_version = self.tree.getroot().get("schemaVersion")
        if self._loaded_schema_version == "2.0" and current_schema_version != "2.0":
            # a plain Save would silently overwrite the original 2.0-format file on disk
            # with the newer format (typically right after Convert to Reference position
            # format bumped it) - ask once, rather than surprise the user
            choice = self._ask_overwrite_or_save_as(current_schema_version)
            if choice == "cancel":
                return False
            if choice == "save_as":
                return self.save_as_dialog()
            # choice == "overwrite": fall through to the normal save below

        return self._save_to(self.current_filename)

    def _ask_overwrite_or_save_as(self, current_schema_version):
        """This file's on-disk schemaVersion is "2.0" but the in-memory content is now a
           newer format (current_schema_version) - ask whether to overwrite the original
           file or save the upgraded content to a new file instead.
        Returns:
            string: "overwrite", "save_as", or "cancel"
        """
        box = QMessageBox(self)
        box.setWindowTitle("File format changed")
        box.setText(
            f'This file was loaded as schemaVersion="2.0". Saving now would overwrite it '
            f'with the newer schemaVersion="{current_schema_version}" format.\n\n'
            "Overwrite the original file, or save the upgraded version as a new file?")
        overwrite_btn = box.addButton("Overwrite", QMessageBox.AcceptRole)
        saveas_btn = box.addButton("Save As...", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(saveas_btn)  # non-destructive default
        box.exec()
        clicked = box.clickedButton()
        if clicked is overwrite_btn:
            return "overwrite"
        if clicked is saveas_btn:
            return "save_as"
        return "cancel"

    def save_as_dialog(self):
        if self.tree is None:
            return False
        previous_dir = os.path.dirname(self.current_filename) if self.current_filename else ""
        filename, _ = QFileDialog.getSaveFileName(self, "Save Stackup XML File", previous_dir, "*.xml;;*.*")
        if not filename:
            return False
        return self._save_to(filename)

    def _compute_auto_dielectric_references(self, dielectrics_elements):
        """Returns {dielectric name: (reference, reference_edge)} for dielectrics that would
           get a Reference auto-assigned from implicit (Thickness-only) stacking - see
           util_stackup_reader.dielectric_layers_list._assign_implicit_references(). Empty
           (not an error) if the current data can't be resolved yet.
        """
        root = self.tree.getroot() if self.tree is not None else None
        variable_elements = self._variables_container(root) if root is not None else []
        try:
            variables = _build_variables_list(variable_elements)
            dielectrics_list = stackup_reader.dielectric_layers_list()
            for element in dielectrics_elements:
                dielectrics_list.append(stackup_reader.dielectric_layer(element, variables), None)
            dielectrics_list.calculate_zpositions()
        except (Exception, SystemExit):
            return {}
        return {
            dielectric.name: (dielectric.reference, dielectric.reference_edge)
            for dielectric in dielectrics_list.dielectrics
            if dielectric.reference_is_auto
        }

    def _maybe_offer_explicit_dielectric_references(self, root):
        """Called once per file per editing session, right before Save actually writes the
           file: if any Dielectric would get a Reference auto-assigned from implicit
           Thickness-stacking, ask once whether to write it into the XML now - purely
           cosmetic/documentary, the computed z-positions are identical either way.
        """
        if self._asked_about_implicit_dielectric_references:
            return
        self._asked_about_implicit_dielectric_references = True

        dielectrics_elements = self._dielectrics_container(root)
        auto_refs = self._compute_auto_dielectric_references(dielectrics_elements)
        if not auto_refs:
            return

        names = ", ".join(auto_refs.keys())
        reply = QMessageBox.question(
            self, "Make implicit dielectric stacking explicit?",
            "These dielectrics use implicit (Thickness-based) stacking, which can now be "
            f"recorded explicitly with Reference:\n\n{names}\n\n"
            "Add Reference/ReferenceEdge attributes to these dielectrics now? Their computed "
            "position stays exactly the same either way - this is asked only once per file.",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            for element in dielectrics_elements:
                name = element.get("Name")
                if name in auto_refs:
                    reference, reference_edge = auto_refs[name]
                    element.set("Reference", reference)
                    element.set("ReferenceEdge", reference_edge)
            self.dielectrics_editor.reload()
            self.layers_editor.reload()

    def _save_to(self, filename):
        root = self.tree.getroot()
        errors = stackup_writer.validate_stackup(root)
        if errors:
            QMessageBox.warning(
                self, "Cannot save - validation errors",
                "Fix these problems before saving:\n\n" + "\n".join(f"- {e}" for e in errors))
            return False

        self._maybe_offer_explicit_dielectric_references(root)

        app_name = getattr(self.MainWindow, "APP_NAME", "openEMS Stackup Editor")
        stackup_writer.stamp_header_comments(root, app_name, self.description_edit.toPlainText())

        try:
            stackup_writer.save_stackup_tree(self.tree, filename)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save {filename}:\n{e}")
            return False

        self.current_filename = filename
        self._set_filename_label(filename)
        # reflects what's now actually on disk, so save() only asks about a format
        # upgrade again if the version changes further from here, not on every save
        self._loaded_schema_version = root.get("schemaVersion")
        self._add_recent_file(filename)

        saved_values = getattr(self.MainWindow, "saved_values", {}) or {}
        substrate_file = saved_values.get("SubstrateFile")
        if substrate_file and os.path.normcase(os.path.abspath(substrate_file)) == os.path.normcase(os.path.abspath(filename)):
            reply = QMessageBox.question(
                self, "Reload in main window?",
                "This is the stackup file currently loaded in the main window.\n"
                "Reload it now so the change takes effect there too?",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.MainWindow.read_XML()

        return True

    # ---------- substrate offset ----------

    def _on_offset_edited(self):
        if self.tree is None:
            return
        text = self.offset_edit.text().strip()
        try:
            value = float(text) if text else 0.0
        except ValueError:
            QMessageBox.warning(self, "Error", f"Not a valid offset value: '{text}'")
            offset_el = stackup_writer.get_substrate_offset_element(self.tree.getroot())
            self.offset_edit.setText(offset_el.get("Offset") if offset_el is not None else "0")
            return
        # Deferred: the mutation below can pop a modal dialog and rebuild the Layers
        # table. Doing that synchronously from inside editingFinished (itself part of
        # this QLineEdit's focus-out processing) is the same class of problem the
        # reload_on_attr_change path works around above - let the focus-out event
        # finish unwinding first.
        QTimer.singleShot(0, lambda: self._apply_offset_change(value))

    def _apply_offset_change(self, value):
        if self.tree is None:
            return
        root = self.tree.getroot()
        old_offset_el = stackup_writer.get_substrate_offset_element(root)
        try:
            old_value = float(old_offset_el.get("Offset")) if old_offset_el is not None else 0.0
        except (TypeError, ValueError):
            old_value = 0.0

        if value != 0:
            # UX improvement layered on top of the authoritative check in
            # validate_stackup() (also catches the case where Reference is added to a
            # layer after a nonzero offset already exists) - catch it here too, before
            # Save-time, since this is the point where the user is actually setting it
            referenced_layer_names = [layer_el.get("Name") or "<unnamed>"
                                       for layer_el in self._layers_container(root) if layer_el.get("Reference")]
            if referenced_layer_names:
                QMessageBox.warning(
                    self, "Cannot set Substrate Offset",
                    "Substrate Offset cannot be combined with Reference-based Layer "
                    "positioning (it would be ambiguous whether the offset applies "
                    "before or after Reference resolution). Layers using Reference:\n\n"
                    + "\n".join(referenced_layer_names))
                self.offset_edit.setText(old_offset_el.get("Offset") if old_offset_el is not None else "0")
                return

        delta = value - old_value

        stackup_writer.set_substrate_offset(root, value)

        layer_elements = self._layers_container(root)
        if delta and layer_elements:
            length_unit = (root.find("ELayers").get("LengthUnit") or "").strip()
            reply = QMessageBox.question(
                self, "Substrate Offset changed",
                f"The Substrate Offset changed by {delta:+.4f}{length_unit}.\n\n"
                "All layers are defined relative to this offset, so their effective "
                "position moves along with it unless their Zmin/Zmax are compensated.\n\n"
                "Yes - SHIFT: leave every layer's Zmin/Zmax unchanged, so the whole "
                "layer stack moves together with the new offset.\n"
                "No - KEEP POSITION: adjust every layer's Zmin/Zmax by "
                f"{-delta:+.4f}{length_unit}, so layers stay at the same effective "
                "position as before.",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                for layer_el in layer_elements:
                    try:
                        zmin = float(layer_el.get("Zmin"))
                        zmax = float(layer_el.get("Zmax"))
                    except (TypeError, ValueError):
                        continue
                    layer_el.set("Zmin", f"{zmin - delta:.4f}")
                    layer_el.set("Zmax", f"{zmax - delta:.4f}")
                self.layers_editor.reload()

        self._on_changed(structural=True)

    # ---------- convert to Reference position format ----------

    def _on_convert_to_reference_clicked(self):
        if self.tree is None:
            return
        root = self.tree.getroot()

        offset_el = stackup_writer.get_substrate_offset_element(root)
        try:
            offset = float(offset_el.get("Offset")) if offset_el is not None else 0.0
        except (TypeError, ValueError):
            offset = 0.0

        message = (
            "Convert this stackup to Reference-relative positioning?\n\n"
            "Every Dielectric and Layer not already using Reference will be repositioned "
            "relative to the nearest thing below it (a Dielectric's Bottom edge, or another "
            "Layer's Top edge) instead of an absolute z-position. Resulting absolute "
            "positions stay exactly the same.")
        if offset:
            message += (
                f"\n\nSubstrate Offset is currently {offset:g} - Reference-based Layer "
                "positioning requires it to be 0, so as a first step it will be folded into "
                "every Layer's own Zmin/Zmax and then removed.")

        reply = QMessageBox.question(self, "Convert to Reference position format", message,
                                      QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        try:
            self._convert_to_reference_format()
        except (Exception, SystemExit) as e:
            QMessageBox.warning(self, "Conversion failed",
                                 f"Could not convert - current stackup could not be fully "
                                 f"resolved:\n{e}")
            return

        self._reload_all_editors()
        self._on_changed(structural=True)
        self._refresh_xml_preview_if_active()

    def _convert_to_reference_format(self):
        """Rewrites every Dielectric/Layer that isn't already Reference-based to use
           Reference instead of an absolute z-position, bumps schemaVersion to "3.0", and
           stamps a comment noting the minimum gds2openEMS reader version needed to read the
           result back (see stamp_reference_format_comment()). First folds a nonzero
           <Substrate Offset> into the Layers' own absolute Zmin/Zmax and removes it, since
           Reference-based Layers and a nonzero Offset are mutually exclusive (see
           validate_stackup()).
        """
        root = self.tree.getroot()

        offset_el = stackup_writer.get_substrate_offset_element(root)
        try:
            offset = float(offset_el.get("Offset")) if offset_el is not None else 0.0
        except (TypeError, ValueError):
            offset = 0.0
        if offset:
            for layer_el in self._layers_container(root):
                if layer_el.get("Reference"):
                    continue  # already Reference-based, never was in the +Offset frame
                try:
                    zmin = float(layer_el.get("Zmin"))
                    zmax = float(layer_el.get("Zmax"))
                except (TypeError, ValueError):
                    continue
                layer_el.set("Zmin", f"{zmin + offset:.4f}")
                layer_el.set("Zmax", f"{zmax + offset:.4f}")
            stackup_writer.set_substrate_offset(root, 0)

        # Resolve concrete absolute positions for everything exactly as the reader would,
        # now that Layers are offset-free - this is the ground truth the new Reference
        # attributes get derived from, computed once up front rather than incrementally,
        # so conversion order doesn't matter and there's no risk of compounding rounding.
        materials_list, dielectrics_list, metals_list = stackup_reader.parse_substrate(root)

        dielectric_elements = {d.get("Name"): d for d in self._dielectrics_container(root)}
        for dielectric in dielectrics_list.dielectrics:
            element = dielectric_elements.get(dielectric.name)
            if element is None or element.get("Reference"):
                continue  # already Reference-based - leave untouched
            candidate = self._nearest_reference_candidate(
                dielectric.zmin, dielectric.name, dielectrics_list.dielectrics, [],
                fallback_to_lowest_dielectric=False)
            if candidate is None:
                continue  # nothing below it - stays the natural implicit anchor at z=0
            candidate_name, candidate_edge, candidate_z = candidate

            offset_zmin = dielectric.zmin - candidate_z
            if abs(offset_zmin) > 1e-6:
                element.set("Zmin", f"{offset_zmin:.4f}")
            elif "Zmin" in element.attrib:
                del element.attrib["Zmin"]
            if "Zmax" in element.attrib:
                # Reference mode sizes from Thickness by default; a leftover absolute Zmax
                # would instead override that as an explicit offset - always wrong here
                del element.attrib["Zmax"]
            if "Thickness" not in element.attrib:
                element.set("Thickness", f"{dielectric.thickness:.4f}")
            element.set("Reference", candidate_name)
            element.set("ReferenceEdge", candidate_edge)

        layer_elements = {l.get("Name"): l for l in self._layers_container(root)}
        for metal in metals_list.metals:
            element = layer_elements.get(metal.name)
            if element is None or element.get("Reference"):
                continue  # already Reference-based - leave untouched
            candidate = self._nearest_reference_candidate(
                metal.zmin, metal.name, dielectrics_list.dielectrics, metals_list.metals,
                fallback_to_lowest_dielectric=True)
            if candidate is None:
                continue  # no dielectric in the file at all - nothing sensible to reference
            candidate_name, candidate_edge, candidate_z = candidate

            element.set("Zmin", f"{metal.zmin - candidate_z:.4f}")
            element.set("Zmax", f"{metal.zmax - candidate_z:.4f}")
            element.set("Reference", candidate_name)
            element.set("ReferenceEdge", candidate_edge)

        root.set("schemaVersion", "3.0")
        stackup_writer.stamp_reference_format_comment(root, stackup_reader.__version__)

    @staticmethod
    def _nearest_reference_candidate(zmin, exclude_name, dielectrics, metals, fallback_to_lowest_dielectric):
        """Find the best Reference target for an element positioned at `zmin`: among every
           other Dielectric's Top and Bottom edge, and every Layer's Top edge, the one with
           the largest z that is still at or below `zmin` - i.e. the nearest thing below,
           whether touching (gap 0) or not (e.g. a capacitor plate floating a small distance
           above the metal below it). Both Dielectric edges are real candidates for different
           reasons: another Dielectric's Top is where one stacks directly on the one below;
           a Dielectric's own Bottom is where the lowest Layer *inside* it naturally sits.
           `metals` should be [] when converting a Dielectric (Reference on a Dielectric can
           only target another Dielectric, never a Layer). Dielectrics are checked before
           metals, so an exact tie (both at the same z) prefers the Dielectric - more
           fundamental/stable a target than an individual Layer.
        Args:
            zmin (float): the element's own resolved absolute Zmin
            exclude_name (string): don't consider a candidate with this name (self)
            dielectrics (list of dielectric_layer): candidate Dielectric Top/Bottom edges
            metals (list of metal_layer): candidate Layer Top edges
            fallback_to_lowest_dielectric (bool): if no candidate qualifies (this element
                is the lowest thing in the whole stack), fall back to the lowest Dielectric's
                Bottom edge with whatever (possibly negative) offset that implies - used for
                Layers (e.g. a backside ground plane below the substrate); Dielectrics have
                no such fallback, since there both being asked here is what defines "lowest"
        Returns:
            (name, edge, z) of the chosen candidate, or None if there isn't one
        """
        epsilon = 1e-5
        best = None  # (z, name, edge)
        for dielectric in dielectrics:
            if dielectric.name == exclude_name:
                continue
            for edge, z in (("Top", dielectric.zmax), ("Bottom", dielectric.zmin)):
                if z <= zmin + epsilon and (best is None or z > best[0]):
                    best = (z, dielectric.name, edge)
        for metal in metals:
            if metal.name == exclude_name:
                continue
            z = metal.zmax
            if z <= zmin + epsilon and (best is None or z > best[0]):
                best = (z, metal.name, "Top")

        if best is not None:
            return best[1], best[2], best[0]
        if fallback_to_lowest_dielectric and dielectrics:
            lowest = min(dielectrics, key=lambda d: d.zmin)
            return lowest.name, "Bottom", lowest.zmin
        return None

    # ---------- convert to legacy format ----------

    def _on_convert_to_legacy_clicked(self):
        if self.tree is None:
            return

        message = (
            "Convert this stackup to the old schemaVersion \"2.0\" legacy format?\n\n"
            "- Every \"=\" expression is resolved to its literal value, and the Variables "
            "section is removed - schemaVersion \"2.0\" predates Variables/expressions.\n"
            "- Every Reference-positioned Layer is rewritten to absolute Zmin/Zmax. Every "
            "Reference-positioned Dielectric is rewritten to plain Thickness (implicit "
            "top-to-bottom stacking) wherever that alone still reproduces its current "
            "position, falling back to absolute Zmin/Zmax only where it doesn't.\n"
            "- Derived layers are removed, along with any Layer entry that exists only to "
            "give a derived layer its Z-position (its Layer number was never real GDSII "
            "geometry) - schemaVersion \"2.0\" predates derived layers too.\n"
            "- Thermal data is removed: the Tables section, and Density/ThermalConductivity/"
            "ThermalConductivityTable on every Material.\n\n"
            "Resulting absolute positions stay exactly the same.")

        reply = QMessageBox.question(self, "Convert to legacy format", message,
                                      QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        try:
            self._convert_to_legacy_format()
        except (Exception, SystemExit) as e:
            # _resolve_all_expressions() inside _convert_to_legacy_format() mutates the
            # tree progressively as it walks, unlike the rest of that function (whose only
            # other fallible step, parse_substrate(), runs before any mutation) - restore
            # the pre-conversion state so a failed attempt never leaves self.tree holding a
            # partial mix of resolved/unresolved attributes the UI isn't showing
            self.tree = ET.ElementTree(self._last_snapshot)
            self._last_snapshot = copy.deepcopy(self.tree.getroot())
            QMessageBox.warning(self, "Conversion failed",
                                 f"Could not convert - current stackup could not be fully "
                                 f"resolved:\n{e}")
            return

        # this conversion's whole point is implicit Thickness-based Dielectric stacking -
        # immediately re-offering to make it Reference-explicit again (a schemaVersion "3.0"
        # feature this conversion just removed) at the next Save would be self-contradictory,
        # so treat "asked" as already settled for the rest of this editing session
        self._asked_about_implicit_dielectric_references = True

        self._reload_all_editors()
        self._on_changed(structural=True)
        self._refresh_xml_preview_if_active()

    def _convert_to_legacy_format(self):
        """Resolves every "="-expression to its literal value and removes the Variables
           section, rewrites every Reference-positioned Layer/Dielectric to absolute
           positioning (preferring plain Thickness-based implicit stacking for a
           Dielectric wherever that alone reproduces its current resolved position),
           removes DerivedLayers (and any Layer entry that exists only to give a derived
           layer its Z-position), removes thermal data (Tables, and Density/
           ThermalConductivity/ThermalConductivityTable on every Material), and sets
           schemaVersion to "2.0" - the format read before Reference/DerivedLayers/
           Tables/Variables existed. The inverse of _convert_to_reference_format() above.
        """
        root = self.tree.getroot()

        # resolve every "="-expression to a literal first, and drop <Variables> - "2.0"
        # predates it entirely. Doing this before anything else below means every
        # existing raw-attribute read further down (e.g. layer_el.get("Reference") at
        # a Layer that has no Reference, whose Zmin/Zmax the Reference-only rewrite loop
        # below skips) already sees a plain literal, with no need to touch that loop's
        # own logic.
        variables = _build_variables_list(self._variables_container(root))
        _resolve_all_expressions(root, variables)
        variables_el = stackup_writer.get_variables_element(root)
        if variables_el is not None:
            root.remove(variables_el)
        for child in list(root):
            if child.tag is ET.Comment and (child.text or "").strip().startswith(
                    stackup_writer.VARIABLES_FORMAT_COMMENT_PREFIX):
                root.remove(child)

        # ground truth: fully resolved positions exactly as the reader sees them today,
        # captured once up front so every lookup below is against the *original* file,
        # never against a partially-converted in-progress state
        materials_list, dielectrics_list, metals_list = stackup_reader.parse_substrate(root)
        dielectric_by_name = {dielectric.name: dielectric for dielectric in dielectrics_list.dielectrics}

        # ---- Layers: Reference -> absolute Zmin/Zmax (no "implicit" alternative exists
        # for Layers - only Dielectrics can fall back to Thickness-based stacking) ----
        metal_by_name = {metal.name: metal for metal in metals_list.metals}
        for layer_el in self._layers_container(root):
            if not layer_el.get("Reference"):
                continue
            metal = metal_by_name.get(layer_el.get("Name"))
            if metal is None:
                continue
            layer_el.set("Zmin", f"{metal.zmin:.4f}")
            layer_el.set("Zmax", f"{metal.zmax:.4f}")
            for attr in ("Reference", "ReferenceEdge"):
                if attr in layer_el.attrib:
                    del layer_el.attrib[attr]

        # ---- Dielectrics: prefer implicit Thickness+order, fall back to absolute
        # Zmin/Zmax only where needed ----
        self._convert_dielectrics_to_legacy(root, dielectric_by_name)

        # ---- remove derived layers, and any Layer entry that exists only for one ----
        derived_layers_el = stackup_writer.get_derived_layers_element(root)
        if derived_layers_el is not None:
            derived_target_numbers = set()
            for derived_el in derived_layers_el.findall("DerivedLayer"):
                layernum = derived_el.get("Layer")
                if layernum is not None:
                    try:
                        derived_target_numbers.add(int(layernum))
                    except ValueError:
                        pass
            root.find("ELayers").remove(derived_layers_el)

            for layer_el in self._layers_container(root):
                layernum = layer_el.get("Layer")
                if layernum is None:
                    continue
                try:
                    if int(layernum) in derived_target_numbers:
                        stackup_writer.remove_layer(root, layer_el)
                except ValueError:
                    pass

            # this comment's claim (minimum reader version needed for DerivedLayers) no
            # longer applies once DerivedLayers itself has been removed above
            for child in list(root):
                if child.tag is ET.Comment and (child.text or "").strip().startswith(
                        stackup_writer.DERIVED_LAYERS_FORMAT_COMMENT_PREFIX):
                    root.remove(child)

        # ---- remove thermal data: Tables section, and thermal attributes on Materials ----
        tables_el = root.find("Tables")
        if tables_el is not None:
            root.remove(tables_el)

        for material_el in self._materials_container(root):
            for attr in ("Density", "ThermalConductivity", "ThermalConductivityTable"):
                if attr in material_el.attrib:
                    del material_el.attrib[attr]

        # this comment's claim (minimum reader version needed for Reference-relative
        # positioning) no longer applies once every Reference has been removed above
        for child in list(root):
            if child.tag is ET.Comment and (child.text or "").strip().startswith(
                    stackup_writer.REFERENCE_FORMAT_COMMENT_PREFIX):
                root.remove(child)

        root.set("schemaVersion", "2.0")

    def _convert_dielectrics_to_legacy(self, root, dielectric_by_name):
        """Decides, per Dielectric, whether plain Thickness (implicit top-to-bottom
           stacking) alone still reproduces its ground-truth resolved position, falling
           back to absolute Zmin/Zmax for the ones where it doesn't - then applies that
           decision to the real elements.

           Single greedy pass, bottom-to-top - the same order/direction as the reader's own
           dielectric_layers_list._assign_implicit_references(). A Dielectric is implicit-
           compatible exactly when its ground-truth zmin equals the top edge of the nearest
           dielectric below it that is *itself* implicit-compatible (or 0, if there is none) -
           an absolute-fallback Dielectric is transparent to this chain, exactly like the real
           implicit-stacking algorithm treats it, so walking bottom-to-top and carrying
           forward only the last implicit dielectric's zmax reproduces its decisions exactly,
           with no need to iterate/guess against a series of what-if hypotheses.
        """
        dielectric_elements = self._dielectrics_container(root)
        epsilon = 1e-4

        last_implicit_zmax = 0.0  # anchor: z=0 once nothing implicit sits below yet
        implicit_names = set()
        for element in reversed(dielectric_elements):
            ground_truth = dielectric_by_name.get(element.get("Name"))
            if ground_truth is None:
                continue
            if abs(ground_truth.zmin - last_implicit_zmax) < epsilon:
                implicit_names.add(element.get("Name"))
                last_implicit_zmax = ground_truth.zmax
            # else: falls back to absolute below: transparent to the chain, so
            # last_implicit_zmax carries forward unchanged to the next (higher) Dielectric

        for element in dielectric_elements:
            name = element.get("Name")
            ground_truth = dielectric_by_name.get(name)
            if ground_truth is None:
                continue
            for attr in ("Reference", "ReferenceEdge"):
                if attr in element.attrib:
                    del element.attrib[attr]
            if name in implicit_names:
                element.set("Thickness", f"{ground_truth.thickness:.4f}")
                for attr in ("Zmin", "Zmax"):
                    if attr in element.attrib:
                        del element.attrib[attr]
            else:
                element.set("Zmin", f"{ground_truth.zmin:.4f}")
                element.set("Zmax", f"{ground_truth.zmax:.4f}")
                if "Thickness" in element.attrib:
                    del element.attrib["Thickness"]
            # Boundary, if present, is orthogonal to position mode and stays untouched

    # ---------- file description ----------

    def _on_description_edited(self):
        if self.tree is None:
            return
        root = self.tree.getroot()
        current = stackup_writer.get_file_description(root)
        new_text = self.description_edit.toPlainText().strip()
        if new_text == current:
            return  # focus-out with no actual change - don't spend an undo step on it
        app_name = getattr(self.MainWindow, "APP_NAME", "openEMS Stackup Editor")
        stackup_writer.stamp_header_comments(root, app_name, new_text)
        self._on_changed()

    # ---------- change propagation ----------

    def _on_variables_changed(self, structural=False, edited_field=None):
        # a variable's Name/Value may have changed (add/remove/rename too) - unlike a Material/
        # Dielectric/Layer rename (which only the tabs "downstream" of it need to know about),
        # a Variable can be referenced from a "="-expression in literally any tab, so this needs
        # the broadest refresh of any change handler here
        self.materials_editor.reload()
        self.dielectrics_editor.reload()
        self.layers_editor.reload()
        self.derived_layers_editor.reload()
        self.tables_editor.reload()
        if self.points_editor.root is not None:
            self.points_editor.reload()
        self._on_changed(structural=structural, edited_field=edited_field)

    def _on_materials_changed(self, structural=False, edited_field=None):
        # material names may have changed (add/remove/rename) - refresh the
        # Material-reference dropdowns shown in the Dielectrics/Layers tabs
        self.dielectrics_editor.reload()
        self.layers_editor.reload()
        self._on_changed(structural=structural, edited_field=edited_field)

    def _on_dielectrics_changed(self, structural=False, edited_field=None):
        # a Dielectric's Thickness/Zmin/Zmax/Name may have changed (add/remove/reorder
        # too) - the Layers tab's ResultZmin/ResultZmax and its Reference dropdown
        # choices both depend on the current Dielectrics tab state, so refresh it too
        self.layers_editor.reload()
        self._on_changed(structural=structural, edited_field=edited_field)

    def _on_tables_changed(self, structural=False, edited_field=None):
        # table names may have changed (add/remove/rename) - refresh the Materials tab's
        # ThermalConductivityTable dropdown choices, and resync the Points detail editor
        # (a selected Table may have just been removed, or rows may have shifted)
        self.materials_editor.reload()
        self._sync_points_editor_from_table_selection()
        self._on_changed(structural=structural, edited_field=edited_field)

    def _on_points_changed(self, structural=False, edited_field=None):
        self._resync_tables_editor_point_counts()
        self._on_changed(structural=structural, edited_field=edited_field)

    def _sync_points_editor_from_table_selection(self):
        if self.tree is None:
            self.points_editor.set_root(None)
            return
        selected = self.tables_editor.table.selectedIndexes()
        row = selected[0].row() if selected else -1
        row_elements = self.tables_editor.row_elements
        table_el = row_elements[row] if 0 <= row < len(row_elements) else None
        self.points_editor.set_root(table_el)

    def _resync_tables_editor_point_counts(self):
        """Refreshes the master Tables editor's Points (count) column after a Point is
           added/removed/edited, without losing the currently-selected Table row. A plain
           self.tables_editor.reload() clears the table's row selection (reload() never
           re-selects anything), which - via the itemSelectionChanged-driven sync above -
           would immediately blank the Points editor out from under the very edit that just
           triggered this call. So: remember the bound Table element, reload, then find and
           re-select its row if it's still there.
        """
        selected_table = self.points_editor.root
        self.tables_editor.reload()
        if selected_table is not None:
            try:
                row = self.tables_editor.row_elements.index(selected_table)
            except ValueError:
                row = -1
            if row >= 0:
                self.tables_editor.table.selectRow(row)

    def _on_changed(self, structural=False, edited_field=None):
        # every edit path (cell edit, add/remove/move, offset edit) funnels through
        # here exactly once per logical user action, right after the mutation has
        # already been applied - which makes this the one place that needs to know
        # about undo, rather than instrumenting every mutating call site individually
        self._record_undo_point()
        self._revalidate_and_refresh(edited_field=edited_field)

    def _is_invalid_field(self, element, attr):
        return self._invalid_field is not None and self._invalid_field == (element, attr)

    def _revalidate_and_refresh(self, edited_field=None):
        if self.tree is None:
            return
        root = self.tree.getroot()
        errors = stackup_writer.validate_stackup(root)
        warnings = stackup_writer.find_reserved_material_definitions(root)

        was_valid = self._was_valid
        self._was_valid = not errors
        new_invalid_field = self._invalid_field
        if errors and was_valid and edited_field is not None:
            # this specific field's edit is what just made an until-now-valid file
            # invalid - mark only that one field, not the (possibly unrelated) cell
            # an error message happens to be worded around
            new_invalid_field = edited_field
        elif not errors:
            new_invalid_field = None
        if new_invalid_field != self._invalid_field:
            self._invalid_field = new_invalid_field
            # invalid_fn-driven red-text state just changed for some cell somewhere -
            # reload every tab so whichever one owns that cell repaints it (same
            # "just reload what might need it" approach _on_variables_changed already
            # uses, cheap enough for these file sizes not to need finer targeting).
            # Deferred, same reason ElementTableEditor._set_attr() defers its own
            # reload_on_attr_change reload: this may be firing from inside the very
            # cell widget (e.g. a combo box) a synchronous reload() would tear down
            # and recreate out from under the signal that's still emitting it.
            QTimer.singleShot(0, self._reload_all_editors)

        self._refresh_preview(root, errors)
        self._refresh_validation_status(errors, warnings)

    # ---------- undo (bounded multi-level) ----------

    def _reset_undo_baseline(self):
        # called after loading/creating a tree: that's a new starting point, not
        # an "edit" - there is nothing to undo back to across a file boundary
        self._last_snapshot = copy.deepcopy(self.tree.getroot()) if self.tree is not None else None
        self._undo_stack = []
        self._set_undo_available(False)
        # same "new starting point" reasoning: whatever was blamed for the previous
        # file's invalidity is meaningless for this one
        self._was_valid = True
        self._invalid_field = None

    def _record_undo_point(self):
        if self.tree is None:
            return
        # self._last_snapshot is always an independent deep copy made before the
        # change that was just applied - push it as the oldest-to-newest undo
        # target, dropping the oldest entry once the buffer is full, then take a
        # fresh independent copy of the now-current (post-change) state ready to
        # serve as the "before" snapshot for whatever gets edited next
        self._undo_stack.append(self._last_snapshot)
        if len(self._undo_stack) > self.UNDO_LEVELS:
            self._undo_stack.pop(0)
        self._last_snapshot = copy.deepcopy(self.tree.getroot())
        self._set_undo_available(bool(self._undo_stack))

    def _set_undo_available(self, enabled):
        self.undo_action.setEnabled(enabled)

    def undo(self):
        if not self._undo_stack or self.tree is None:
            return
        self.tree = ET.ElementTree(self._undo_stack.pop())
        # the restored state becomes the new baseline for whatever gets edited (or
        # undone again) next; no redo - only stepping further back is supported
        self._last_snapshot = copy.deepcopy(self.tree.getroot())
        self._set_undo_available(bool(self._undo_stack))
        self._reload_all_editors()
        self._revalidate_and_refresh()
        self._refresh_xml_preview_if_active()

    def _refresh_preview(self, root, errors):
        if errors:
            # data is not fully consistent yet (e.g. mid-edit) - leave the last
            # good preview showing rather than risk parse_substrate() choking on it
            return
        try:
            materials_list, dielectrics_list, metals_list = stackup_reader.parse_substrate(root)
        except (Exception, SystemExit):
            # SystemExit is caught deliberately (not just Exception): the reader's
            # derived_layer class calls exit(1) on a handful of hard requirements
            # (invalid Operation, wrong operand count, ...) instead of raising.
            # validate_stackup()'s DerivedLayers checks mirror those requirements
            # exactly so errors should already be non-empty and we shouldn't even
            # get here, but this is cheap insurance against ending the whole
            # process over a gap in that mirroring rather than just skipping a
            # preview refresh.
            return
        self.vector_widget.refresh(materials_list, dielectrics_list, metals_list)
        self.chiplet_switcher.set_groups(dielectrics_list.chiplet_groups)

    def _on_preview_element_selected(self, kind, name):
        """Preview -> table: a shape was clicked in the cross-section preview -
           switch to its tab and select its row there."""
        editor = self.dielectrics_editor if kind == "dielectric" else self.layers_editor
        tab_widget = editor if kind == "dielectric" else self.layers_tab
        try:
            row = next(i for i, el in enumerate(editor.row_elements) if el.get("Name") == name)
        except StopIteration:
            return
        self.tabs.setCurrentWidget(tab_widget)
        if editor.table.currentRow() != row:
            editor.table.selectRow(row)

    def _on_dielectrics_row_selected(self):
        """Table -> preview: a Dielectric Stack row was selected - highlight the
           matching slab in the preview."""
        row = self.dielectrics_editor.table.currentRow()
        if 0 <= row < len(self.dielectrics_editor.row_elements):
            name = self.dielectrics_editor.row_elements[row].get("Name")
            if name:
                self.vector_widget.select_element("dielectric", name)

    def _on_layers_row_selected(self):
        """Table -> preview: a Layers row was selected - highlight the matching
           metal/via/sheet box in the preview."""
        row = self.layers_editor.table.currentRow()
        if 0 <= row < len(self.layers_editor.row_elements):
            name = self.layers_editor.row_elements[row].get("Name")
            if name:
                self.vector_widget.select_element("layer", name)
        self.vector_widget.update()

    def _refresh_validation_status(self, errors, warnings=None):
        warnings = warnings or []
        if errors:
            self.status_label.setText(f"{len(errors)} problem(s) - see Save for details.")
            self.status_label.setStyleSheet("color: darkred;")
        elif warnings:
            self.status_label.setText(f"Valid - {len(warnings)} note(s): " + "; ".join(warnings))
            self.status_label.setStyleSheet("color: #b8860b;")
        else:
            self.status_label.setText("Valid.")
            self.status_label.setStyleSheet("color: green;")

    def _on_tab_changed(self, index):
        if self.tabs.widget(index) is self.xml_preview_tab:
            self._refresh_xml_preview()

    def _refresh_xml_preview_if_active(self):
        # the tab only auto-refreshes on switching into it (_on_tab_changed) - if it's
        # already the active tab when the whole file changes underneath it (New/Open/
        # Import/Convert), no tab switch happens to trigger that, so those call sites
        # refresh explicitly instead, same as they already do for every other tab
        if self.tabs.currentWidget() is self.xml_preview_tab:
            self._refresh_xml_preview()

    def _refresh_xml_preview(self):
        """Shows exactly what Save would write right now, without side effects: works
           on a deep copy (never touches self.tree), and - unlike an actual Save -
           never pops the one-time "make implicit dielectric stacking explicit?"
           confirmation (see _maybe_offer_explicit_dielectric_references()), since a
           passive preview can't ask the user anything.
        """
        if self.tree is None:
            self.xml_preview_edit.setPlainText("(no file loaded)")
            return

        root = self.tree.getroot()
        errors = stackup_writer.validate_stackup(root)
        if errors:
            self.xml_preview_edit.setPlainText(
                "Cannot preview - fix these problems before saving:\n\n" +
                "\n".join(f"- {e}" for e in errors))
            return

        preview_tree = ET.ElementTree(copy.deepcopy(root))
        app_name = getattr(self.MainWindow, "APP_NAME", "openEMS Stackup Editor")
        stackup_writer.stamp_header_comments(
            preview_tree.getroot(), app_name, self.description_edit.toPlainText())

        fd, temp_path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        try:
            stackup_writer.save_stackup_tree(preview_tree, temp_path)
            with open(temp_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            text = f"(preview unavailable: {e})"
        finally:
            os.unlink(temp_path)
        self.xml_preview_edit.setPlainText(text)


# ------------------------------------------------------------------
# Standalone launch (python stackupEditor.py [file.xml], or the stackupEditor
# console script - see pyproject.toml)
# ------------------------------------------------------------------

class _StandaloneMainWindow:
    """Minimal stand-in for a full host application's MainWindow. This editor has no such
       host in gds2openEMS (unlike setupEM's original, where the equivalent stand-in exists
       only as a fallback for the rare direct-run case, since setupEM/setupThermal normally
       provide a real MainWindow) - here it is the only way this window is ever constructed,
       via main() below. Provides the handful of attributes/methods StackupEditorWindow needs
       from its MainWindow argument. The preview coloring/labeling hooks reuse the same
       permittivity/sheet-resistance-based defaults this module's ported setupEM ancestor
       used (see editor_common.epsilon_to_color()/default_stackup_dielectric_label()/
       default_stackup_metal_label()).
    """
    APP_NAME = "openEMS Stackup Editor"
    saved_values = {}

    def stackup_dielectric_color(self, material):
        return epsilon_to_color(material.eps, 95)

    def stackup_dielectric_label(self, dielectric, material):
        return default_stackup_dielectric_label(dielectric, material)

    def stackup_metal_label(self, metal, material, is_sheet):
        return default_stackup_metal_label(metal, material, is_sheet)

    def stackup_via_label_suffix(self, metal, material):
        return ""


def main():
    """Run the openEMS Stackup Editor as a standalone application - this is for
       editing/inspecting an openEMS-format stackup file on its own, with no
       gds2openEMS model/simulation setup involved. Preview coloring/labeling uses
       the permittivity/sheet-resistance-based defaults from editor_common.py (see
       _StandaloneMainWindow).
    """
    app = QApplication(sys.argv)
    if sys.platform.startswith("win"):
        # without this, Qt's default style on Windows looks visibly different
        # (fonts/widget chrome) from the platform-native style
        app.setStyle(QStyleFactory.create("Windows"))

    parser = argparse.ArgumentParser(description="Standalone stackup XML editor")
    parser.add_argument("xmlfile", nargs="?", default=None, help="stackup XML file to open")
    args = parser.parse_args()

    window = StackupEditorWindow(_StandaloneMainWindow(), initial_filename=args.xmlfile)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
