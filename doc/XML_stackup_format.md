# Stackup XML Format

This document describes the XML file format read by `util_stackup_reader.read_substrate()`.
It defines the process stackup used to build a 3D simulation model from GDSII: materials,
the dielectric stack, the drawn metal/via layers and their GDSII layer numbers, optional
derived (computed) layers, and optional thermal-conductivity tables.

Reference files in this repo: [`SG13G2_200um.xml`](../workflow/SG13G2_200um.xml) (basic
stackup) and [`SG13G2_with_resistors_200um.xml`](../more_examples/resistors_sg13g2/SG13G2_with_resistors_200um.xml)
(adds resistor materials and derived-layer examples using `AND`/`OR`/`NOT`).

## Top-level structure

```xml
<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<Stackup schemaVersion="2.0">
  <Materials>
    ...
  </Materials>
  <ELayers LengthUnit="um">
    <Dielectrics>
      ...
    </Dielectrics>
    <Layers>
      ...
    </Layers>
    <DerivedLayers>       <!-- optional -->
      ...
    </DerivedLayers>
  </ELayers>
  <Tables>                 <!-- optional -->
    ...
  </Tables>
</Stackup>
```

`schemaVersion` doesn't change how the reader parses a file (no attribute's meaning branches
on it) — but `read_substrate()` does print a warning if a file declares a `schemaVersion`
newer than `util_stackup_reader.SUPPORTED_SCHEMA_VERSION` (currently `"3.0"`), since such a
file may use attributes this version of the reader doesn't know about yet.

## `<Materials>`

One `<Material>` element per material, referenced by name from `<Dielectric>` and `<Layer>`
elements later in the file.

> **Note:** `Density`, `ThermalConductivity`, and `ThermalConductivityTable` are **not used by
> S-parameter simulation**. They are only read when this XML file is used in a thermal
> simulation flow — leaving them at their defaults (or omitting them) has no effect on EM
> simulation results.

| Attribute                 | Required | Default | Description |
|----------------------------|----------|---------|--------------|
| `Name`                     | yes      | —       | Material name, referenced elsewhere as `Material="..."`. |
| `Type`                     | yes      | —       | `Conductor`, `Dielectric`, `Semiconductor`, or `Resistor`. |
| `Permittivity`              | no       | `1`     | Relative permittivity (εr). |
| `DielectricLossTangent`     | no       | `0`     | Loss tangent. |
| `Conductivity`               | no       | `0`     | Conductivity in S/m. Used for `Conductor`/`Semiconductor` materials. |
| `Rs`                        | no       | `0`     | Sheet resistance in Ω/square. Used for `Resistor` materials (paired with a zero-thickness `Type="sheet"` layer). |
| `Density`                   | no       | `1`     | Mass density, used by thermal simulation setup. |
| `ThermalConductivity`        | no       | `0`     | Constant thermal conductivity, used by thermal simulation setup. |
| `ThermalConductivityTable`   | no       | —       | Name of a `<Table>` (see [Tables](#tables-thermal-conductivity) below) to use instead of a constant value, for temperature-dependent conductivity. |
| `Color`                     | no       | —       | Hex RGB color (no `#`), used for 3D preview / GUI display. |

> **Built-in default `"AIR"`:** if the file has no `<Material Name="AIR">` entry, one is added
> automatically (`Type="Dielectric" Permittivity="1.0" DielectricLossTangent="0.0"
> Conductivity="0" Color="d0d0d0"` — the same values used across the example stackups in this
> repo), so `Material="AIR"` just works on a `<Dielectric>`/`<Layer>` without declaring it
> explicitly. Defining your own `<Material Name="AIR">` overrides this default.

```xml
<Materials>
  <Material Name="Metal1" Type="Conductor" Permittivity="1" DielectricLossTangent="0"
            Conductivity="21640000.0" Color="39bfff"/>
  <Material Name="SiO2" Type="Dielectric" Permittivity="4.1" DielectricLossTangent="0.0"
            Conductivity="0" Color="fffcad"/>
  <Material Name="Substrate" Type="Semiconductor" Permittivity="11.9" DielectricLossTangent="0"
            Conductivity="2.0" Color="01e0ff"/>
  <Material Name="RSIL" Type="Resistor" Rs="7" Color="d0d0d0"/>
</Materials>
```

## `<ELayers>`

Container for the dielectric stack and drawn layers. `LengthUnit` sets the unit for all
`Thickness`/`Zmin`/`Zmax`/`Offset`/`Oversize` values in this section (typically `"um"`).

### `<Dielectrics>`

Defines the vertical dielectric stack, independent of GDSII — these layers exist everywhere
and are not drawn as polygons. Order in the file is **top to bottom**. Three ways to position
a `<Dielectric>`, in the order they take priority:

1. **Absolute** — both `Zmin` and `Zmax` given (no `Reference`).
2. **Reference-relative** — `Reference` given (see below).
3. **Implicit stacking** (the default/legacy behavior) — neither of the above: z-positions are
   computed automatically by stacking `Thickness` values from the top down
   (`calculate_zpositions()` walks the list in reverse).

| Attribute       | Required | Default | Description |
|-----------------|----------|---------|--------------|
| `Name`          | yes      | —       | Dielectric name. Must be unique across `<Dielectrics>`. |
| `Material`      | yes      | —       | References a `<Material>` by name. |
| `Thickness`     | yes*     | —       | Layer thickness. Used to auto-stack this dielectric relative to its neighbors, or (with `Reference`) to size it from the reference edge. |
| `Zmin`/`Zmax`   | no       | —       | Absolute z-position instead of `Thickness` (both required together); or, with `Reference` set, offsets from the reference edge (both optional there — see below). |
| `Reference`     | no       | —       | Name of another `<Dielectric>` to position this one relative to. |
| `ReferenceEdge` | no       | `Top`   | `Top` or `Bottom` (case-insensitive). Only meaningful with `Reference` set. |
| `Boundary`      | no       | —       | GDSII layer number that defines this dielectric's finite (x,y) extent in the model. Optional — omit for a dielectric that simply fills the whole simulation domain. |

\* `Thickness` is required unless `Zmin`/`Zmax` are both given (absolute mode), or `Zmax` is
given (`Reference` mode).

```xml
<Dielectrics>
  <Dielectric Name="AIR" Material="AIR" Thickness="200.0000" />
  <Dielectric Name="Passive" Material="Passive" Thickness="0.4000" />
  <Dielectric Name="SiO2" Material="SiO2" Thickness="15.7303" />
  <Dielectric Name="EPI" Material="EPI" Thickness="3.7500" />
  <Dielectric Name="Substrate" Material="Substrate" Thickness="180.0000" />
</Dielectrics>
```

With an explicit boundary layer instead of the full domain:

```xml
<Dielectric Name="Package" Material="MoldCompound" Thickness="500" Boundary="299"/>
```

#### Reference-relative positioning (Dielectrics)

Like `<Layer>`'s `Reference` (below), but Dielectrics keep `Thickness` as their primary size
instead of requiring both `Zmin`/`Zmax`: `Zmin` defaults to `0` (start right at the reference
edge — the common case) and `Zmax` defaults to `Zmin + Thickness`. Either can still be given
explicitly to override — e.g. a small designed gap before this dielectric starts.

```xml
<Dielectric Name="SiO2" Material="SiO2" Thickness="15.7303"
            Reference="EPI" ReferenceEdge="Top" />
<!-- equivalent to Zmin="0" Zmax="15.7303" offset from EPI's top edge -->
```

`Reference` on a Dielectric can only target another `<Dielectric>` — never a `<Layer>` (Layers
are resolved after Dielectrics, so the reverse would be a circular pipeline dependency).

**Implicit stacking, made explicit internally:** the reader auto-assigns an in-memory
`Reference` (to the nearest dielectric below it in file order that is *also* using implicit
stacking, `ReferenceEdge="Top"`) to every dielectric that has neither an explicit `Reference`
nor an absolute position — this is purely descriptive (it does not change the computed
z-position, and by default it is **not** written back into the XML file). It lets other code
treat every dielectric's positioning uniformly through `.reference`/`.reference_edge`, and lets
the Stackup Editor's Dielectrics tab show a live Reference-style relationship even for
old-style, purely `Thickness`-stacked files. The Stackup Editor offers, once per file per
editing session at Save time, to write these auto-assigned references into the XML — declining
leaves the file exactly as implicit as before (same resulting z-positions either way).

Note one legacy quirk this auto-assignment deliberately preserves: an absolute-position or
explicit-`Reference` dielectric sitting between two implicit ones is transparent to implicit
stacking — implicit dielectrics keep stacking against each other as if it weren't there, not
against its own `Zmax`. Mixing absolute/Reference dielectrics with implicit ones is uncommon;
if you rely on one sitting directly beneath an implicit dielectric, give that implicit
dielectric an explicit `Reference` instead of relying on file order.

### `<Layers>`

Drawn layers: metals, vias, sheet resistors, and dielectric "bricks" that are read from
specific GDSII layer numbers instead of being implied by the dielectric stack.

An optional `<Substrate Offset="..."/>` element shifts the z-position of every `<Layer>` by
a fixed amount (used e.g. to place the drawn stack on top of a backside/substrate region
that is itself modeled with negative z).

| Attribute | Required | Default | Description |
|-----------|----------|---------|--------------|
| `Name`    | yes      | —       | Layer name, used for lookups (`getbylayername`) and in port definitions (`from_layername`/`to_layername` etc. elsewhere in the pipeline). Must be unique across `<Layers>`, and must not collide with a `<Dielectric>` name (see `Reference` below). |
| `Type`    | yes      | —       | `conductor`, `via`, `dielectric`, or `sheet` (see below). |
| `Material`| yes      | —       | References a `<Material>` by name, or the reserved keyword `"PEC"` (see below). |
| `Zmin`    | yes      | —       | Bottom z-position — absolute, or an offset from `Reference`'s edge if `Reference` is set (see below). |
| `Zmax`    | yes      | —       | Top z-position, same absolute-vs-offset rule as `Zmin`. Equal to `Zmin` forces `Type` to `sheet` regardless of the stated `Type`. |
| `Layer`   | yes      | —       | GDSII layer number. Also used as the target layer number for a [derived layer](#derivedlayers-boolean-operations-on-layers), in which case its geometry does not need to exist directly in the GDSII file. |
| `Reference` | no     | —       | Name of another `<Dielectric>` or `<Layer>` to position this layer relative to. When set, `Zmin`/`Zmax` are reinterpreted as offsets from the resolved reference edge instead of absolute z (positive = up). Dielectric and Layer names share one namespace for this lookup, so a name must not exist as both. |
| `ReferenceEdge` | no | `Top`   | `Top` or `Bottom` (case-insensitive). Only meaningful with `Reference` set. For a `<Dielectric>` target: its top/bottom z. For a `<Layer>` target: its `Zmax`/`Zmin`. |

Layer `Type` meanings:
- **`conductor`** — a normal metal layer with thickness (`Zmax > Zmin`).
- **`via`** — a vertical connection between two conductor layers; eligible for via-array
  merging (`merge_polygon_size` in `read_gds()`).
- **`dielectric`** — a drawn (GDSII-sourced) dielectric region, as opposed to the implicit
  stack in `<Dielectrics>`.
- **`sheet`** — zero-thickness layer (`Zmin == Zmax`), typically paired with a `Resistor`
  material for sheet-resistance elements.

> **Reserved keyword `Material="PEC"`:** valid on a `conductor`, `via`, or `sheet` layer with no
> matching `<Material>` entry at all — it bypasses the `<Materials>` list entirely and is
> modeled as a literal ideal conductor (`CSX.AddMetal(...)`), for the polygon/volume itself in
> all three cases — openEMS is FDTD, so unlike an FEM solver it has no "domain vs. boundary"
> distinction that would make a PEC via any less exact than a PEC sheet or metal.

```xml
<Layers>
  <Substrate Offset="183.75"/>
  <Layer Name="Metal1" Type="conductor" Zmin="1.0400" Zmax="1.4600" Material="Metal1" Layer="8" />
  <Layer Name="Via1"   Type="via"       Zmin="1.4600" Zmax="2.0000" Material="Via1"   Layer="19" />
  <Layer Name="LBE"    Type="dielectric" Zmin="-183.75" Zmax="0"    Material="AIR"    Layer="157" />
  <Layer Name="RSIL"   Type="sheet"     Zmin="0.4"     Zmax="0.4"   Material="RSIL"   Layer="314"/>
</Layers>
```

#### Reference-relative positioning (Layers)

Instead of an absolute z-position, a `<Layer>` can position itself relative to the top or
bottom edge of a named `<Dielectric>` or another `<Layer>`, by setting `Reference`
(+ optional `ReferenceEdge`, default `Top`). `Zmin`/`Zmax` are then offsets from that edge
(positive = up), not absolute z — the layer may lie fully inside, fully outside, or straddle
the reference's own z-range. This avoids hand-recomputing every dependent `<Layer>`'s z-position
whenever a `<Dielectric Thickness="...">` changes; a `<Layer>` can itself be a `Reference`
target for another `<Layer>`, chaining any number of levels deep (resolved in dependency order,
regardless of file order).

```xml
<Layer Name="Metal1" Type="conductor" Material="Metal1" Layer="8"
       Reference="Passive" ReferenceEdge="Top" Zmin="-0.5" Zmax="-0.1" />

<Layer Name="Via1" Type="via" Material="Via1" Layer="19"
       Reference="Metal1" ReferenceEdge="Top" Zmin="0" Zmax="0.54" />
```

Two rules apply:

- **Shared namespace**: `Reference` is looked up against `<Dielectric>` names and `<Layer>`
  names together, so a name must not exist as both — and `<Layer>` names must be unique (unlike
  the general case, this is enforced when `Reference` is used).
- **Mutual exclusivity with `<Substrate Offset="...">`**: a file must not mix
  `Reference`-based `<Layer>` positioning with a nonzero `<Substrate Offset="...">` — it would
  be ambiguous whether the offset applies before or after reference resolution. Use `Reference`
  to point at a backside dielectric's edge directly instead of using `Offset`.

`Reference` is orthogonal to [`<DerivedLayers>`](#derivedlayers-boolean-operations-on-layers) —
a derived layer's own `<Layer>` entry (the one giving it a Z-position/material) can use
`Reference` like any other layer.

### `<DerivedLayers>` (boolean operations on layers)

Defines new layer numbers whose geometry is *computed* from other layers (boolean
operations and/or resizing) instead of being read directly from GDSII — e.g. an overlap
between two drawn layers, used here to derive resistor geometry from poly/implant/contact
layers. Full reference, including chaining and self-touching polygon handling, is in
[`derived_layers.md`](derived_layers.md); summary:

- Give the derived layer's target `Layer` number a normal `<Layer>` entry too (as above),
  so it gets a Z-position/material and is included in `metals_list.getlayernumbers()`.
- `Operation` is one of `AND`, `OR`, `XOR`, `NOT` (≥2 `<Operand>` children, folded pairwise
  in order — order matters for `NOT`), or `SIZE` (exactly 1 operand, requires non-zero
  `Oversize`, pure resize with no boolean op).
- `Oversize` (optional, any operation) grows (positive) or shrinks (negative) the result by
  a fixed distance in layout units, applied after the boolean step.
- An `<Operand Layer="...">` can reference a native GDSII layer number or another derived
  layer's number; dependencies are resolved automatically regardless of definition order.

```xml
<DerivedLayers>
  <!-- layer 240 = layer 134 (TopMetal2) AND layer 126 (TopMetal1) -->
  <DerivedLayer Name="TM1_TM2_Overlap" Layer="240" Operation="AND">
    <Operand Layer="134"/>
    <Operand Layer="126"/>
  </DerivedLayer>

  <!-- layer 241 = layer 134 minus layer 126 -->
  <DerivedLayer Name="TM2_minus_TM1" Layer="241" Operation="NOT">
    <Operand Layer="134"/>
    <Operand Layer="126"/>
  </DerivedLayer>

  <!-- layer 242 = layer 126, grown by 2 units on every side, no boolean op -->
  <DerivedLayer Name="TM1_grown" Layer="242" Operation="SIZE" Oversize="2">
    <Operand Layer="126"/>
  </DerivedLayer>
</DerivedLayers>
```

Three or more operands are allowed for `AND`/`OR`/`XOR`, folded left to right — used here to
intersect three layers into one resistor recognition layer:

```xml
<DerivedLayer Name="Rhigh_or_Rppd" Layer="311" Operation="AND">
  <Operand Layer="28"/>
  <Operand Layer="14"/>
  <Operand Layer="310"/>  <!-- 310 is itself a derived layer, resolved first -->
</DerivedLayer>
```

## `<Tables>` (thermal conductivity)

Optional, sibling of `<Materials>` and `<ELayers>` directly under `<Stackup>`. Defines named
temperature/value lookup tables for materials whose thermal conductivity depends on
temperature (referenced from `<Material ThermalConductivityTable="...">` instead of a
constant `ThermalConductivity`).

```xml
<Tables>
  <Table Name="Si_k_vs_T">
    <Point Temperature="250" Value="170"/>
    <Point Temperature="300" Value="148"/>
    <Point Temperature="350" Value="130"/>
  </Table>
</Tables>
```

```xml
<Material Name="Substrate" Type="Semiconductor" Permittivity="11.9" Conductivity="2.0"
          ThermalConductivityTable="Si_k_vs_T" Color="01e0ff"/>
```

## What `read_substrate()` returns

```python
materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate(XML_filename)
```

- `materials_list` — all `<Material>` entries (`stackup_materials_list`).
- `dielectrics_list` — all `<Dielectric>` entries, with z-positions resolved
  (`dielectric_layers_list`).
- `metals_list` — all `<Layer>` entries, sorted by z with above/below neighbors resolved
  (`metal_layers_list`). `metals_list.getlayernumbers()` is the layer list normally passed to
  `gds_reader.read_gds()`.
- `metals_list.derived_layers` — parsed `<DerivedLayers>` entries (empty if the XML has none).
  Not a separate return value, so this signature stays compatible with older 3-value call
  sites; `read_gds()` picks it up automatically from `metals_list` if not passed explicitly.
