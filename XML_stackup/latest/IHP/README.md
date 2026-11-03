# IHP stackup files (latest)

These are the current gds2openEMS stackup files for IHP SG13G2 and SG13CMOS5L. They replace the files in [../../legacy](../../legacy), which are kept only for compatibility with older models. For the XML format itself, see the [XML stackup format description](../../../doc/XML_stackup_format.md).

The files need gds2openEMS 0.4.0 or newer (September 2026), the first release with `<Variables>`, Reference positioning and the reserved `PEC` material.

These files are for gds2openEMS only, do not use them with gds2palace. The gds2palace stackups model the MIM capacitor differently, see below.

| File | Technology | Passivation over top metal | Default total height |
|---|---|---|---:|
| `SG13G2_FDTD_300um.xml` | SG13G2 (7 metals) | planar SiO2 + Passivation block over TopMetal2 | 300 µm |
| `SG13G2_FDTD_300um_passicut.xml` | SG13G2 (7 metals) | SiO2 + Passivation only up to the "valleys" between TopMetal2 traces | 297 µm |
| `SG13CMOS5L_FDTD_300um.xml` | SG13CMOS5L (5 metals) | planar SiO2 + Passivation block over TopMetal1 | 300 µm |

"300um" is the total chip height, the same as the legacy `SG13G2.xml` and `SG13CMOS5L.xml` used by the [workflow](../../../workflow) examples. For SG13G2 this is 280.12 µm substrate below 19.88 µm of EPI + BEOL. The legacy `SG13G2.xml` used a 280 µm substrate, so its total height was 299.88 µm. For other chip heights, override `total_thickness`, see below. The metal, via and MIM positions above the substrate are the same as in the legacy files.

To use a file, copy it next to your model script, or use the copy that is installed with the gds2openEMS package:

```python
XML_filename = utilities.get_stackup_path('SG13G2_FDTD_300um.xml')
```

`utilities.get_stackup_path()` without a file name prints the stackup folder and the available files.

## MIM capacitor

The MIM dielectric is much thinner than all other layers. Resolved with its real thickness, it would need a very small FDTD time step and slow down the simulation. The openEMS stackups therefore model it with a 0.1 µm thick dielectric `MIM_equiv` with permittivity 16.87, for the same capacitance per area of 1.5 fF/µm². The MIM top plate is modelled as a via block from that dielectric up to TopMetal1. This is unchanged from the legacy files.

## Changes from the legacy stackups

**Parameterized heights (`<Variables>`)**
- `total_thickness`: final chip height. The substrate thickness (`bulk_thickness`) is calculated from it, so the BEOL stays the same and only the substrate changes.
- `air_thickness`: thickness of the air layer above the passivation, 300 µm by default as in most legacy files.
- Layers and dielectrics are positioned relative to each other (`Reference`/`ReferenceEdge`) instead of absolute z values, and `LBE` follows the substrate height automatically.

Using parameters for final chip height and air height replaces several legacy files, see below.

**Resistors**
- New sheet resistor layers `RHIGH` (Rs = 1360 Ω), `RPPD` (Rs = 260 Ω) and `RSIL` (Rs = 7 Ω) on top of Activ.
- They are created by derived layers from the drawn PDK layers (GatPoly, resistor marker layers), so no extra drawing is needed in the layout. See the [resistor example](../../../more_examples/resistors_sg13g2/README.md).
- New `REF_FOR_TRANSISTOR` PEC sheet (layer 300) at the same height, as a reference plane for transistor ports (see the [transistor example](../../../more_examples/core_transistor_3port_bce/README.md)).

**Ground layers**
- `SUBGND` is now an ideal conductor sheet (`PEC`) on top of the EPI layer. In the legacy files it was a 3.75 µm thick volume of `LOWLOSS` material filling the EPI layer.
- `SUBGND` moved from GDS layer 210 to 250, for SG13G2 and SG13CMOS5L. Layer 210 was inside the range 201–249 used for port polygons. Layouts that drew SUBGND on layer 210 need to move those shapes to layer 250.
- `BACKSIDEGND` (layer 251) is a new `PEC` sheet at the bottom of the substrate, where it is drawn in the layout. The legacy `_backsideGND` files had a 1 µm `LOWLOSS` slab below the whole substrate instead.
- The `LOWLOSS` material is no longer needed and has been removed.

**Cut passivation (`SG13G2_FDTD_300um_passicut.xml` only)**
- The planar SiO2 dielectric ends 1.5 µm above the bottom of TopMetal2 (the "valleys" between TopMetal2 traces), followed by the Passive and AIR layers. TopMetal2 extends into the AIR layer, there is no SiO2 or passivation on top of it.
- `total_thickness` is the height the chip would have with the full SiO2 thickness, so the substrate is the same as in `SG13G2_FDTD_300um.xml`. The real chip top is 3 µm lower.
- See the [L6n2 inductor study](../../../more_examples/measured_vs_simulated/more_accurate_models_L6n2/README.md#third-error-source-non-planar-dielectrics-covering-topmetal2) for results compared to the planar stackup.

## Legacy files and their replacement

| Legacy file | Use instead |
|---|---|
| `SG13G2.xml` | `SG13G2_FDTD_300um.xml` (substrate 0.12 µm thicker, total height now exactly 300 µm) |
| `SG13G2_200um.xml` | `SG13G2_FDTD_300um.xml` with `total_thickness = 200` (substrate 0.12 µm thicker, total height now exactly 200 µm) |
| `SG13G2_200um_backsideGND.xml` | `SG13G2_FDTD_300um.xml` with `total_thickness = 200`, backside ground drawn on layer 251, and `air_thickness = 200` for the same air height. The legacy file modelled a 1 µm backside metal slab below the substrate, so all heights differ by 1 µm. |
| `SG13CMOS5L.xml` | `SG13CMOS5L_FDTD_300um.xml` (identical dielectric heights) |
| `SG13CMOS5L_200um.xml` | `SG13CMOS5L_FDTD_300um.xml` with `total_thickness = 200` (identical dielectric heights) |
| `SG13CMOS5L_200um_backsideGND.xml` | `SG13CMOS5L_FDTD_300um.xml` with `total_thickness = 200` and backside ground drawn on layer 251. The legacy file modelled a 1 µm backside metal slab below the substrate, so all heights differ by 1 µm. |
| `SG13G2_nosub.xml`, `SG13CMOS5L_nosub.xml` | `SG13G2_FDTD_300um.xml` / `SG13CMOS5L_FDTD_300um.xml` with `total_thickness = 25`. Not identical, but a similar use case: the legacy files had no silicon at all (BEOL on a 2 µm SiO2 spacer), while this keeps the 3.75 µm EPI layer on a thin substrate. Do not go below `total_thickness` = 19.88 (SG13G2) or 13.05 (SG13CMOS5L): the substrate thickness would become zero or negative, and the stackup reader does not check this. |

In all cases, SUBGND is now on layer 250 instead of 210.

## Overriding stackup variables in the model code

A model can change any `<Variable>` of the stackup file without editing the XML file. The Python model code passes a dictionary of overrides to the stackup reader:

```python
XML_filename = utilities.get_stackup_path('SG13G2_FDTD_300um.xml')
settings['variable_overrides'] = {'total_thickness': 100, 'air_thickness': 200}

...

materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate (XML_filename, variable_overrides=settings['variable_overrides'])
```

Without overrides, the dictionary is empty and the values from the XML file are used:

```python
settings['variable_overrides'] = {}
```

How overrides work:
- Each key must be the name of a `<Variable>` defined in the stackup file. An unknown name stops the model with an error, so a typo is not silently ignored.
- The values are plain numbers, not `=` expressions.
- Variables calculated from an overridden variable follow it automatically. For example, overriding `total_thickness` also changes `bulk_thickness` (substrate) and the height of `LBE`.
- Override the base variables (`total_thickness`, `air_thickness`), not the calculated ones like `bulk_thickness`. An override replaces a calculated variable's formula completely.

The [parameterized stackup example](../../../more_examples/parameterized_XML_stackup/README.md) shows both model syntax styles.
