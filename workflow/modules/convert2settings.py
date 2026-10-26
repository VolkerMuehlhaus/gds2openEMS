#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert a loose-variable openEMS model (gds2openEMS) to the settings[] workflow.

Older models define plain variables and call the workflow positionally:

    margin = 50
    simulation_setup.setupSimulation(excite_ports, simulation_ports, FDTD, ..., margin, unit)

The converted model stores them in a ``settings`` dict and calls

    simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)

like the current gds2openEMS examples and the EMStudio template.

Nothing is guessed from a variable name. A variable becomes ``settings['key']`` only when
its meaning is proven:

* it is passed to a workflow function (setupSimulation, runSimulation, read_gds,
  read_substrate): the key is that parameter (keywords/workflow_signatures.csv maps read_gds
  parameters such as ``preprocess`` to their keyword ``preprocess_gds``);
* or it sits in one of the expressions the workflow itself uses with these settings
  (``openEMS(EndCriteria=exp(X/10*log(10)))``, ``SetGaussExcite((A+B)/2, (B-A)/2)``,
  ``SetBoundaryCond(X)``, ``linspace(fstart, fstop, X)`` and the max_cellsize formula, which
  must equal the formula in the workflow's setupSimulation).

The imports of a local ``modules`` folder are switched to the installed gds2openEMS package
(this one), and a ``sys.path`` line that points to that folder is removed. The workflow source of
this package is parsed to check that its settings branch reads the keys the conversion writes,
with the same defaults. Anything unproven stays a variable, anything the converter can't handle
safely is refused, and the result is verified: the edited text must parse to exactly the AST
that the intended transformation gives.

Usage:
    convert2settings model.py [more models or folders] [--engine gpu] [--dry-run] [--json]

Each model is written to <name>_settings.py next to it. The model itself is never written, and an
existing <name>_settings.py is never overwritten.

Ported from EMStudio's scripts/convert_loose_to_settings.py (2026-10-02, 547ee77); the analysis
and the proof are the same, keep both in sync.
"""

from __future__ import annotations

import argparse
import ast
import copy
import csv
import difflib
import importlib.util
import io
import json
import os
import re
import sys
import tokenize

WORKFLOW_CALLS = ("setupSimulation", "runSimulation")
WORKFLOW_SOURCE = "util_simulation_setup.py"
PACKAGE = "gds2openEMS"

# Signature default vs settings.get() default that differ in spelling but act the same in
# runSimulation: preview_only / postprocess_only are only tested for truth (None, False and ''
# are all false), numThreads None is replaced by 0 before use.
EQUIVALENT_DEFAULTS = {
    ("runSimulation", "preview_only"),
    ("runSimulation", "postprocess_only"),
    ("runSimulation", "numThreads"),
}

# Names whose use makes a static rename unsafe.
DYNAMIC_NAME_ACCESS = {"exec", "eval", "globals", "locals", "vars"}

FORMULA_NOTE = ("# max_cellsize is calculated by setupSimulation from settings['fstop'], "
                "settings['unit'] and settings['cells_per_wavelength']")

# (function, argument position, parameter, settings key) for the reader functions whose
# arguments have a settings key (EMStudio keywords/workflow_signatures.csv). The parameters of
# setupSimulation / runSimulation come from the workflow source itself.
SIGNATURES = [
    ("read_gds", 2, "purposelist", "purpose"),
    ("read_gds", 4, "preprocess", "preprocess_gds"),
    ("read_gds", 5, "merge_polygon_size", "merge_polygon_size"),
    ("read_gds", 11, "cellname", "cellname"),
    ("read_substrate", 1, "variable_overrides", "variable_overrides"),
]

ENGINES = ("gpu",)        # openEMS --engine values offered by --engine (the CPU is the default)


class Refused(Exception):
    """The model can't be converted safely; the message says why."""


# --------------------------------------------------------------------------------------------
# Small AST helpers
# --------------------------------------------------------------------------------------------

def call_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def is_literal(node):
    try:
        ast.literal_eval(node)
        return True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False


def parse_expr(text):
    return ast.parse(text, mode="eval").body


def settings_ref(key, ctx):
    node = parse_expr("settings[%r]" % key)
    node.ctx = ctx
    return node


def stmt_lists(node):
    """Yields (owner, field) for every statement list inside node (not descending)."""
    for field in ("body", "orelse", "finalbody"):
        value = getattr(node, field, None)
        if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
            yield node, field
    for handler in getattr(node, "handlers", []) or []:
        yield handler, "body"
    for case in getattr(node, "cases", []) or []:
        yield case, "body"


def module_level_statements(tree):
    """Statements reachable from the module without entering a def, lambda or class."""
    out = []
    todo = [tree]
    while todo:
        node = todo.pop()
        for owner, field in stmt_lists(node):
            for stmt in getattr(owner, field):
                out.append(stmt)
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    todo.append(stmt)
    return out


def binding_counts(tree):
    """Counts every way a name gets bound anywhere in the module."""
    counts = {}

    def add(name):
        counts[name] = counts.get(name, 0) + 1

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            add(node.id)
        elif isinstance(node, ast.arg):
            add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(node.name)
        elif isinstance(node, ast.alias):
            add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                add(name)
        elif type(node).__name__ in ("MatchAs", "MatchStar") and getattr(node, "name", None):
            add(node.name)
        elif type(node).__name__ == "MatchMapping" and getattr(node, "rest", None):
            add(node.rest)
    return counts


def load_counts(tree):
    counts = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            counts[node.id] = counts.get(node.id, 0) + 1
    return counts


class NumpyNames:
    """Tells whether a call target is a numpy function (np.exp, or exp from a star import)."""

    def __init__(self, tree, module_bindings):
        self.aliases = set()
        self.star = False
        for node in tree.body:
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "numpy":
                        self.aliases.add(a.asname or "numpy")
            elif isinstance(node, ast.ImportFrom) and node.module in ("numpy", "pylab"):
                if any(a.name == "*" for a in node.names):
                    self.star = True
                    # matplotlib.pylab has no __all__ and does "import numpy as np"
                    if node.module == "pylab":
                        self.star_np = True
        self.bound = module_bindings
        if getattr(self, "star_np", False) and module_bindings.get("np", 0) == 0:
            self.aliases.add("np")

    def name(self, node):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in self.aliases):
            return node.attr
        if isinstance(node, ast.Name) and self.star and self.bound.get(node.id, 0) == 0:
            return node.id
        return None


def canonical(node, names, numpy_names, free):
    """Structural text of an expression; names maps variables to keys, other names go to free."""
    if isinstance(node, ast.Constant):
        return "C(%r)" % (node.value,)
    if isinstance(node, ast.Name):
        if node.id in names:
            return "K(%s)" % names[node.id]
        free.append(node.id)
        return "F(%s)" % node.id
    if isinstance(node, ast.BinOp):
        return "(%s %s %s)" % (canonical(node.left, names, numpy_names, free),
                               type(node.op).__name__,
                               canonical(node.right, names, numpy_names, free))
    if isinstance(node, ast.UnaryOp):
        return "(%s %s)" % (type(node.op).__name__, canonical(node.operand, names, numpy_names, free))
    if isinstance(node, ast.Call) and not node.keywords:
        fn = numpy_names.name(node.func)
        if fn is None:
            raise ValueError("call")
        return "numpy.%s(%s)" % (fn, ", ".join(canonical(a, names, numpy_names, free)
                                               for a in node.args))
    if isinstance(node, ast.Attribute):
        return "%s.%s" % (canonical(node.value, names, numpy_names, free), node.attr)
    raise ValueError(type(node).__name__)


def inline(node, name, value):
    """Copy of node with Name(name) replaced by value."""
    class Sub(ast.NodeTransformer):
        def visit_Name(self, n):
            if n.id == name and isinstance(n.ctx, ast.Load):
                return copy.deepcopy(value)
            return n
    return Sub().visit(copy.deepcopy(node))


# --------------------------------------------------------------------------------------------
# Workflow source
# --------------------------------------------------------------------------------------------

class WorkflowFunction:
    def __init__(self, fn):
        self.name = fn.name
        args = fn.args.args
        self.params = [a.arg for a in args]
        defaults = fn.args.defaults
        self.defaults = {}
        for a, d in zip(args[len(args) - len(defaults):], defaults):
            self.defaults[a.arg] = d
        self.reads = {}          # key -> list of defaults (None entry = required read)
        self.local_keys = {}     # local variable -> settings key it is read from
        for node in ast.walk(fn):
            key, default, required = self._settings_read(node)
            if key is None:
                continue
            self.reads.setdefault(key, []).append(None if required else default)
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                key, _, _ = self._settings_read(node.value)
                if key is not None:
                    self.local_keys.setdefault(node.targets[0].id, set()).add(key)
        self.fn = fn

    @staticmethod
    def _settings_read(node):
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id == "settings" and isinstance(node.ctx, ast.Load)):
            key = node.slice
            if type(key).__name__ == "Index":   # Python 3.8
                key = key.value
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                return key.value, None, True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "settings" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            default = node.args[1] if len(node.args) > 1 else parse_expr("None")
            return node.args[0].value, default, False
        return None, None, False

    def formula(self):
        """(wavelength_air, max_cellsize) assignments of the settings branch, or None."""
        assigns = {}
        for node in ast.walk(self.fn):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in ("wavelength_air", "max_cellsize")
                    and not isinstance(node.value, (ast.Call, ast.Constant, ast.Name))):
                assigns.setdefault(node.targets[0].id, node.value)
        if "wavelength_air" in assigns and "max_cellsize" in assigns:
            return inline(assigns["max_cellsize"], "wavelength_air", assigns["wavelength_air"])
        return None


class Workflow:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.tree = ast.parse(f.read(), filename=path)
        self.functions = {}
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in WORKFLOW_CALLS:
                self.functions[node.name] = WorkflowFunction(node)
        bindings = binding_counts(self.tree)
        self.numpy = NumpyNames(self.tree, bindings)

    def supports_settings(self):
        return all(name in self.functions and "settings" in self.functions[name].params
                   for name in WORKFLOW_CALLS)

    def formula_canonical(self):
        fn = self.functions.get("setupSimulation")
        expr = fn.formula() if fn else None
        if expr is None:
            return None
        names = {}
        for var, keys in fn.local_keys.items():
            if len(keys) == 1:
                names[var] = next(iter(keys))
        names.setdefault("materials_list", "materials_list")
        free = []
        try:
            text = canonical(expr, names, self.numpy, free)
        except ValueError:
            return None
        return text if not free else None


def exported_names(init_path):
    """Names bound at the top level of a package __init__.py (or its __all__)."""
    try:
        with open(init_path, "rb") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return None
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def top_level_defs(path):
    try:
        with open(path, "rb") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return None
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


def find_package_dir(explicit):
    if explicit:
        return explicit if os.path.isfile(os.path.join(explicit, WORKFLOW_SOURCE)) else None
    # this converter is part of the package it converts to
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.isfile(os.path.join(here, WORKFLOW_SOURCE)):
        return here
    try:
        spec = importlib.util.find_spec(PACKAGE)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    for loc in spec.submodule_search_locations:
        if os.path.isfile(os.path.join(loc, WORKFLOW_SOURCE)):
            return loc
    return None


def read_signatures(path):
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="\t"):
            if len(row) >= 4 and row[1].strip().isdigit():
                rows.append((row[0].strip(), int(row[1]), row[2].strip(), row[3].strip()))
    return rows


# --------------------------------------------------------------------------------------------
# Source text with positions
# --------------------------------------------------------------------------------------------

class Source:
    def __init__(self, raw):
        self.encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig" if self.bom else self.encoding)
        self.text = text
        self.lines = text.splitlines(keepends=True)
        self.starts = []
        pos = 0
        for line in self.lines:
            self.starts.append(pos)
            pos += len(line)
        self.starts.append(pos)
        crlf = text.count("\r\n")
        self.newline = "\r\n" if crlf and crlf * 2 >= text.count("\n") else "\n"

    def offset(self, lineno, col):
        """Character offset of an AST position (col is a UTF-8 byte offset)."""
        line = self.lines[lineno - 1] if lineno - 1 < len(self.lines) else ""
        chars = len(line.encode("utf-8")[:col].decode("utf-8", errors="strict"))
        return self.starts[lineno - 1] + chars

    def span(self, node):
        return (self.offset(node.lineno, node.col_offset),
                self.offset(node.end_lineno, node.end_col_offset))

    def line_start(self, lineno):
        return self.starts[lineno - 1]

    def line_end(self, lineno):
        """Offset after the newline of line lineno."""
        return self.starts[lineno]

    def indent_of(self, node):
        line = self.lines[node.lineno - 1]
        prefix = line.encode("utf-8")[:node.col_offset].decode("utf-8")
        return prefix

    def owns_lines(self, node):
        """True when the statement is alone on its lines (only whitespace before, comment after)."""
        if self.indent_of(node).strip():
            return False
        last = self.lines[node.end_lineno - 1]
        tail = last.encode("utf-8")[node.end_col_offset:].decode("utf-8")
        return re.fullmatch(r"[ \t]*(#[^\r\n]*)?(\r\n|\n|\r)?", tail) is not None

    def encode(self, text):
        data = text.encode("utf-8" if self.bom else self.encoding)
        return (b"\xef\xbb\xbf" + data) if self.bom else data


def comments_in(src, start, end, exclude):
    """Comment texts inside [start, end) that are not inside any of the exclude spans."""
    out = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src.text).readline)
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            pos = src.starts[tok.start[0] - 1] + tok.start[1]
            if start <= pos < end and not any(a <= pos < b for a, b in exclude):
                out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        pass
    return out


# --------------------------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------------------------

class Converter:
    def __init__(self, model_path, signatures, package_dir, engine=None):
        self.model_path = os.path.abspath(model_path)
        self.engine = engine          # openEMS engine to set in the converted model, or None
        self.syspath_stmts = []       # sys.path lines for the local modules folder, removed
        self.removed = []             # line numbers of removed sys.path statements
        with open(self.model_path, "rb") as f:
            raw = f.read()
        self.src = Source(raw)
        try:
            self.tree = ast.parse(raw, filename=self.model_path)
        except SyntaxError as e:
            raise Refused("the model has a syntax error (line %s): %s" % (e.lineno, e.msg))
        self.signatures = signatures
        self.package_dir = package_dir
        self.converted = []       # dicts: name, key, line, proof
        self.loose = []           # dicts: name, line, reason
        self.notes = []
        self.calls = []           # dicts: function, line
        self.dropped = []         # line numbers of dropped formula statements
        self.workflow_info = {}

    # ---- analysis ------------------------------------------------------------------------

    def analyse(self):
        tree = self.tree
        self.bindings = binding_counts(tree)
        self.loads = load_counts(tree)
        self.numpy = NumpyNames(tree, self.bindings)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in DYNAMIC_NAME_ACCESS:
                raise Refused("the model calls %s(), so variables can't be renamed safely"
                              % node.func.id)
            if isinstance(node, ast.Name) and node.id == "settings" or \
                    isinstance(node, ast.arg) and node.arg == "settings":
                raise Refused("the model already uses a name 'settings' (line %d)" % node.lineno)

        # Top-level literal assignments: name -> Assign statement (only the single binding counts).
        self.literals = {}
        for stmt in tree.body:
            if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name) and is_literal(stmt.value)):
                self.literals.setdefault(stmt.targets[0].id, stmt)

        self._find_workflow_calls()
        self._check_workflow_source()
        self._bind_variables()
        self._check_workflow_reads()
        self._plan_engine()

    def _plan_engine(self):
        """The runSimulation() statement that gets settings['engine'] (the first one)."""
        self.engine_stmt = None
        if not self.engine:
            return
        runs = [(s, c) for s, c in self.call_stmts if call_name(c) == "runSimulation"]
        if not runs:
            raise Refused("--engine needs a runSimulation() call in the model")
        for _, call in runs:
            if any(p == "engine" for p, _ in self.call_args[id(call)]):
                raise Refused("runSimulation() on line %d already passes engine; leave out --engine"
                              % call.lineno)
        if "engine" not in self.workflow.functions["runSimulation"].reads:
            raise Refused("%s doesn't read settings['engine'] (needs gds2openEMS 0.6.3 or newer)"
                          % self.workflow.path)
        self.engine_stmt = runs[0][0]

    def _find_workflow_calls(self):
        reachable = set(id(s) for s in module_level_statements(self.tree))
        self.call_stmts = []      # (stmt, call)
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call) and call_name(node) in WORKFLOW_CALLS):
                continue
            stmt = None
            for candidate in ast.walk(self.tree):
                if not isinstance(candidate, (ast.Expr, ast.Assign)):
                    continue
                value = candidate.value
                # The call itself, or the only argument of name.method(call) such as
                # data_paths.append(runSimulation(...)): looking up a method on a name has no
                # side effects, so the settings lines may run before it.
                if value is node or (isinstance(value, ast.Call) and len(value.args) == 1
                                     and value.args[0] is node and not value.keywords
                                     and isinstance(value.func, ast.Attribute)
                                     and isinstance(value.func.value, ast.Name)):
                    stmt = candidate
                    break
            name = call_name(node)
            if stmt is None or id(stmt) not in reachable:
                raise Refused("%s() on line %d is not a plain statement at module level or in a "
                              "loop / if block" % (name, node.lineno))
            if isinstance(stmt, ast.Assign) and not (len(stmt.targets) == 1
                                                     and isinstance(stmt.targets[0], ast.Name)):
                raise Refused("%s() on line %d assigns its result to more than one name"
                              % (name, node.lineno))
            if any(isinstance(a, ast.Starred) for a in node.args) or \
                    any(k.arg is None for k in node.keywords):
                raise Refused("%s() on line %d uses *args or **kwargs" % (name, node.lineno))
            if any(k.arg == "settings" for k in node.keywords):
                raise Refused("%s() on line %d already passes settings=; the model is not a "
                              "loose-variable model" % (name, node.lineno))
            if not self.src.owns_lines(stmt):
                raise Refused("%s() on line %d shares its line with other code" % (name, node.lineno))
            self.call_stmts.append((stmt, node))
        if not self.call_stmts:
            raise Refused("the model has no setupSimulation() / runSimulation() call")
        self.call_stmts.sort(key=lambda sc: (sc[0].lineno, sc[0].col_offset))

    def _local_module(self, name):
        """Module name inside the model's modules folder that an import name refers to:
        'modules.util_X' and, with sys.path pointing into the folder, plain 'util_X' when
        modules/util_X.py exists. '' for the modules package itself, None for anything else."""
        if name == "modules":
            return ""
        if name.startswith("modules."):
            return name[len("modules."):]
        if "." not in name and os.path.isfile(os.path.join(self.model_dir, "modules", name + ".py")):
            return name
        return None

    def _imports(self):
        """Top-level imports from the local modules folder; name -> (origin, module) bindings."""
        modules_imports = []
        bound = {}                # bound name -> ("modules" | "package", submodule)
        for stmt in module_level_statements(self.tree):
            if isinstance(stmt, ast.Import):
                local = False
                for a in stmt.names:
                    sub = self._local_module(a.name)
                    if sub is not None:
                        local = True
                        if a.asname:
                            bound[a.asname] = ("modules", sub)
                        elif "." not in a.name:
                            bound[a.name] = ("modules", sub)
                    elif a.name.startswith(PACKAGE + ".") and a.asname:
                        bound[a.asname] = ("package", a.name[len(PACKAGE) + 1:])
                if local:
                    modules_imports.append(stmt)
            elif isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module:
                sub = self._local_module(stmt.module)
                origin = "modules" if sub is not None else (
                    "package" if stmt.module == PACKAGE or stmt.module.startswith(PACKAGE + ".") else None)
                if origin is None:
                    continue
                if origin == "modules":
                    modules_imports.append(stmt)
                else:
                    sub = stmt.module[len(PACKAGE) + 1:] if stmt.module != PACKAGE else ""
                for a in stmt.names:
                    if a.name == "*":
                        if sub == "":
                            # the package __init__ binds the standard aliases
                            for alias, mod in (("simulation_setup", "util_simulation_setup"),):
                                bound.setdefault(alias, (origin, mod))
                        continue
                    if sub == "":
                        bound[a.asname or a.name] = (origin, a.name)
        return modules_imports, bound

    def _check_workflow_source(self):
        self.model_dir = os.path.dirname(self.model_path)
        modules_imports, bound = self._imports()
        self.modules_imports = modules_imports
        model_dir = self.model_dir
        local = os.path.join(model_dir, "modules", WORKFLOW_SOURCE)
        pkg_dir = find_package_dir(self.package_dir)
        info = self.workflow_info
        info["package_dir"] = pkg_dir
        self.needs_switch = False

        # Where do the workflow calls come from? simulation_setup.setupSimulation(...) -> the
        # import that binds simulation_setup.
        origins = set()
        for _, call in self.call_stmts:
            func = call.func
            base = func.value.id if (isinstance(func, ast.Attribute)
                                     and isinstance(func.value, ast.Name)) else None
            origin = bound.get(base) if base else None
            if origin is None or origin[1] != WORKFLOW_SOURCE[:-3]:
                raise Refused("can't tell which workflow %s() on line %d comes from"
                              % (call_name(call), call.lineno))
            origins.add(origin[0])
        if len(origins) != 1:
            raise Refused("the workflow calls come from both the modules folder and %s" % PACKAGE)
        origin = origins.pop()

        current = None
        if origin == "package":
            info["source"] = "package"
            if pkg_dir is None:
                raise Refused("the model imports %s, but this Python doesn't have it installed"
                              % PACKAGE)
            current = Workflow(os.path.join(pkg_dir, WORKFLOW_SOURCE))
        else:
            info["source"] = "modules"
            if os.path.isfile(local):
                current = Workflow(local)

        info["path"] = current.path if current else local
        info["supports_settings"] = bool(current and current.supports_settings())
        if origin == "package":
            if current.supports_settings():
                self.workflow = current
                return
            raise Refused("the installed %s doesn't support settings= in setupSimulation / "
                          "runSimulation" % PACKAGE)

        # Imports from a local modules folder are always switched to this package: the converted
        # model uses the current workflow, like the gds2openEMS examples.
        self.needs_switch = True
        why = "the model imports a local modules folder"
        if pkg_dir is None:
            raise Refused(why + ", and %s is not installed in this Python" % PACKAGE)
        package = Workflow(os.path.join(pkg_dir, WORKFLOW_SOURCE))
        if not package.supports_settings():
            raise Refused(why + ", and the installed %s doesn't support settings= either" % PACKAGE)
        self.switch_problems = self._plan_import_switch(pkg_dir, model_dir)
        if self.switch_problems:
            raise Refused(why + "; switching the imports to %s is not possible: %s"
                          % (PACKAGE, "; ".join(self.switch_problems)))
        info["switch_reason"] = why
        self.workflow = package
        self.syspath_stmts = self._modules_syspath_statements()

    @staticmethod
    def _names_modules_folder(node):
        """True when an expression contains a string that names a folder 'modules'."""
        for n in ast.walk(node):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                if re.fullmatch(r"(.*[/\\])?modules[/\\]?", n.value):
                    return True
        return False

    def _modules_syspath_statements(self):
        """Top-level sys.path.insert(...) / sys.path.append(...) statements that add the local
        modules folder: they are removed together with the import switch."""
        out = []
        for stmt in self.tree.body:
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
                continue
            func = stmt.value.func
            if not (isinstance(func, ast.Attribute) and func.attr in ("insert", "append")
                    and isinstance(func.value, ast.Attribute) and func.value.attr == "path"
                    and isinstance(func.value.value, ast.Name) and func.value.value.id == "sys"):
                continue
            if not any(self._names_modules_folder(a) for a in stmt.value.args):
                continue
            if not self.src.owns_lines(stmt):
                raise Refused("the sys.path line on line %d shares its line with other code"
                              % stmt.lineno)
            out.append(stmt)
        return out

    def _plan_import_switch(self, pkg_dir, model_dir):
        """Builds self.import_rewrites: stmt -> new import text. Returns a list of problems."""
        problems = []
        self.import_rewrites = {}
        old_init = os.path.join(model_dir, "modules", "__init__.py")
        new_exports = exported_names(os.path.join(pkg_dir, "__init__.py")) or set()

        def names_text(names):
            return ", ".join(a.name + (" as " + a.asname if a.asname else "") for a in names)

        for stmt in self.modules_imports:
            if not self.src.owns_lines(stmt):
                problems.append("the import on line %d shares its line with other code" % stmt.lineno)
                continue
            if isinstance(stmt, ast.Import):
                if len(stmt.names) != 1:
                    problems.append("line %d imports several modules in one statement" % stmt.lineno)
                    continue
                a = stmt.names[0]
                sub = self._local_module(a.name)
                if sub is None or sub == "":
                    problems.append("line %d: 'import %s' can't be switched" % (stmt.lineno, a.name))
                    continue
                if a.name.startswith("modules.") and not a.asname:
                    problems.append("line %d: 'import %s' without 'as' binds the name 'modules'"
                                    % (stmt.lineno, a.name))
                    continue
                if "." in sub or not os.path.isfile(os.path.join(pkg_dir, sub + ".py")):
                    problems.append("line %d: %s has no module %s" % (stmt.lineno, PACKAGE, sub))
                    continue
                self.import_rewrites[id(stmt)] = "from %s import %s%s" % (
                    PACKAGE, sub, " as " + a.asname if a.asname else "")
            else:
                sub = self._local_module(stmt.module)
                if sub == "":
                    if [a.name for a in stmt.names] == ["*"]:
                        old = exported_names(old_init)
                        if old is not None and not old <= new_exports:
                            problems.append("%s doesn't export %s" % (
                                PACKAGE, ", ".join(sorted(old - new_exports))))
                    else:
                        for a in stmt.names:
                            if not os.path.isfile(os.path.join(pkg_dir, a.name + ".py")) \
                                    and a.name not in new_exports:
                                problems.append("line %d: %s has no %s" % (stmt.lineno, PACKAGE, a.name))
                    self.import_rewrites[id(stmt)] = "from %s import %s" % (PACKAGE, names_text(stmt.names))
                else:
                    defs = top_level_defs(os.path.join(pkg_dir, sub + ".py"))
                    if defs is None or "." in sub:
                        problems.append("line %d: %s has no module %s" % (stmt.lineno, PACKAGE, sub))
                        continue
                    for a in stmt.names:
                        if a.name != "*" and a.name not in defs:
                            problems.append("line %d: %s.%s has no %s"
                                            % (stmt.lineno, PACKAGE, sub, a.name))
                    self.import_rewrites[id(stmt)] = "from %s.%s import %s" % (
                        PACKAGE, sub, names_text(stmt.names))
        return problems

    # ---- variable binding ------------------------------------------------------------------

    def _call_args(self, call):
        """[(param, expr)] in evaluation order, using the workflow signature for positions."""
        fn = self.workflow.functions[call_name(call)]
        out = []
        for i, a in enumerate(call.args):
            if i >= len(fn.params):
                raise Refused("%s() on line %d has more positional arguments than the workflow "
                              "function" % (call_name(call), call.lineno))
            out.append((fn.params[i], a))
        for k in call.keywords:
            if k.arg not in fn.params:
                raise Refused("%s() on line %d passes %s=, which the workflow function doesn't have"
                              % (call_name(call), call.lineno, k.arg))
            out.append((k.arg, k.value))
        return out

    def _candidate(self, name, key, line, proof, candidates):
        candidates.setdefault(name, []).append((key, line, proof))

    def _bind_variables(self):
        candidates = {}   # name -> [(key, line, proof)]
        self.no_key = {}  # name -> read_gds / read_substrate argument without a settings key

        # (a)/(b) arguments of the workflow calls
        self.call_args = {}
        for stmt, call in self.call_stmts:
            args = self._call_args(call)
            self.call_args[id(call)] = args
            params = [p for p, _ in args]
            if "FDTD" not in params:
                raise Refused("%s() on line %d doesn't pass FDTD" % (call_name(call), call.lineno))
            fdtd = dict(args)["FDTD"]
            if not isinstance(fdtd, ast.Name):
                raise Refused("%s() on line %d passes FDTD as an expression" % (call_name(call), call.lineno))
            for param, expr in args:
                if param != "FDTD" and isinstance(expr, ast.Name):
                    self._candidate(expr.id, param, expr.lineno,
                                    "passed as %s to %s() on line %d"
                                    % (param, call_name(call), call.lineno), candidates)

        # read_gds / read_substrate parameters listed in workflow_signatures.csv
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            fname = call_name(node)
            rows = [r for r in self.signatures if r[0] == fname and r[0] not in WORKFLOW_CALLS]
            if not rows:
                continue
            for i, a in enumerate(node.args):
                row = next((r for r in rows if r[1] == i), None)
                if not isinstance(a, ast.Name):
                    continue
                if row:
                    self._candidate(a.id, row[3], a.lineno, "passed as %s to %s() on line %d"
                                    % (row[2], fname, node.lineno), candidates)
                else:
                    self.no_key.setdefault(a.id, "%s() argument %d" % (fname, i + 1))
            for k in node.keywords:
                row = next((r for r in rows if r[2] == k.arg), None)
                if not isinstance(k.value, ast.Name):
                    continue
                if row:
                    self._candidate(k.value.id, row[3], k.value.lineno,
                                    "passed as %s to %s() on line %d"
                                    % (row[2], fname, node.lineno), candidates)
                else:
                    self.no_key.setdefault(k.value.id, "%s(%s=...)" % (fname, k.arg))

        # use sites that the workflow itself has for these settings
        uses = self._use_site_bindings()
        for name, key, line, proof in uses:
            self._candidate(name, key, line, proof, candidates)
        self._formula = self._prove_formula(candidates)
        if self._formula:
            cpw, lines = self._formula
            self._candidate(cpw, "cells_per_wavelength", lines[1],
                            "max_cellsize formula on lines %d-%d equals the workflow's" % lines,
                            candidates)

        # decide
        self.renames = {}         # name -> key
        key_owner = {}
        for name, entries in sorted(candidates.items()):
            keys = sorted(set(e[0] for e in entries))
            stmt = self.literals.get(name)
            reason = None
            if len(keys) > 1:
                reason = "means different settings (%s)" % ", ".join(keys)
            elif stmt is None:
                continue          # not a literal variable: passed into settings at the call
            elif self.bindings.get(name, 0) != 1:
                reason = "assigned or bound more than once"
            if reason:
                if stmt is not None:
                    self.loose.append({"name": name, "line": stmt.lineno, "reason": reason})
                continue
            key = keys[0]
            if key in key_owner:
                other = key_owner[key]
                self.loose.append({"name": name, "line": stmt.lineno,
                                   "reason": "settings['%s'] is also proven for %s" % (key, other)})
                if other in self.renames:
                    del self.renames[other]
                    self.converted = [c for c in self.converted if c["name"] != other]
                    self.loose.append({"name": other, "line": self.literals[other].lineno,
                                       "reason": "settings['%s'] is also proven for %s" % (key, name)})
                continue
            key_owner[key] = name
            self.renames[name] = key
            self.converted.append({"name": name, "key": key, "line": stmt.lineno,
                                   "proof": entries[0][2]})

        # The formula is only dropped when setupSimulation can rebuild it: fstop and
        # cells_per_wavelength must be settings, assigned before the first setupSimulation call.
        if self._formula:
            cpw = self._formula[0]
            first_setup = min(c.lineno for _, c in self.call_stmts if call_name(c) == "setupSimulation")
            ok = (cpw in self.renames and self._fstop in self.renames
                  and self.literals[cpw].lineno < first_setup
                  and self.literals[self._fstop].lineno < first_setup)
            if not ok:
                self._formula = None
                self.formula_stmts = []
                if self.renames.get(cpw) == "cells_per_wavelength":
                    del self.renames[cpw]
                    self.converted = [c for c in self.converted if c["name"] != cpw]
                    self.loose.append({"name": cpw, "line": self.literals[cpw].lineno,
                                       "reason": "only proven by the max_cellsize formula, which "
                                                 "stays because fstop is not converted or is "
                                                 "assigned after setupSimulation()"})
                    self.loose.sort(key=lambda e: e["line"])

        bound = set(self.renames)
        for name, stmt in sorted(self.literals.items(), key=lambda kv: kv[1].lineno):
            if name in bound or name in candidates:
                continue
            if name in self.no_key:
                reason = ("passed as %s, which has no settings key (file names and layer "
                          "lists stay variables, as in the gds2openEMS examples)" % self.no_key[name])
            else:
                reason = ("not passed to a workflow function, and no workflow expression proves "
                          "its meaning")
            self.loose.append({"name": name, "line": stmt.lineno, "reason": reason})
        self.loose.sort(key=lambda e: e["line"])
        self.converted.sort(key=lambda e: e["line"])

    def _use_site_bindings(self):
        out = []
        np = self.numpy

        def is_const(node, value):
            return isinstance(node, ast.Constant) and node.value == value and \
                type(node.value) is type(value)

        fstart = fstop = None
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            name = call_name(node)
            if name == "openEMS":
                for k in node.keywords:
                    v = k.value
                    if (k.arg == "EndCriteria" and isinstance(v, ast.Call) and np.name(v.func) == "exp"
                            and len(v.args) == 1 and not v.keywords):
                        e = v.args[0]
                        if (isinstance(e, ast.BinOp) and isinstance(e.op, ast.Mult)
                                and isinstance(e.left, ast.BinOp) and isinstance(e.left.op, ast.Div)
                                and isinstance(e.left.left, ast.Name) and is_const(e.left.right, 10)
                                and isinstance(e.right, ast.Call) and np.name(e.right.func) == "log"
                                and len(e.right.args) == 1 and is_const(e.right.args[0], 10)):
                            out.append((e.left.left.id, "energy_limit", node.lineno,
                                        "openEMS(EndCriteria=exp(%s/10*log(10))) on line %d"
                                        % (e.left.left.id, node.lineno)))
            elif name == "SetGaussExcite" and isinstance(node.func, ast.Attribute) \
                    and len(node.args) == 2 and not node.keywords:
                a0, a1 = node.args

                def half(n, op):
                    if (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) and is_const(n.right, 2)
                            and isinstance(n.left, ast.BinOp) and isinstance(n.left.op, op)
                            and isinstance(n.left.left, ast.Name) and isinstance(n.left.right, ast.Name)):
                        return n.left.left.id, n.left.right.id
                    return None
                s = half(a0, ast.Add)
                d = half(a1, ast.Sub)
                if s and d and s[0] == d[1] and s[1] == d[0] and s[0] != s[1]:
                    fstart, fstop = s
                    proof = "SetGaussExcite((%s+%s)/2, (%s-%s)/2) on line %d" % (
                        fstart, fstop, fstop, fstart, node.lineno)
                    out.append((fstart, "fstart", node.lineno, proof))
                    out.append((fstop, "fstop", node.lineno, proof))
            elif name == "SetBoundaryCond" and isinstance(node.func, ast.Attribute) \
                    and len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Name):
                out.append((node.args[0].id, "Boundaries", node.lineno,
                            "SetBoundaryCond(%s) on line %d" % (node.args[0].id, node.lineno)))
        if fstart and fstop:
            for node in ast.walk(self.tree):
                if (isinstance(node, ast.Call) and np.name(node.func) == "linspace"
                        and len(node.args) == 3 and not node.keywords
                        and all(isinstance(a, ast.Name) for a in node.args)
                        and node.args[0].id == fstart and node.args[1].id == fstop):
                    n = node.args[2].id
                    out.append((n, "numfreq", node.lineno, "linspace(%s, %s, %s) on line %d"
                                % (fstart, fstop, n, node.lineno)))
        self._fstop = fstop
        return out

    def _prove_formula(self, candidates):
        """(cells_per_wavelength variable, (line W, line M)) when the model's max_cellsize formula
        equals the workflow's; else None. Also records the statements to drop."""
        self.formula_stmts = []
        if not self._fstop:
            return None
        wf_text = self.workflow.formula_canonical()
        if wf_text is None:
            return None
        setup_calls = [(s, c) for s, c in self.call_stmts if call_name(c) == "setupSimulation"]
        if not setup_calls:
            return None
        names_for = {}
        for _, call in setup_calls:
            args = dict(self.call_args[id(call)])
            for p in ("max_cellsize", "unit", "materials_list"):
                a = args.get(p)
                if not isinstance(a, ast.Name):
                    return None
                if names_for.setdefault(p, a.id) != a.id:
                    return None
        m_name = names_for["max_cellsize"]
        top = {}
        for stmt in self.tree.body:
            if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)):
                top.setdefault(stmt.targets[0].id, []).append(stmt)
        if len(top.get(m_name, [])) != 1 or self.bindings.get(m_name, 0) != 1:
            return None
        m_stmt = top[m_name][0]
        expr = m_stmt.value
        w_stmt = None
        refs = [n.id for n in ast.walk(expr) if isinstance(n, ast.Name)]
        for r in set(refs):
            if r in (names_for["unit"], names_for["materials_list"], self._fstop) or self.numpy.name(
                    ast.Name(id=r, ctx=ast.Load())) is not None:
                continue
            stmts = top.get(r, [])
            if len(stmts) == 1 and self.bindings.get(r, 0) == 1 and not is_literal(stmts[0].value):
                if w_stmt is not None:
                    return None
                w_stmt = stmts[0]
                expr = inline(expr, r, w_stmt.value)
        names = {self._fstop: "fstop", names_for["unit"]: "unit",
                 names_for["materials_list"]: "materials_list"}
        free = []
        try:
            text = canonical(expr, names, self.numpy, free)
        except ValueError:
            return None
        free = sorted(set(free))
        if len(free) != 1:
            return None
        cpw = free[0]
        if text.replace("F(%s)" % cpw, "K(cells_per_wavelength)") != wf_text:
            return None
        stmts = [s for s in (w_stmt, m_stmt) if s is not None]
        lines = (stmts[0].lineno, stmts[-1].end_lineno)
        # The lines are dropped only when max_cellsize just feeds setupSimulation and
        # wavelength_air just max_cellsize; else they stay (reading settings[...]) and
        # setupSimulation computes the same value itself.
        droppable = (self.loads.get(m_name, 0) == len(setup_calls)
                     and (w_stmt is None or self.loads.get(w_stmt.targets[0].id, 0) == 1)
                     and all(self.src.owns_lines(s) for s in stmts)
                     and not any(s.lineno > c.lineno for s in stmts for _, c in setup_calls))
        self.formula_stmts = stmts if droppable else []
        return cpw, lines

    def _check_workflow_reads(self):
        """The workflow's settings branch must read every key the conversion writes, and
        parameters the model doesn't pass must default the same way in both branches."""
        for stmt, call in self.call_stmts:
            fname = call_name(call)
            fn = self.workflow.functions[fname]
            passed = set(p for p, _ in self.call_args[id(call)])
            if self._formula and fname == "setupSimulation":
                passed.discard("max_cellsize")
            for p in passed - {"FDTD"}:
                if p not in fn.reads:
                    raise Refused("%s in %s doesn't read settings['%s'], which the model passes "
                                  "on line %d" % (fname, self.workflow.path, p, call.lineno))
            for p in fn.params:
                if p in passed or p in ("FDTD", "settings") or p not in fn.defaults:
                    continue
                reads = fn.reads.get(p)
                if not reads:
                    continue
                if None in reads:
                    raise Refused("%s needs settings['%s'], but the model doesn't pass %s (line %d)"
                                  % (fname, p, p, call.lineno))
                same = all(ast.dump(d) == ast.dump(fn.defaults[p]) for d in reads)
                if not same and (fname, p) not in EQUIVALENT_DEFAULTS:
                    raise Refused("%s uses a different default for %s in its settings branch"
                                  % (fname, p))
            if self._formula and fname == "setupSimulation":
                for k in ("fstop", "unit", "cells_per_wavelength"):
                    if k not in fn.reads:
                        raise Refused("setupSimulation doesn't read settings['%s']" % k)

    # ---- text edits --------------------------------------------------------------------------

    def _fstring_quote(self):
        """Name node id -> quote to use inside the enclosing f-string."""
        quotes = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.JoinedStr):
                start, _ = self.src.span(node)
                m = re.match(r"[rRfFbBuU]*(['\"])", self.src.text[start:start + 6])
                q = m.group(1) if m else "'"
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Name):
                        quotes[id(inner)] = '"' if q == "'" else "'"
        return quotes

    def build(self):
        src = self.src
        quotes = self._fstring_quote()
        name_edits = []           # (start, end, text)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and node.id in self.renames:
                start, end = src.span(node)
                if src.text[start:end] != node.id:
                    raise Refused("can't locate %s on line %d inside an f-string with Python %d.%d; "
                                  "run the conversion with Python 3.12 or newer"
                                  % (node.id, node.lineno, sys.version_info[0], sys.version_info[1]))
                q = quotes.get(id(node), "'")
                name_edits.append((start, end, "settings[%s%s%s]" % (q, self.renames[node.id], q)))
        name_edits.sort()

        def render(start, end, used):
            out = []
            pos = start
            for a, b, t in name_edits:
                if a >= start and b <= end:
                    out.append(src.text[pos:a])
                    out.append(t)
                    pos = b
                    used.add(a)
            out.append(src.text[pos:end])
            return "".join(out)

        edits = []                # (start, end, text), non-overlapping
        used = set()
        nl = src.newline

        # workflow calls
        for stmt, call in self.call_stmts:
            indent = src.indent_of(stmt)
            s_start, s_end = src.span(stmt)
            lines = []
            arg_spans = [src.span(e) for _, e in self.call_args[id(call)]]
            for c in comments_in(src, s_start, s_end, arg_spans):
                lines.append(c)
            if self.engine and stmt is self.engine_stmt:
                lines.append("settings[%r] = %r" % ("engine", self.engine))
            fdtd = None
            for param, expr in self.call_args[id(call)]:
                if param == "FDTD":
                    fdtd = render(*src.span(expr), used)
                    continue
                if param == "max_cellsize" and self._formula:
                    continue
                if isinstance(expr, ast.Name) and self.renames.get(expr.id) == param:
                    continue      # the variable already is settings[param]
                lines.append("settings[%r] = %s" % (param, render(*src.span(expr), used)))
            func = render(*src.span(call.func), used)
            c_start, c_end = src.span(call)
            lines.append(render(s_start, c_start, used)
                         + "%s(FDTD=%s, settings=settings)" % (func, fdtd)
                         + render(c_end, s_end, used))
            edits.append((s_start, s_end, (nl + indent).join(lines)))
            self.calls.append({"function": call_name(call), "line": stmt.lineno})

        # dropped max_cellsize formula (whole lines)
        for i, stmt in enumerate(self.formula_stmts):
            start = src.line_start(stmt.lineno)
            end = src.line_end(stmt.end_lineno)
            text = (src.indent_of(stmt) + FORMULA_NOTE + nl) if i == len(self.formula_stmts) - 1 else ""
            edits.append((start, end, text))
            self.dropped.append(stmt.lineno)

        # import switch (added after settings = {} is placed: imports are no use of settings)
        import_edits = []
        for stmt in self.modules_imports if self.needs_switch else []:
            start, end = src.span(stmt)
            import_edits.append((start, end, self.import_rewrites[id(stmt)]))
        # sys.path lines for the local modules folder (whole lines)
        for stmt in self.syspath_stmts:
            import_edits.append((src.line_start(stmt.lineno), src.line_end(stmt.end_lineno), ""))
            self.removed.append(stmt.lineno)

        # renamed names outside the replaced statements
        def inside_edit(a):
            return any(s <= a < e for s, e, _ in edits)
        for a, b, t in name_edits:
            if a not in used and not inside_edit(a):
                edits.append((a, b, t))

        # settings = {} before its first use, after the last top-level import if that is earlier
        first_use = None
        touched = [s for s, _, _ in edits]
        for stmt in self.tree.body:
            s, e = src.span(stmt)
            if any(s <= t < max(e, s + 1) for t in touched):
                first_use = stmt
                break
        if first_use is None:
            raise Refused("nothing to convert")
        last_import = None
        for stmt in self.tree.body:
            if stmt.lineno >= first_use.lineno:
                break
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                last_import = stmt
        if last_import is not None and src.owns_lines(last_import):
            pos = src.line_end(last_import.end_lineno)
            tail = src.text[src.line_start(last_import.end_lineno):pos]
            prefix = "" if tail.endswith(("\n", "\r")) else nl
            insert = prefix + nl + "settings = {}" + nl
            self.settings_index = self.tree.body.index(last_import) + 1
        else:
            pos = src.line_start(first_use.lineno)
            insert = "settings = {}" + nl
            self.settings_index = self.tree.body.index(first_use)
        edits.append((pos, pos, insert))
        edits.extend(import_edits)

        edits.sort(key=lambda e: (e[0], e[1]))
        for (a1, b1, _), (a2, b2, _) in zip(edits, edits[1:]):
            if a2 < b1:
                raise Refused("internal error: overlapping edits at offset %d" % a2)
        out = []
        pos = 0
        for a, b, t in edits:
            out.append(src.text[pos:a])
            out.append(t)
            pos = b
        out.append(src.text[pos:])
        return "".join(out)

    # ---- proof ---------------------------------------------------------------------------------

    def expected_tree(self):
        """The intended transformation applied to the original AST."""
        tree = copy.deepcopy(self.tree)
        orig_stmts = {}
        for o, c in zip(ast.walk(self.tree), ast.walk(tree)):
            orig_stmts[id(c)] = o
        renames = self.renames
        assign_targets = set(id(self.literals[n].targets[0]) for n in renames)
        call_ids = set(id(s) for s, _ in self.call_stmts)
        formula_ids = set(id(s) for s in self.formula_stmts)
        formula_ids |= set(id(s) for s in self.syspath_stmts)     # dropped as well
        import_ids = set(id(s) for s in self.modules_imports) if self.needs_switch else set()
        engine, engine_stmt = self.engine, getattr(self, "engine_stmt", None)
        call_info = {id(s): (c, self.call_args[id(c)]) for s, c in self.call_stmts}
        formula = self._formula

        class Rename(ast.NodeTransformer):
            def visit_Name(self, node):
                orig = orig_stmts.get(id(node))
                if node.id in renames:
                    if orig is not None and id(orig) in assign_targets:
                        return settings_ref(renames[node.id], ast.Store())
                    if isinstance(node.ctx, ast.Load):
                        return settings_ref(renames[node.id], ast.Load())
                return node

        def transform_expr(node):
            return Rename().visit(copy.deepcopy(node))

        def rewrite_list(stmts):
            out = []
            for st in stmts:
                orig = orig_stmts[id(st)]
                if id(orig) in formula_ids:
                    continue
                if id(orig) in import_ids:
                    out.extend(ast.parse(self.import_rewrites[id(orig)]).body)
                    continue
                if id(orig) in call_ids:
                    call, args = call_info[id(orig)]
                    if engine and orig is engine_stmt:
                        out.append(ast.parse("settings[%r] = %r" % ("engine", engine)).body[0])
                    fdtd = None
                    for param, expr in args:
                        if param == "FDTD":
                            fdtd = transform_expr(expr)
                            continue
                        if param == "max_cellsize" and formula:
                            continue
                        if isinstance(expr, ast.Name) and renames.get(expr.id) == param:
                            continue
                        a = ast.parse("settings[%r] = 0" % param).body[0]
                        a.value = transform_expr(expr)
                        out.append(a)
                    new_call = ast.parse("f(FDTD=F, settings=settings)", mode="eval").body
                    new_call.func = transform_expr(call.func)
                    new_call.keywords[0].value = fdtd
                    new = transform_expr(orig)
                    if orig.value is call:
                        new.value = new_call
                    else:
                        new.value.args[0] = new_call
                    out.append(new)
                    continue
                for owner, field in stmt_lists(st):
                    setattr(owner, field, rewrite_list(getattr(owner, field)))
                for f, value in ast.iter_fields(st):
                    if f in ("body", "orelse", "finalbody", "handlers", "cases"):
                        continue
                    if isinstance(value, ast.AST):
                        setattr(st, f, Rename().visit(value))
                    elif isinstance(value, list):
                        setattr(st, f, [Rename().visit(v) if isinstance(v, ast.AST) else v
                                        for v in value])
                for h in getattr(st, "handlers", []) or []:
                    if h.type is not None:
                        h.type = Rename().visit(h.type)
                for case in getattr(st, "cases", []) or []:
                    case.pattern = Rename().visit(case.pattern)
                    if case.guard is not None:
                        case.guard = Rename().visit(case.guard)
                out.append(st)
            return out

        # insert settings = {} at the index in the original body, before rewriting shifts it
        body = list(tree.body)
        marker = ast.parse("settings = {}").body[0]
        body.insert(self.settings_index, marker)
        orig_stmts[id(marker)] = marker
        tree.body = rewrite_list(body)
        return tree

    def prove(self, new_text):
        try:
            new_tree = ast.parse(new_text)
        except SyntaxError as e:
            raise Refused("internal error: the converted text doesn't parse (line %s): %s"
                          % (e.lineno, e.msg))
        expected = self.expected_tree()
        if ast.dump(expected) != ast.dump(new_tree):
            raise Refused("internal error: the converted text differs from the intended "
                          "transformation; nothing was written")
        compile(new_text, self.model_path, "exec")


def side_by_side(old_lines, new_lines):
    """Aligned rows for a side-by-side view: equal lines share a row, a changed block pads the
    shorter side with empty rows (l or r = 0). Paired changed lines get the changed character
    spans ("ls" / "rs", [start, end) in each line) only when most of the original line survives
    (the conversion mostly wraps names: margin -> settings['margin']); others are marked whole."""
    rows = []
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            rows.extend({"l": i1 + k + 1, "r": j1 + k + 1} for k in range(i2 - i1))
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            l = i1 + k + 1 if i1 + k < i2 else 0
            r = j1 + k + 1 if j1 + k < j2 else 0
            row = {"l": l, "r": r, "c": True}
            if l and r:
                a, b = old_lines[l - 1], new_lines[r - 1]
                chars = difflib.SequenceMatcher(None, a, b, autojunk=False)
                kept = sum(size for _, _, size in chars.get_matching_blocks())
                if a.strip() and kept >= 0.7 * len(a):
                    ops = [op for op in chars.get_opcodes() if op[0] != "equal"]
                    row["ls"] = [[o[1], o[2]] for o in ops if o[2] > o[1]]
                    row["rs"] = [[o[3], o[4]] for o in ops if o[4] > o[3]]
            rows.append(row)
    return rows


def convert(model, engine=None, package_dir=None, signatures=None):
    """Converts one model in memory: (converter, converted text, report dict)."""
    if sys.version_info < (3, 8):
        raise Refused("Python 3.8 or newer is needed (this is %d.%d)" % sys.version_info[:2])
    conv = Converter(model, SIGNATURES if signatures is None else signatures, package_dir, engine)
    conv.analyse()
    new_text = conv.build()
    conv.prove(new_text)
    name = os.path.basename(conv.model_path)
    diff = "".join(difflib.unified_diff(conv.src.text.splitlines(keepends=True),
                                        new_text.splitlines(keepends=True),
                                        fromfile=name, tofile=os.path.basename(output_path(model))))
    report = {
        "ok": True,
        "model": conv.model_path,
        "workflow": conv.workflow_info,
        "needs_import_switch": conv.needs_switch,
        "removed_syspath_lines": conv.removed,
        "engine": engine,
        "converted": conv.converted,
        "loose": conv.loose,
        "calls": conv.calls,
        "dropped_formula_lines": conv.dropped,
        "diff": diff,
        "original_lines": conv.src.text.splitlines(),
        "converted_lines": new_text.splitlines(),
        "rows": side_by_side(conv.src.text.splitlines(), new_text.splitlines()),
    }
    return conv, new_text, report


def output_path(model):
    """<name>_settings.py next to the model."""
    stem, _ = os.path.splitext(os.path.abspath(model))
    return stem + "_settings.py"


def collect(paths):
    """Model files from the command line: files as given, folders -> their *.py files (not
    recursive), without converted ones (*_settings.py)."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(os.path.join(p, f) for f in sorted(os.listdir(p))
                       if f.endswith(".py") and not f.endswith("_settings.py")
                       and os.path.isfile(os.path.join(p, f)))
        else:
            out.append(p)
    return out


def summary(report):
    """Text summary of one model's conversion."""
    lines = ["== %s" % report["model"]]
    if not report["ok"]:
        lines.append("   not converted: %s" % report["reason"])
        return "\n".join(lines)
    if report["needs_import_switch"]:
        text = "   imports: switched from the local modules folder to %s" % PACKAGE
        if report["removed_syspath_lines"]:
            text += ", sys.path line %s removed" % ", ".join(str(n) for n in report["removed_syspath_lines"])
        lines.append(text)
    keys = ["%s" % c["key"] if c["name"] == c["key"] else "%s -> %s" % (c["name"], c["key"])
            for c in report["converted"]]
    lines.append("   settings[] (%d): %s" % (len(keys), ", ".join(keys) if keys else "none"))
    if report["dropped_formula_lines"]:
        lines.append("   max_cellsize formula removed (lines %s): setupSimulation calculates it"
                     % ", ".join(str(n) for n in report["dropped_formula_lines"]))
    if report["engine"]:
        lines.append("   engine: settings['engine'] = '%s'" % report["engine"])
    for c in report["loose"]:
        lines.append("   kept as variable: %s (line %d), %s" % (c["name"], c["line"], c["reason"]))
    if report.get("written"):
        lines.append("   written: %s" % report["written"])
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="convert2settings",
        description="Convert loose-variable gds2openEMS models to the settings[] syntax and the "
                    "gds2openEMS imports. Each model is written to <name>_settings.py next to it; "
                    "the model itself and existing files are never overwritten.")
    p.add_argument("models", nargs="+", metavar="MODEL",
                   help="model script(s), or folder(s) whose *.py files are converted")
    p.add_argument("--engine", choices=ENGINES,
                   help="set settings['engine'] in the converted model, e.g. gpu for the GPU engine")
    p.add_argument("--dry-run", action="store_true", help="show the changes, write nothing")
    p.add_argument("--json", action="store_true", help="print the full reports as JSON")
    p.add_argument("--package-dir", help=argparse.SUPPRESS)      # for tests: another workflow
    p.add_argument("--signatures", help=argparse.SUPPRESS)       # for tests: a signatures CSV
    args = p.parse_args(argv)
    signatures = read_signatures(args.signatures) if args.signatures else None

    reports = []
    for model in collect(args.models):
        out = output_path(model)
        try:
            if not args.dry_run and os.path.exists(out):
                raise Refused("%s already exists, it is not overwritten" % out)
            conv, new_text, report = convert(model, args.engine, args.package_dir, signatures)
            if not args.dry_run:
                with open(out, "xb") as f:
                    f.write(conv.src.encode(new_text))
                report["written"] = out
        except (Refused, OSError, UnicodeDecodeError) as e:
            report = {"ok": False, "model": os.path.abspath(model), "reason": str(e)}
        reports.append(report)
        if not args.json:
            print(summary(report))
            if args.dry_run and report["ok"]:
                print(report["diff"])

    if args.json:
        json.dump(reports[0] if len(reports) == 1 else reports, sys.stdout, indent=1)
        sys.stdout.write("\n")
    else:
        done = sum(1 for r in reports if r["ok"])
        print("\n%d converted%s, %d not converted" % (done, " (dry run)" if args.dry_run else "",
                                                     len(reports) - done))
    return 0 if all(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
