# Transistor core with 3 via ports at Base/Collector/Emitter (gds2openEMS)

This is the openEMS/FDTD counterpart of the `core_transistor_3port_bce`
example in `gds2palace_ihp_sg13g2` — same transistor test cell, same GDSII
file, same 5-port idea: extract a parasitic S-parameter network for an SiGe
HBT transistor core, with 3 of the 5 ports going directly to the Base,
Collector and Emitter terminals instead of only exposing 2 external RF pads.

It extends the baseline `../numThreads` example (2 pad via ports + 2 in-plane
ports on `Metal2`, 4 ports total) the same way the Palace version does: the 2
in-plane ports are replaced with 3 vertical via ports referenced to a new
artificial common ground plane, `REF_FOR_TRANSISTOR`.

![Layout with all 5 ports](png/layout_and_ports.png)

## Ports

```python
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=1, voltage=1, port_Z0=50, source_layernum=201, from_layername='Metal3', to_layername='TopMetal2', direction='z'))
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=2, voltage=1, port_Z0=50, source_layernum=202, from_layername='Metal3', to_layername='TopMetal2', direction='z'))
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=3, voltage=1, port_Z0=50, source_layernum=203, from_layername='Metal2', to_layername='REF_FOR_TRANSISTOR', direction='z'))
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=4, voltage=1, port_Z0=50, source_layernum=204, from_layername='Metal2', to_layername='REF_FOR_TRANSISTOR', direction='z'))
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=5, voltage=1, port_Z0=50, source_layernum=205, from_layername='Metal2', to_layername='REF_FOR_TRANSISTOR', direction='z'))
```

| Port | Layer | From → To | Purpose |
|---|---|---|---|
| 1 | 201 | Metal3 → TopMetal2 | outer RF pad |
| 2 | 202 | Metal3 → TopMetal2 | outer RF pad |
| 3 | 203 | Metal2 → REF_FOR_TRANSISTOR | transistor Base |
| 4 | 204 | Metal2 → REF_FOR_TRANSISTOR | transistor Collector |
| 5 | 205 | Metal2 → REF_FOR_TRANSISTOR | transistor Emitter |

All 3 transistor-terminal ports reference the same `REF_FOR_TRANSISTOR`
plane, so they behave as ordinary lumped ports to a shared node — no gap
between two conductor edges is needed the way an in-plane port requires,
which is what makes a genuine 3-terminal port set at the device possible.

Note: the ports have been created with zero xy area (i.e. vertical sheet) because that was a requirement in the original gds2palace example. If you prefer that, you can also create ports with finite xy area in gds2palace, i.e. ports represented as volumes in the FDTD solver.

## Using the result in a circuit simulator

The 5-port S-parameters describe the interconnect only. The transistor itself is not in the EM model: in a circuit
simulator, the foundry model (here npn13G2 from the IHP SG13G2 PDK) goes back in at ports 3, 4 and 5, together with
three inductors for the DC bias (explained below):

![Circuit wiring of the 5-port result](png/circuit_wiring.png)

**Wiring.** Use the S-parameters directly (an S-parameter block) or an equivalent circuit made from them (for example
by vector fitting). Either way, each port is referenced to ground. Then:

- Ports 1 and 2 are the RF pads: they connect to the outside circuit.
- The transistor's base, collector and emitter connect directly to ports 3, 4 and 5. Its substrate pin goes to
  ground.

This grounds the `REF_FOR_TRANSISTOR` sheet. In the EM model the sheet floats: it touches only the three ports. Wiring
the transistor directly adds the sheet's own capacitance to ground, a few fF. In a cascode test with two npn13G2
(Nx = 8, simulated with gds2palace), this lowered S21 by 0.06 dB at 10 GHz and 0.4 dB at 200 GHz. To keep the sheet
floating instead, couple each of the three ports through an ideal 1:1 transformer (a voltage-controlled voltage source
plus a current-controlled current source) to a common node for the transistor.

**DC bias.** A port measures a voltage difference, between a terminal and the reference sheet. At DC the sheet has
no connection, so the EM model does not fix the transistor's potential as a whole. Tie each transistor terminal to
the port of the same net with a large inductor (for example 1 mH: a short at DC, open at RF):

- port 3 (base) to port 1 (left pad),
- port 4 (collector) to port 2 (right pad),
- port 5 (emitter) to ground, since the emitter is on the Metal3 ground plane.

The bias is then applied at the pads, for example through bias tees in the testbench.

**DC point of the S-parameters.** The script runs from `fstart = 0`, so the `.s5p` file starts with a 0 Hz point
from the FDTD run itself. In this example's result, that point matches the layout's DC connections within 0.003 in S,
and each signal net leaks about 130 kΩ to the rest. That is fine for a bias from low-impedance sources at the pads.
For a bias network with kΩ resistors, connect the S-parameter model through DC blocks (for example 1 µF at each port),
so that only the inductors carry the bias.

**Port polarity.** With `direction='z'`, gds2openEMS builds a via port from its lower to its upper metal, whatever
the order of `from_layername` and `to_layername`, and `'-z'` reverses it. In this example the signal metal is on top
at every port (TopMetal2 over Metal3, Metal2 over the reference sheet), so `'z'` is right for all of them. For a port
whose signal metal is below its reference metal, use `'-z'`, so that all ports have the same orientation.

A minimal ngspice subcircuit (`em5` is the equivalent circuit of the 5-port, pins in port order):

```spice
.subckt core pad1 pad2
XEM pad1 pad2 b c e em5
XQ c b e 0 npn13G2 <parameters of the transistor in the layout>
Lb pad1 b 1m        ; DC ties, open at RF
Lc pad2 c 1m
Le e 0 1m
.ends core
```

## Stackup (`SG13G2_100um_bce_ports.xml`)

This stackup is the full IHP SG13G2 metal/via stack from this repo's
standard openEMS stackup template
([`../parameterized_XML_stackup/SG13G2_parameterized.xml`](../parameterized_XML_stackup/SG13G2_parameterized.xml)),
including `Activ`/`Cont`/`Metal1`/`Via1` and the dual-layer `MIM_DK`+`MIM`
capacitor representation — even though this particular GDSII file only draws
`Metal2` and up, keeping the full stack means the file stays reusable
as-is for other layouts that do use those layers.

The one addition on top of that standard template:

```xml
<Layer Name="REF_FOR_TRANSISTOR" Type="sheet" Reference="SiO2" ReferenceEdge="Bottom" Material="PEC" Layer="300" Zmin="0.4" Zmax="0.4" />
```

Position is 0.4 µm above the top of `EPI` with `Material="PEC"` — exactly at
the top of `Activ`.

Ports 3/4/5 each span the resulting ~1.6 µm gap between the bottom of
`Metal2` and this artificial ground, passing through the `Via1`/`Metal1`/
`Cont`/`Activ` region — those layers are defined in the stackup (so they
still contribute z-mesh lines through that gap, see below) but have no
drawn geometry at the ports' xy location in this simplified test structure,
so no real conductor fills the gap; the lumped port is the only thing
bridging it.

## Mesh: `refined_cellsize`

The `REF_FOR_TRANSISTOR` footprint is small (~13.5 x 15.5 µm) and the 3 ports
on it sit only ~6.5-7 µm apart, noticeably tighter than the outer-pad
spacing. `refined_cellsize` is set to **0.5 µm**, the same value as the
baseline mpa_core example in `../numThreads`. A dry run confirms this
resolves the 3-port region with roughly a dozen cells across each
port-to-port gap, and gives a 0.4 µm minimum z-cell driven by the
`REF_FOR_TRANSISTOR` position itself; keeping the (undrawn) `Cont`/`Metal1`/
`Via1` layers in the stackup also adds a couple of extra z-mesh lines
through the port gap, since `Type="via"` layers are meshed whether or not
they have drawn geometry at a given xy location:

```
Mesh cells by axis (total 746 kcells):
 x = 112, y = 90, z = 74
Smallest cell size: dx = 0.4813, dy = 0.4153, dz = 0.4000
```

If you tighten the port spacing or shrink the `REF_FOR_TRANSISTOR` footprint
in your own layout, reduce `refined_cellsize` accordingly and check the
resulting cell counts/`AppCSXCAD` preview before running a full sweep.

## Usage

```bash
source ~/venv/openems/bin/activate
python openems_core_bce_ports.py
```

This previews the model in AppCSXCAD before the first port excitation, then
runs all 5 port excitations and writes a 5-port Touchstone file
(`openems_core_bce_ports.s5p`). Connection for B,C,E is at ports 3,4,5 respectively.
