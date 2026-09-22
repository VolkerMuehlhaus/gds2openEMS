# SG13G2 Resistors (Derived Layers)

`run_resistors_Rsil.py` simulates an IHP SG13G2 `Rsil` (silicided
polysilicon) resistor with a nominal value of 50 Ω, recognized purely from
the stackup file rather than being drawn on its own dedicated GDS layer:
`SG13G2_with_resistors_200um.xml` uses `<DerivedLayers>` boolean operations
(`OR`/`AND`/`NOT`) to build `RSIL`/`RPPD`/`RHIGH` sheet-resistor geometry out
of the poly/implant/contact layers actually present in the GDSII - see
[`../../doc/derived_layers.md`](../../doc/derived_layers.md) for how that
mechanism works in general.

Two via ports (`Metal1` → `Metal2`, layers 201/202) sit at either end of the
resistor. Meshing is finer than the other line examples
(`refined_cellsize = 0.2` µm) since resolving the resistor geometry itself -
not just the surrounding metal routing - needs it. Like `easyMesh`, this
runs a full n-port excitation loop and writes a full Touchstone S-parameter
file, using the installed PyPI package and classic loose-variable script
style.

## See also

- [`../../doc/derived_layers.md`](../../doc/derived_layers.md) - full
  reference for `<DerivedLayers>` boolean/resize operations.
- [`../parameterized_XML_stackup`](../parameterized_XML_stackup) - another
  stackup-file feature (`<Variables>`/overrides) shown independently of this one.
