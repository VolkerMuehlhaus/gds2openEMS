# More Examples

Extra, more advanced gds2openEMS examples, each demonstrating one specific
feature or workflow choice beyond the baseline scripts in
[`../workflow`](../workflow) (`run_line_viaport.py`, `run_generic_nport.py`,
etc. - several of the examples below are explicitly derived from one of
those). Each folder is self-contained (own GDS/XML/script) and has its own
README with the details.

| Example | Demonstrates |
|---|---|
| [`combine_layout_sources`](combine_layout_sources) | Combining GDS-derived geometry, manually-added polygons, native openEMS shapes and an STL import in one model - and which of those get automatic mesh refinement |
| [`core_transistor_3port_bce`](core_transistor_3port_bce) | 5-port transistor parasitic-extraction network: 2 RF pad via ports plus 3 via ports straight to the Base/Collector/Emitter terminals, referenced to an artificial ground plane |
| [`easyMesh`](easyMesh) | The `settings{}` dict script style, a full generic n-port sweep, and the third-party easyMesh4openEMS meshing module |
| [`local_modules_copy`](local_modules_copy) | Running gds2openEMS from a local `modules/` folder copy instead of the installed PyPI package |
| [`numThreads`](numThreads) | Forcing a fixed openEMS solver thread count instead of automatic detection |
| [`parameterized_XML_stackup`](parameterized_XML_stackup) | Overriding stackup `<Variable>`s from a Python script without editing the XML file |
| [`resistors_sg13g2`](resistors_sg13g2) | Simulating an IHP SG13G2 `Rsil` resistor recognized via `<DerivedLayers>` boolean operations |

Three examples (`combine_layout_sources`, `easyMesh`, `local_modules_copy`)
share the same simple 2-port via-port test line
(`line_simple_viaport.gds` + `SG13G2_nosub.xml`, a reduced substrate-free
stackup) so the actual feature difference between them stays easy to spot -
see each one's own README for the specifics.
