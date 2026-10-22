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
Import ADS Momentum stackup exports (*.subst + materials.matdb, and *.ltd) into a
stackup XML tree, using the same stackup_writer API the Stackup Editor's other
mutations go through - so an imported stackup is a normal, editable, validated tree
like any loaded/hand-built one.

This is a general-purpose importer: it processes every material/dielectric/layer/via
in the source file uniformly. It carries no process- or vendor-specific assumptions
(no hardcoded layer names, colors, or skip lists) - unlike the older, IHP-SG13G2-specific
momentum_to_xml.py script this replaces the GUI-facing need for.

Both formats describe a physical stack from an open-ended top boundary (Momentum
models this as an unbounded half-space, not a finite material) down to a substrate,
sometimes terminated by a backside ground plane. The target schema needs a finite
top thickness to bound the simulation domain, so air_thickness_um is a required
parameter (the caller is expected to prompt for it) rather than silently guessed. A
backside ground plane (*.subst's <interface groundplane="1">, *.ltd's BOTTOM COVERED)
is modeled as a synthetic Dielectric slab at the very bottom of the stack (see
_GROUND_PLANE_THICKNESS_UM/_GROUND_PLANE_CONDUCTIVITY below) - a Dielectric rather
than a Layer, deliberately: a Layer only produces geometry where a matching GDSII
polygon exists on its layer number, which a full-wafer backside ground plane has no
reason to have in an arbitrary layout, whereas a Dielectric automatically covers the
whole simulation domain, the same way AIR/Substrate/EPI already do.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# __package__ is None/"" when this module was loaded outside the stackup_editor package
# (e.g. stackupEditor.py run directly), so relative import fails - same dual-mode pattern
# used throughout stackupEditor.py for sibling imports.
if __package__ in (None, ""):
  import stackup_writer
else:
  from . import stackup_writer

_UNIT_TO_MICRON = {
    "meter": 1e6,
    "millimeter": 1e3,
    "micron": 1.0,
    "nanometer": 1e-3,
    "mil": 25.4,
    "inch": 25.4e3,
}

_EPSILON_UM = 1e-4

# a backside ground plane has no physical thickness in the source data - modeled as a thin,
# very-high-conductivity Dielectric slab at the bottom of the stack, standing in for a PEC
# boundary condition
_GROUND_PLANE_NAME = "BACKSIDEGND"
_GROUND_PLANE_THICKNESS_UM = 5.0
_GROUND_PLANE_CONDUCTIVITY = 1e10


# -------------------- shared intermediate representation --------------------

@dataclass
class MaterialSpec:
  name: str
  kind: str  # "conductor", "dielectric", "semiconductor", "sheet_resistor"
  permittivity: float = 1.0
  loss_tangent: float = 0.0
  conductivity: float = 0.0
  rs: float = 0.0  # sheet resistance in Ohm/square, only meaningful for kind="sheet_resistor"
  color: str = ""  # hex RGB, no '#'


@dataclass
class DielectricSlab:
  material_name: str
  thickness_um: float


@dataclass
class LayerEntry:
  name: str
  material_name: str
  kind: str  # "metal" or "via"
  gds_layer: str
  zmin: float
  zmax: float


@dataclass
class DerivedLayerEntry:
  name: str
  target_gds_layer: str
  operation: str  # "AND", "OR", "XOR", or "NOT"
  operand_gds_layers: list


@dataclass
class ImportResult:
  tree: ET.ElementTree
  warnings: list = field(default_factory=list)


# -------------------- shared helpers --------------------

def _ground_plane_slab(materials, warnings):
  """Registers the backside-ground-plane Material (if not already present) and returns
     a DielectricSlab for it - see module docstring. Callers insert this at position 0
     of their bottom-to-top slabs list (the very bottom of the stack) once it's otherwise
     complete, and must also account for its thickness when computing metal/via z (both
     parsers do this by starting their z-accumulation at _GROUND_PLANE_THICKNESS_UM
     instead of 0 when a ground plane was detected, rather than shifting positions in an
     already-built list).
  """
  materials.setdefault(_GROUND_PLANE_NAME, MaterialSpec(
      name=_GROUND_PLANE_NAME, kind="conductor", conductivity=_GROUND_PLANE_CONDUCTIVITY))
  warnings.append(
      f"Backside ground plane detected - modeled as a {_GROUND_PLANE_THICKNESS_UM:g}um "
      f"Dielectric '{_GROUND_PLANE_NAME}' (Material Conductivity={_GROUND_PLANE_CONDUCTIVITY:g}) "
      f"at the bottom of the stack; adjust thickness/material as needed.")
  return DielectricSlab(_GROUND_PLANE_NAME, _GROUND_PLANE_THICKNESS_UM)


# a shared naming-convention suffix is stripped once it's common to MORE than this many
# names - not required to be universal, since a handful of materials (e.g. the bulk
# semiconductor materials) often sit outside a fab's per-technology metal/via naming
# convention even when most of the file's names follow it (see SG25H5EPIC_Cu_50Ohmcm.ltd:
# 26 of 28 materials end in "_SG25H5Cu", but EPI_H5/Substrate_H5_50R don't)
_SUFFIX_STRIP_MIN_COUNT = 4


def _find_majority_suffix(names, min_count):
  """Suffix shared by more than min_count of the given names - not necessarily all of
     them, and not an arbitrary character-count match: candidates are constrained to
     start right after a '_' (Momentum's own name-segment delimiter, consistently used
     across every sample seen), so a short trailing digit that's part of a *different*
     name's own token (e.g. "Metal2"'s "2", "SiO2"'s "2") can never be mistaken for the
     start of the real shared suffix - only "_SG25H5Cu" is a candidate for
     "Metal2_SG25H5Cu", never "2_SG25H5Cu". Ties on count prefer the longer (more
     specific) suffix. Returns "" if nothing clears min_count.
  """
  counts = {}
  for name in names:
    start = 0
    while True:
      idx = name.find("_", start)
      if idx == -1:
        break
      suffix = name[idx:]
      if len(suffix) < len(name):  # never propose the whole name as its own suffix
        counts[suffix] = counts.get(suffix, 0) + 1
      start = idx + 1
  if not counts:
    return ""
  best_suffix, best_count = max(counts.items(), key=lambda kv: (kv[1], len(kv[0])))
  return best_suffix if best_count > min_count else ""


def _strip_common_material_suffix(materials, slabs, layers, warnings, derived_layers=None):
  """If a suffix is shared by more than _SUFFIX_STRIP_MIN_COUNT of the file's material,
     Layer, Dielectric, and DerivedLayer names combined, strips it from every name (in
     any of those) that has it - not requiring universal agreement, so a handful of
     names outside the convention (see _SUFFIX_STRIP_MIN_COUNT) don't block cleanup of
     the rest. Layer/Dielectric/DerivedLayer names are stripped unconditionally once
     found (validate_stackup()'s existing name-uniqueness enforcement is relied on
     further downstream - see _dedup_names() - to resolve any collision this creates);
     Material renames are more conservative, since materials have no such dedup safety
     net, so the whole operation is abandoned if it would empty out or collide a
     Material name.

     _GROUND_PLANE_NAME and "AIR" are always excluded, whether they came from the source
     file or were defaulted by this importer: both are boundary/placeholder materials,
     not part of the actual process - Momentum exports name them "AIR"/leave the
     backside plane unnamed even when every real process material carries a shared
     per-technology suffix (confirmed against a real sample file).
  """
  candidate_names = set(materials) - {_GROUND_PLANE_NAME, "AIR"}
  candidate_names |= {l.name for l in layers}
  candidate_names |= {s.material_name for s in slabs}
  candidate_names |= {d.name for d in derived_layers or []}

  suffix = _find_majority_suffix(candidate_names, _SUFFIX_STRIP_MIN_COUNT)
  if not suffix:
    return

  def strip(name):
    return name[:-len(suffix)] if len(name) > len(suffix) and name.endswith(suffix) else name

  material_renames = {name: strip(name) for name in materials
                       if name not in (_GROUND_PLANE_NAME, "AIR") and strip(name) != name}
  if not material_renames:
    return

  final_names = [material_renames.get(name, name) for name in materials]
  if any(not name for name in final_names) or len(set(final_names)) != len(final_names):
    return  # would empty out or collide a Material name - abandon entirely

  for old_name, new_name in material_renames.items():
    spec = materials.pop(old_name)
    spec.name = new_name
    materials[new_name] = spec

  for slab in slabs:
    if slab.material_name in material_renames:
      slab.material_name = material_renames[slab.material_name]

  for layer in layers:
    layer.name = strip(layer.name)
    if layer.material_name in material_renames:
      layer.material_name = material_renames[layer.material_name]

  for derived in derived_layers or []:
    derived.name = strip(derived.name)

  warnings.append(
      f"Stripped common name suffix '{suffix}' (shared by more than "
      f"{_SUFFIX_STRIP_MIN_COUNT} material/layer/dielectric names)")


def _dedup_names(names):
  """Appends _1, _2, ... to any repeated name, first occurrence unchanged - guarantees
     the uniqueness validate_stackup() requires for Dielectric/Layer names, regardless
     of what the source format handed us.
  """
  seen = {}
  result = []
  for name in names:
    if name not in seen:
      seen[name] = 0
      result.append(name)
    else:
      seen[name] += 1
      result.append(f"{name}_{seen[name]}")
  return result


def _same_dielectric_material(name_a, name_b, materials):
  a = materials.get(name_a)
  b = materials.get(name_b)
  if a is None or b is None:
    return name_a == name_b
  return (a.kind == b.kind
          and abs(a.permittivity - b.permittivity) < 1e-9
          and abs(a.loss_tangent - b.loss_tangent) < 1e-9
          and abs(a.conductivity - b.conductivity) < 1e-9)


def _add_material_element(root, spec):
  type_map = {"conductor": "Conductor", "dielectric": "Dielectric",
              "semiconductor": "Semiconductor", "sheet_resistor": "Resistor"}
  attrs = {"Name": spec.name, "Type": type_map[spec.kind]}
  if spec.kind == "sheet_resistor":
    attrs["Rs"] = f"{spec.rs:.6g}"
  else:
    attrs["Permittivity"] = f"{spec.permittivity:.6g}"
    attrs["DielectricLossTangent"] = f"{spec.loss_tangent:.6g}"
    attrs["Conductivity"] = f"{spec.conductivity:.6g}"
  if spec.color:
    attrs["Color"] = spec.color
  stackup_writer.add_material(root, **attrs)


def _build_tree(slabs, layers, materials, warnings, derived_layers=None):
  """The core shared by both formats: everything downstream of "a bottom-to-top list of
     dielectric slabs, all with real positive thickness (including an already-sized top
     AIR slab), plus a list of metal/via Layer entries with absolute Zmin/Zmax already
     resolved in that same bottom-up z=0-at-the-very-bottom frame".
  Args:
      slabs (list of DielectricSlab): bottom-to-top
      layers (list of LayerEntry): zmin/zmax in the same frame as slabs, mutated in place
      materials (dict): name -> MaterialSpec
      warnings (list of str): appended to in place
      derived_layers (list of DerivedLayerEntry or None): only *.ltd's DERIVEDMASK
        sections produce these; *.subst has no equivalent concept
  Returns:
      xml.etree.ElementTree.ElementTree
  """
  # via nudge: a via's raw zmin, as resolved from the source format's own indexing/
  # interface scheme, naturally lands at the BOTTOM of the metal it connects to below
  # (both source formats define it that way) rather than that metal's TOP, where it
  # actually needs to start - shift any via whose zmin coincides with a metal's zmin
  # up by that metal's own thickness.
  # A metal that only shares its zmin with the via by coincidence (e.g. a thick *.ltd
  # EXPAND DOWN metal reaching the via's bottom interface) must not shrink the via to
  # nothing - only nudge while the via keeps a positive height.
  metal_spans = [(l.zmin, l.zmax - l.zmin) for l in layers if l.kind == "metal"]
  for l in layers:
    if l.kind != "via":
      continue
    for metal_zmin, metal_thickness in metal_spans:
      if abs(l.zmin - metal_zmin) < _EPSILON_UM and l.zmin + metal_thickness < l.zmax - _EPSILON_UM:
        l.zmin += metal_thickness
        break

  # merge adjacent dielectric slabs sharing the same material properties - this only
  # changes how the <Dielectrics> section is presented (fewer, combined-thickness
  # entries); it cannot change any Layer's already-resolved absolute z, since summed
  # thickness across a merged run is identical to the sum of its unmerged parts.
  merged = []
  for slab in slabs:
    if merged and _same_dielectric_material(merged[-1].material_name, slab.material_name, materials):
      merged[-1] = DielectricSlab(merged[-1].material_name, merged[-1].thickness_um + slab.thickness_um)
    else:
      merged.append(DielectricSlab(slab.material_name, slab.thickness_um))

  # re-baseline: both source formats have z=0 at the very bottom of the stack; the
  # target schema's convention (matching every hand-curated reference file) is z=0 at
  # the top of the substrate/semiconductor region, with a <Substrate Offset="..."> that
  # shifts the drawn Layer stack up to meet it - so offset = z at the top of the
  # topmost semiconductor slab, walked pre-merge (merging never changes this value).
  offset = 0.0
  z = 0.0
  for slab in slabs:
    zmax = z + slab.thickness_um
    material = materials.get(slab.material_name)
    if material is not None and material.kind == "semiconductor":
      offset = zmax
    z = zmax

  for l in layers:
    l.zmin -= offset
    l.zmax -= offset

  dielectric_names = _dedup_names([s.material_name for s in merged])
  layer_names = _dedup_names([l.name for l in layers])

  tree = stackup_writer.new_stackup_tree()
  root = tree.getroot()

  used_material_names = {s.material_name for s in merged} | {l.material_name for l in layers}
  for name in sorted(used_material_names):
    spec = materials.get(name)
    if spec is None:
      warnings.append(f"Material '{name}' is used but was never defined - substituted with AIR-like defaults")
      spec = MaterialSpec(name=name, kind="dielectric", permittivity=1.0)
    _add_material_element(root, spec)

  # <Dielectrics> must read top-to-bottom; slabs/merged were built bottom-to-top
  for name, slab in reversed(list(zip(dielectric_names, merged))):
    stackup_writer.add_dielectric(root, Name=name, Material=slab.material_name,
                                   Thickness=f"{slab.thickness_um:.4f}")

  if offset:
    stackup_writer.set_substrate_offset(root, f"{offset:.4f}")

  for name, l in zip(layer_names, layers):
    material = materials.get(l.material_name)
    is_sheet = material is not None and material.kind == "sheet_resistor"
    zmin = l.zmin
    zmax = zmin if is_sheet else l.zmax
    layer_type = "sheet" if is_sheet else ("via" if l.kind == "via" else "conductor")
    stackup_writer.add_layer(root, Name=name, Type=layer_type, Material=l.material_name,
                              Zmin=f"{zmin:.4f}", Zmax=f"{zmax:.4f}", Layer=l.gds_layer)

  derived_names = _dedup_names([d.name for d in derived_layers]) if derived_layers else []
  for name, derived in zip(derived_names, derived_layers or []):
    el = stackup_writer.add_derived_layer(root, Name=name, Layer=derived.target_gds_layer,
                                           Operation=derived.operation)
    stackup_writer.set_operands(el, derived.operand_gds_layers)

  errors = stackup_writer.validate_stackup(root)
  if errors:
    raise ValueError("Imported stackup failed validation:\n" + "\n".join(f"- {e}" for e in errors))

  return tree


# -------------------- materials.matdb (*.subst companion) --------------------

def _parse_matdb(matdb_path):
  materials = {}
  warnings = []
  root = ET.parse(matdb_path).getroot()

  for el in root.iter("Conductor"):
    name = el.get("name")
    real = el.get("real") or ""
    parts = real.split()
    try:
      value = float(parts[0]) if parts else 0.0
    except ValueError:
      value = 0.0
      warnings.append(f"Conductor '{name}': could not parse conductivity value '{real}', using 0")
    if "Ohm/Sq" in real:
      materials[name] = MaterialSpec(name=name, kind="sheet_resistor", rs=value)
    else:
      if "Siemens/m" not in real:
        warnings.append(f"Conductor '{name}': unrecognized conductivity unit in '{real}', assuming Siemens/m")
      materials[name] = MaterialSpec(name=name, kind="conductor", conductivity=value)

  for el in root.iter("Dielectric"):
    name = el.get("name")
    er = el.get("er_real")
    tand = el.get("er_loss")
    materials[name] = MaterialSpec(
        name=name, kind="dielectric",
        permittivity=float(er) if er not in (None, "") else 1.0,
        loss_tangent=float(tand) if tand not in (None, "") else 0.0)

  for el in root.iter("Semiconductor"):
    name = el.get("name")
    er = el.get("er_real")
    resistivity = el.get("resistivity") or ""
    try:
      resistivity_value = float(resistivity.split()[0]) if resistivity else None
    except (ValueError, IndexError):
      resistivity_value = None
      warnings.append(f"Semiconductor '{name}': could not parse resistivity '{resistivity}', using 0 S/m")
    conductivity = (1.0 / (resistivity_value * 0.01)) if resistivity_value else 0.0
    materials[name] = MaterialSpec(
        name=name, kind="semiconductor",
        permittivity=float(er) if er not in (None, "") else 1.0,
        conductivity=conductivity)

  materials.setdefault("AIR", MaterialSpec(name="AIR", kind="dielectric", permittivity=1.0))

  return materials, warnings


# -------------------- *.subst --------------------

def _thickness_um(value_str, unit_str, warnings, context):
  if unit_str and unit_str not in _UNIT_TO_MICRON:
    warnings.append(f"{context}: unrecognized unit '{unit_str}', assuming micron")
  factor = _UNIT_TO_MICRON.get(unit_str, 1.0)
  if value_str in (None, ""):
    return 0.0
  return float(value_str) * factor


def _parse_subst(subst_path, materials, air_thickness_um, warnings):
  root = ET.parse(subst_path).getroot()

  slab_materials = []
  slab_thickness = []
  for el in root.iter("material"):
    name = el.get("materialname")
    if name not in materials:
      warnings.append(f"Dielectric slab material '{name}' not found in materials.matdb, skipped")
      continue
    thickness = _thickness_um(el.get("thick"), el.get("thickunit"), warnings, f"Dielectric slab '{name}'")
    slab_materials.append(name)
    slab_thickness.append(thickness)

  groundplane_detected = any(el.get("groundplane") == "1" for el in root.iter("interface"))

  substrates_el = root.find("substrates")
  if substrates_el is not None and len(substrates_el) > 0:
    warnings.append("<substrates> section is non-empty and was not imported (unsupported).")

  if not slab_thickness:
    raise ValueError("No usable dielectric slabs found in *.subst file")

  # the topmost (last, file-order) slab with ~zero declared thickness is Momentum's
  # open/unbounded top boundary - give it the prompted thickness. If the file doesn't
  # have one (unusual, but not impossible), append a fresh AIR slab on top instead.
  if slab_thickness[-1] < _EPSILON_UM:
    slab_thickness[-1] = air_thickness_um
  else:
    materials.setdefault("AIR", MaterialSpec(name="AIR", kind="dielectric", permittivity=1.0))
    slab_materials.append("AIR")
    slab_thickness.append(air_thickness_um)

  # expand="1": a metal that doesn't fit inside its normally-enclosing slab grows that
  # slab's thickness to fit it - must happen before interface positions are computed
  for el in root.iter("layer"):
    try:
      index = int(el.get("index"))
    except (TypeError, ValueError):
      continue
    thickness = _thickness_um(el.get("thick"), el.get("thickunit"), warnings,
                               f"Layer '{el.get('materialname')}'")
    if el.get("expand") == "1":
      target_index = index + 1 if thickness > 0 else index
      if 0 <= target_index < len(slab_thickness):
        slab_thickness[target_index] += abs(thickness)

  # interface_pos[i] = cumulative z at the TOP of slab i (after its own thickness is
  # added) - this is where a <layer index="i">/<via index1="i"> attaches. A <layer
  # index="i"> physically sits right above dielectric slab i (e.g. index="2" - EPI in
  # the sample stack - is where Activ, the first metal above EPI, attaches). A detected
  # ground plane sits below slab index 0 without being part of the file's own index
  # numbering (inserted into the *output* slabs list separately, below) - starting the
  # accumulation at its thickness instead of 0 shifts every index-based z by the same
  # amount this slab_thickness list is silently missing it, without disturbing any
  # <layer index="N">/<via index1="N"> value, which refer to *this* array's positions.
  interface_pos = []
  z = _GROUND_PLANE_THICKNESS_UM if groundplane_detected else 0.0
  for t in slab_thickness:
    z += t
    interface_pos.append(z)

  layers = []
  for el in root.iter("layer"):
    name = el.get("materialname")
    if name not in materials:
      warnings.append(f"Layer material '{name}' not found in materials.matdb, skipped")
      continue
    try:
      index = int(el.get("index"))
    except (TypeError, ValueError):
      warnings.append(f"Layer '{name}': missing/invalid index, skipped")
      continue
    thickness = _thickness_um(el.get("thick"), el.get("thickunit"), warnings, f"Layer '{name}'")
    # a negative thick means this metal grows DOWN from its interface (into the slab
    # below, index N) instead of UP (into the slab above, index N+1) - same convention
    # "expand"'s target-slab choice already relies on, just for a plain slab's position
    # rather than which one to grow (see the target_index branch above). Either way the
    # interface itself is one edge of the metal, never its Zmin specifically - min/max
    # the two candidate z's rather than assuming the sign, so Zmax is always > Zmin
    # regardless of growth direction.
    interface_z = interface_pos[index]
    other_z = interface_z + thickness
    zmin, zmax = min(interface_z, other_z), max(interface_z, other_z)
    gds_layer = el.get("layer")
    layers.append(LayerEntry(name=name, material_name=name, kind="metal",
                              gds_layer=gds_layer, zmin=zmin, zmax=zmax))
    # sheet="1" is a Momentum solver hint ("treat as electrically thin"), not a
    # geometric zero-thickness declaration - this layer keeps its real thickness above.

  for el in root.iter("via"):
    name = el.get("materialname")
    if name not in materials:
      warnings.append(f"Via material '{name}' not found in materials.matdb, skipped")
      continue
    try:
      index1 = int(el.get("index1"))
      index2 = int(el.get("index2"))
    except (TypeError, ValueError):
      warnings.append(f"Via '{name}': missing/invalid index1/index2, skipped")
      continue
    gds_layer = el.get("layer")
    layers.append(LayerEntry(name=name, material_name=name, kind="via", gds_layer=gds_layer,
                              zmin=interface_pos[index1], zmax=interface_pos[index2]))

  slabs = [DielectricSlab(m, t) for m, t in zip(slab_materials, slab_thickness) if t > _EPSILON_UM]
  if groundplane_detected:
    slabs.insert(0, _ground_plane_slab(materials, warnings))

  return slabs, layers


def import_subst(subst_path, matdb_path, air_thickness_um):
  """Import an ADS Momentum *.subst + materials.matdb pair into a stackup tree.
  Args:
      subst_path (string): path to the *.subst file
      matdb_path (string): path to the companion materials.matdb file
      air_thickness_um (float): thickness to use for the open-boundary AIR region
        above the stack (the source file leaves this undefined)
  Returns:
      ImportResult
  """
  materials, warnings = _parse_matdb(matdb_path)
  slabs, layers = _parse_subst(subst_path, materials, air_thickness_um, warnings)
  _strip_common_material_suffix(materials, slabs, layers, warnings)
  tree = _build_tree(slabs, layers, materials, warnings)
  return ImportResult(tree=tree, warnings=warnings)


# -------------------- *.ltd --------------------

_KV_RE = re.compile(r'(\w+)\s*=\s*("[^"]*"|\S+)')
_MASK_BRACE_RE = re.compile(r'MASK\s*=\s*\{([^}]*)\}')


def _ltd_kv(line):
  """Parses "KEY=value" / "KEY = value" / "KEY="quoted value"" tokens from a *.ltd line
     into a dict keyed by UPPERCASED attribute name. Real exports vary both in whether
     '=' has surrounding whitespace and in attribute name case (seen "Name="/"NAME=" for
     the very same attribute in two real files from the same PDK, exported by different
     ADS versions) - lookups here must be case-insensitive to be reliable.
  """
  return {key.upper(): value.strip('"') for key, value in _KV_RE.findall(line)}


# keywords that start a new statement in each section - any other line in these sections
# is a continuation of the previous statement (a long MATERIAL/MASK/LAYER line wrapped
# onto the next line, e.g. "IMAG_PERMEABILITY=0", "OPERATION=...", or a MASK's own
# "MASK_PROPERTIES = {...}" line) and is joined back onto it
_LTD_STATEMENT_KEYWORDS = {
    "MATERIAL": {"MATERIAL"},
    "OPERATION": {"OPERATION"},
    "MASK": {"MASK"},
    "DERIVEDMASK": {"DERIVEDMASK"},
    "STACK": {"TOP", "INTERFACE", "LAYER", "BOTTOM"},
}


def _split_ltd_sections(text):
  # END_<section> is not always on a line of its own - seen trailing the last statement
  # ("OPERATION OperationTSV_Virtual_VIA1 DRILL END_OPERATION")
  text = re.sub(r'\s+(END_\w+)\b', r'\n\1', text)
  sections = {}
  current = None
  buf = []
  for raw_line in text.splitlines():
    line = raw_line.strip()
    if not line:
      continue
    m = re.match(r'^BEGIN_(\w+)$', line)
    if m:
      current = m.group(1)
      buf = []
      continue
    m = re.match(r'^END_(\w+)$', line)
    if m:
      sections[current] = buf
      current = None
      continue
    if current:
      keywords = _LTD_STATEMENT_KEYWORDS.get(current)
      if keywords and buf and line.split()[0] not in keywords:
        buf[-1] = buf[-1] + " " + line
      else:
        buf.append(line)
  return sections


def _resolve_mask_token(token, masks, masks_by_layer):
  """A MASK={...} entry's members (in BEGIN_STACK or a DERIVEDMASK definition) can be
     given as mask Names or as bare GDS layer numbers - both seen in real exports of the
     same PDK from different ADS versions. Tries a Name match first, falls back to a
     layer-number match.
  Returns:
      dict or None: the resolved mask's own dict from `masks`, or None if neither matches
  """
  if token in masks:
    return masks[token]
  return masks_by_layer.get(token)


def _parse_ltd(ltd_path, air_thickness_um, warnings):
  with open(ltd_path, encoding="utf-8") as f:
    text = f.read()
  sections = _split_ltd_sections(text)

  for line in sections.get("UNITS", []):
    if line.startswith("DISTANCE=") and line.split("=", 1)[1].strip().upper() != "METRE":
      warnings.append(f"*.ltd declares {line} - this importer assumes METRE, lengths may be wrong")
    if line.startswith("RESISTIVITY=") and line.split("=", 1)[1].strip().upper() != "OHM.CM":
      warnings.append(f"*.ltd declares {line} - this importer assumes OHM.CM, semiconductor conductivity may be wrong")

  materials = {}
  # RESISTANCE= (Ohm/Sq) can't be classified from the MATERIAL line alone: a real GPDK
  # export uses it both for genuine zero-thickness sheet resistors AND for ordinary
  # conductors that still get real 3D thickness via an INTRUDE/EXPAND operation (e.g. a
  # "Poly" resistor layer vs. a "Metal1" that just happens to express its conductivity as
  # a sheet-resistance-equivalent instead of CONDUCTIVITY). Deferred to a second pass
  # below, once every material's actual Layer thickness is known.
  pending_rs = {}
  for line in sections.get("MATERIAL", []):
    tokens = line.split()
    if len(tokens) < 2:
      continue
    name = tokens[1]
    kv = _ltd_kv(line)
    conductivity = kv.get("CONDUCTIVITY")
    resistance = kv.get("RESISTANCE")
    permittivity = kv.get("PERMITTIVITY")
    resistivity = kv.get("RESISTIVITY")
    loss_tangent = kv.get("LOSSTANGENT")
    if resistance is not None:
      pending_rs[name] = float(resistance)
      materials[name] = MaterialSpec(name=name, kind="conductor", conductivity=0.0)
    elif conductivity is not None:
      materials[name] = MaterialSpec(name=name, kind="conductor", conductivity=float(conductivity))
    elif permittivity is not None and resistivity is not None:
      materials[name] = MaterialSpec(name=name, kind="semiconductor",
                                      permittivity=float(permittivity),
                                      conductivity=1.0 / (float(resistivity) * 0.01))
    elif permittivity is not None:
      materials[name] = MaterialSpec(name=name, kind="dielectric",
                                      permittivity=float(permittivity),
                                      loss_tangent=float(loss_tangent) if loss_tangent is not None else 0.0)
    else:
      warnings.append(f"Material '{name}': could not classify from '{line}', skipped")
  materials.setdefault("AIR", MaterialSpec(name="AIR", kind="dielectric", permittivity=1.0))

  operations = {}
  for line in sections.get("OPERATION", []):
    tokens = line.split()
    if len(tokens) < 2:
      continue
    name = tokens[1]
    kv = _ltd_kv(line)
    if "DRILL" in tokens:
      operations[name] = ("via", None)
    elif "INTRUDE" in kv or "EXPAND" in kv:
      # both give a thickness in meters; DOWN (vs. the default UP) means this metal
      # grows downward from its interface into the slab below - same concept *.subst
      # expresses via a negative thick value, here via an explicit direction token.
      # INTRUDE places the metal inside the existing slab; EXPAND makes that slab
      # thicker by the metal thickness (same as *.subst's expand="1"), handled when
      # the stack is walked below.
      magnitude_um = float(kv.get("INTRUDE") or kv.get("EXPAND")) * 1e6
      thickness_um = -magnitude_um if "DOWN" in tokens else magnitude_um
      operations[name] = ("metal", thickness_um, "EXPAND" in kv)
    elif "SHEET" in tokens:
      operations[name] = ("sheet", None)
    elif "WALL" in tokens:
      operations[name] = ("wall", None)
    else:
      warnings.append(f"Operation '{name}': could not classify from '{line}'")

  masks = {}
  masks_by_layer = {}
  for line in sections.get("MASK", []):
    tokens = line.split()
    if len(tokens) < 2:
      continue
    gds_layer = tokens[1]
    kv = _ltd_kv(line)
    name = kv.get("NAME")
    if name is None:
      continue
    masks[name] = {
        "name": name,
        "gds_layer": gds_layer,
        "material": kv.get("MATERIAL"),
        "operation": kv.get("OPERATION"),
        "color": kv.get("COLOR", ""),
        "derivedmask": kv.get("DERIVEDMASK"),
    }
    masks_by_layer[gds_layer] = masks[name]

  derived_masks = {}
  for line in sections.get("DERIVEDMASK", []):
    tokens = line.split()
    if len(tokens) < 2:
      continue
    name = tokens[1]
    kv = _ltd_kv(line)
    operator = kv.get("OPERATOR")
    mask_match = _MASK_BRACE_RE.search(line)
    operands = mask_match.group(1).split() if mask_match else []
    derived_masks[name] = (operator, operands)

  # build <DerivedLayer> entries: one per BEGIN_MASK entry that references a
  # BEGIN_DERIVEDMASK definition via DERIVEDMASK=... - the mask's own gds_layer is the
  # DerivedLayer's target Layer number; its DERIVEDMASK's OPERATOR/MASK={...} give the
  # Operation and Operands (each operand resolved the same Name-or-layer-number way as
  # any other MASK={...} reference). The mask itself also gets a normal <Layer> entry
  # further below (it's still placed in BEGIN_STACK like any other via/metal) - nothing
  # special needed for that here.
  derived_layers = []
  for mask_name, mask in masks.items():
    dm_name = mask["derivedmask"]
    if not dm_name:
      continue
    dm = derived_masks.get(dm_name)
    if dm is None:
      warnings.append(f"Mask '{mask_name}' references DERIVEDMASK '{dm_name}' which is not "
                       f"defined in BEGIN_DERIVEDMASK, skipped")
      continue
    operator, operand_tokens = dm
    if operator not in ("AND", "OR", "XOR", "NOT"):
      warnings.append(f"DerivedMask '{dm_name}': unsupported OPERATOR '{operator}', skipped")
      continue
    operand_layers = []
    unresolved = False
    for token in operand_tokens:
      operand_mask = _resolve_mask_token(token, masks, masks_by_layer)
      if operand_mask is None:
        warnings.append(f"DerivedMask '{dm_name}': operand '{token}' matches no mask Name "
                         f"or GDS layer number, skipped")
        unresolved = True
        break
      operand_layers.append(operand_mask["gds_layer"])
    if not unresolved:
      derived_layers.append(DerivedLayerEntry(name=mask_name, target_gds_layer=mask["gds_layer"],
                                               operation=operator, operand_gds_layers=operand_layers))

  stack_lines = sections.get("STACK", [])
  slabs = []
  # accumulated by mask name rather than appended directly to `layers`: the same via
  # (or, in principle, metal) mask can be attached to more than one LAYER/INTERFACE
  # line - e.g. a via passing through two adjacent dielectric segments with a
  # different metal's INTERFACE sandwiched in between (TopVia1 in the sample stack,
  # spanning both the SubstrateLayer8/equivalent_for_MIM and SubstrateLayer9/SiO2
  # segments around the MIM plate) - such occurrences must union into one Layer
  # spanning from the lowest zmin to the highest zmax seen, not become separate
  # same-named entries.
  spans = {}  # mask name -> [material_name, kind, gds_layer, zmin, zmax]
  z = 0.0
  groundplane_detected = False
  bottom_state = None

  # EXPAND metals make the dielectric LAYER next to their INTERFACE thicker (DOWN: the
  # LAYER below, UP: the one above) - by the thickest such metal on that interface, not
  # the sum (ADS shows TFR 0.05um + MET1 1um EXPAND DOWN on one interface as +1um). A
  # LAYER can grow from both sides (metal EXPAND UP below it, another EXPAND DOWN above
  # it), which adds up. Must be known before the bottom-up walk reaches that LAYER, so
  # collected up front: (line index in file order, top-to-bottom; +1 DOWN / -1 UP) ->
  # extra thickness in um
  expand_um = {}
  for idx, line in enumerate(stack_lines):
    if line.split()[0] != "INTERFACE":
      continue
    mask_match = _MASK_BRACE_RE.search(line)
    for token in mask_match.group(1).split() if mask_match else []:
      mask = _resolve_mask_token(token, masks, masks_by_layer)
      op = operations.get(mask["operation"]) if mask else None
      if op is None or op[0] != "metal" or not op[2]:
        continue
      side = 1 if op[1] < 0 else -1
      target = idx + side
      if 0 <= target < len(stack_lines) and stack_lines[target].split()[0] == "LAYER":
        expand_um[(target, side)] = max(expand_um.get((target, side), 0.0), abs(op[1]))
      else:
        warnings.append(f"Mask '{mask['name']}' uses EXPAND but has no dielectric LAYER on that "
                         f"side of its INTERFACE - placed without growing any layer")

  for idx in reversed(range(len(stack_lines))):
    line = stack_lines[idx]
    tokens = line.split()
    if not tokens:
      continue
    keyword = tokens[0]
    kv = _ltd_kv(line)

    if keyword == "BOTTOM":
      # BOTTOM is always the first line seen here (it's the last line in the file, and
      # this loop walks in reverse) - z is still untouched at 0.0, so starting it at the
      # ground plane's thickness instead shifts every subsequent slab/metal/via z by the
      # same amount the plane itself will occupy below them
      bottom_state = tokens[1].upper() if len(tokens) > 1 else ""
      if bottom_state == "COVERED":
        groundplane_detected = True
        z = _GROUND_PLANE_THICKNESS_UM
      continue

    if keyword == "TOP":
      state = tokens[1].upper() if len(tokens) > 1 else ""
      top_material = kv.get("MATERIAL", "AIR")
      if state == "OPEN":
        materials.setdefault(top_material, MaterialSpec(name=top_material, kind="dielectric", permittivity=1.0))
        slabs.append(DielectricSlab(top_material, air_thickness_um))
      elif state == "COVERED":
        warnings.append(
            "Top boundary (TOP COVERED) detected - has no GDSII layer number and was not "
            "modeled; add manually if needed.")
      continue

    if keyword == "LAYER":
      material_name = kv.get("MATERIAL")
      height_m = kv.get("HEIGHT")
      if material_name not in materials:
        warnings.append(f"Dielectric slab material '{material_name}' not found, skipped")
        continue
      thickness_um = ((float(height_m) * 1e6 if height_m else 0.0)
                      + expand_um.get((idx, 1), 0.0) + expand_um.get((idx, -1), 0.0))
      zmin = z
      z += thickness_um
      slabs.append(DielectricSlab(material_name, thickness_um))

      mask_match = _MASK_BRACE_RE.search(line)
      if mask_match:
        for token in mask_match.group(1).split():
          mask = _resolve_mask_token(token, masks, masks_by_layer)
          if mask is None:
            warnings.append(f"Mask '{token}' referenced in stack but not defined in BEGIN_MASK, skipped")
            continue
          via_mask_name = mask["name"]
          op = operations.get(mask["operation"])
          if op is None or op[0] != "via":
            warnings.append(f"Mask '{via_mask_name}' is attached to a dielectric LAYER line but its "
                             f"operation isn't DRILL - expected a via, skipped")
            continue
          mat_name = mask["material"]
          if mat_name not in materials:
            warnings.append(f"Via material '{mat_name}' not found, skipped")
            continue
          existing = spans.get(via_mask_name)
          if existing is None:
            spans[via_mask_name] = [mat_name, "via", mask["gds_layer"], zmin, z]
          else:
            existing[3] = min(existing[3], zmin)
            existing[4] = max(existing[4], z)
      continue

    if keyword == "INTERFACE":
      # SHIELD=... is an alternative way (seen in a real export, paired with "BOTTOM
      # OPEN" instead of "BOTTOM COVERED") to mark a backside ground plane, positioned
      # at a specific INTERFACE rather than as the stack's own bottom boundary. Only
      # treated as equivalent to a covered bottom when it's genuinely at (or extremely
      # near) the true bottom of the stack (z still ~0 at this point in the bottom-up
      # walk) - a mid-stack shield has no verified real-world example to model
      # correctly against, so it's surfaced as a warning instead of guessed at.
      shield = kv.get("SHIELD")
      if shield:
        if z < _EPSILON_UM:
          groundplane_detected = True
        else:
          warnings.append(
              f"Shield/ground plane (SHIELD={shield}) detected mid-stack (not at the "
              f"bottom) - has no GDSII layer number and was not modeled; add manually if needed.")
        continue

      mask_match = _MASK_BRACE_RE.search(line)
      if not mask_match:
        continue
      for token in mask_match.group(1).split():
        mask = _resolve_mask_token(token, masks, masks_by_layer)
        if mask is None:
          warnings.append(f"Mask '{token}' referenced in stack but not defined in BEGIN_MASK, skipped")
          continue
        metal_mask_name = mask["name"]
        op = operations.get(mask["operation"])
        if op is None or op[0] == "via":
          warnings.append(f"Mask '{metal_mask_name}' is attached to an INTERFACE line but its "
                           f"operation is DRILL - expected a metal, skipped")
          continue
        if op[0] in ("sheet", "wall"):
          warnings.append(f"Mask '{metal_mask_name}' uses a {op[0].upper()} operation with no "
                           f"thickness defined - skipped, add manually if needed")
          continue
        mat_name = mask["material"]
        if mat_name not in materials:
          warnings.append(f"Layer material '{mat_name}' not found, skipped")
          continue
        if mask["color"]:
          materials[mat_name].color = mask["color"]
        thickness_um = op[1]
        existing = spans.get(metal_mask_name)
        metal_zmin, metal_zmax = min(z, z + thickness_um), max(z, z + thickness_um)
        if existing is None:
          spans[metal_mask_name] = [mat_name, "metal", mask["gds_layer"], metal_zmin, metal_zmax]
        else:
          existing[3] = min(existing[3], metal_zmin)
          existing[4] = max(existing[4], metal_zmax)
      continue

  if not slabs:
    raise ValueError("No usable dielectric slabs found in *.ltd file")

  if bottom_state == "OPEN" and not groundplane_detected:
    warnings.append("Bottom boundary (BOTTOM OPEN) detected - open/unbounded and not modeled; "
                     "add a backside ground or substrate manually if needed.")

  layers = [LayerEntry(name=name, material_name=mat_name, kind=kind, gds_layer=gds_layer, zmin=zmin, zmax=zmax)
            for name, (mat_name, kind, gds_layer, zmin, zmax) in spans.items()]

  # resolve deferred RESISTANCE=-only materials now that every Layer's real thickness is
  # known: sheet-resistor only if every use of that material is genuinely zero-thickness,
  # otherwise treated as a normal conductor with an equivalent bulk conductivity computed
  # from Rs and the first non-zero thickness found (conductivity = 1/(Rs * thickness_m)) -
  # see the note where pending_rs is populated above.
  for name, rs in pending_rs.items():
    uses = [l for l in layers if l.material_name == name]
    nonzero = next((l for l in uses if (l.zmax - l.zmin) > _EPSILON_UM), None)
    if nonzero is not None:
      thickness_m = (nonzero.zmax - nonzero.zmin) * 1e-6
      materials[name].conductivity = 1.0 / (rs * thickness_m)
    else:
      materials[name].kind = "sheet_resistor"
      materials[name].rs = rs

  # slabs were built while walking the file in reverse (bottom-to-top), matching
  # _build_tree's expected bottom-to-top input order - the ground plane, if any,
  # belongs at the very start of that order (the true bottom of the stack)
  if groundplane_detected:
    slabs.insert(0, _ground_plane_slab(materials, warnings))

  return slabs, layers, materials, derived_layers


def import_ltd(ltd_path, air_thickness_um):
  """Import an ADS Momentum *.ltd file into a stackup tree.
  Args:
      ltd_path (string): path to the *.ltd file
      air_thickness_um (float): thickness to use for the open-boundary AIR region
        above the stack (the source file leaves this undefined)
  Returns:
      ImportResult
  """
  warnings = []
  slabs, layers, materials, derived_layers = _parse_ltd(ltd_path, air_thickness_um, warnings)
  _strip_common_material_suffix(materials, slabs, layers, warnings, derived_layers)
  tree = _build_tree(slabs, layers, materials, warnings, derived_layers)
  return ImportResult(tree=tree, warnings=warnings)
