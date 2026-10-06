########################################################################
#
# Copyright 2026 Volker Muehlhaus and IHP PDK Authors
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

# Textbook dielectric-attenuation example for the DielectricLossTangent -> wideband Debye
# dispersive material feature (see ../../doc/XML_stackup_format.md and
# ../../doc/userguide_md_format/Using_OpenEMS_Python_with_IHP_SG13G2_v3.md).
#
# Geometry: a single straight 50-ohm microstrip line, no GDSII file at all (built directly
# with allpolygons.add_rectangle(), the same way as workflow/run_line_noGDSII.py), on a
# simple 2-conductor (ground + trace) stackup.
#
# Substrate: Pozar "Microwave Engineering" Table 3.1-style typical FR4 (G10) values,
# eps_r=4.3, tan(delta)=0.02, h=1.6mm (1600um) - a standard FR4 PCB thickness.
#
# The 50-ohm trace width (W=3111.8um, W/h=1.9449) was synthesized from the closed-form
# Hammerstad equations (see results/microstrip_design.py), the same equations given in every
# microwave engineering textbook (Pozar, Ch. 3, "Microstrip Line") for exactly this purpose.
# Those equations also give the effective permittivity (eps_eff=3.2662) and, together with the
# standard closed-form dielectric attenuation formula (alpha_d, also Pozar Ch. 3), the expected
# attenuation in dB/cm at any frequency in the sweep - entirely analytically, with no
# simulation needed and nothing left unknown. That is the "known answer" this example checks
# the new dispersive-loss feature against, run with the DielectricLossTangent=0 and
# DielectricLossTangent=0.02 stackup copies and compared with results/microstrip_design.py.
#
# Usage:
#   python -u run_microstrip_attenuation.py lossless
#   python -u run_microstrip_attenuation.py lossy

import os
import sys

from gds2openEMS import *
from openEMS import openEMS
import numpy as np

variant = sys.argv[1] if len(sys.argv) > 1 else 'lossless'
if variant not in ('lossless', 'lossy'):
    print('Usage: python run_microstrip_attenuation.py [lossless|lossy]')
    sys.exit(1)

# ======================== workflow settings ================================

settings = {}
settings['preview_only'] = False
settings['no_gui'] = True

XML_filename = 'FR4_microstrip_' + variant + '.xml'

script_path = utilities.get_script_path(__file__)
model_basename = 'run_microstrip_attenuation_' + variant
sim_path = utilities.create_sim_path(script_path, model_basename)
print('Simulation data directory: ', sim_path)

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ======================== simulation settings ================================

settings['unit'] = 1e-6    # geometry is in microns
settings['margin'] = 3000  # um, dielectric oversize around the drawn geometry

settings['fstart'] = 1e9
settings['fstop'] = 4e9
settings['numfreq'] = 301

settings['refined_cellsize'] = 200       # um, mesh size at conductor edges
settings['cells_per_wavelength'] = 15     # coarser background mesh is fine away from the line
settings['Boundaries'] = ['PEC', 'PEC', 'PEC', 'PEC', 'PEC', 'PEC']
settings['energy_limit'] = -40

# ---- geometry (no GDSII, built directly - see workflow/run_line_noGDSII.py) ----

W_um = 3111.8            # synthesized 50-ohm trace width (see results/microstrip_design.py)
L_um = 100000.0          # 100 mm line length
GND_HALFWIDTH_um = 12000.0  # ground plane half-width, several h beyond the trace edges

simulation_ports = simulation_setup.all_simulation_ports()
simulation_ports.add_port(simulation_setup.simulation_port(
    portnumber=1, voltage=1, port_Z0=50, source_layernum=201,
    from_layername='GND', to_layername='Trace', direction='z'))
simulation_ports.add_port(simulation_setup.simulation_port(
    portnumber=2, voltage=1, port_Z0=50, source_layernum=202,
    from_layername='GND', to_layername='Trace', direction='z'))

materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate(XML_filename)
layernumbers = metals_list.getlayernumbers()
layernumbers.extend(simulation_ports.portlayers)

allpolygons = gds_reader.all_polygons_list()

# ground plane, full length plus a little extra so it extends past the ports
allpolygons.add_rectangle(x1=-1000, y1=-GND_HALFWIDTH_um, x2=L_um + 1000, y2=GND_HALFWIDTH_um,
                           layernum=metals_list.getbylayername('GND').layernum)
# signal trace
allpolygons.add_rectangle(x1=0, y1=-W_um/2, x2=L_um, y2=W_um/2,
                           layernum=metals_list.getbylayername('Trace').layernum)
# via ports at each end, spanning the trace width
allpolygons.add_rectangle(x1=0, y1=-W_um/2, x2=1, y2=W_um/2, layernum=201, is_port=True)
allpolygons.add_rectangle(x1=L_um - 1, y1=-W_um/2, x2=L_um, y2=W_um/2, layernum=202, is_port=True)

settings['simulation_ports'] = simulation_ports
settings['materials_list'] = materials_list
settings['dielectrics_list'] = dielectrics_list
settings['metals_list'] = metals_list
settings['allpolygons'] = allpolygons
settings['sim_path'] = sim_path
settings['model_basename'] = model_basename

FDTD = openEMS(EndCriteria=np.exp(settings['energy_limit']/10 * np.log(10)))
FDTD.SetGaussExcite((settings['fstart']+settings['fstop'])/2, (settings['fstop']-settings['fstart'])/2)
FDTD.SetBoundaryCond(settings['Boundaries'])

########### create model, run and post-process ###########
# single-side excitation with symmetry assumed (same approach as workflow/run_line_viaport.py)

excite_ports = [1]
settings['excite_portnumbers'] = excite_ports
FDTD = simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)
simulation_setup.runSimulation(FDTD=FDTD, settings=settings)

f = np.linspace(settings['fstart'], settings['fstop'], settings['numfreq'])
s11 = utilities.calculate_Sij(1, 1, f, sim_path, simulation_ports)
s21 = utilities.calculate_Sij(2, 1, f, sim_path, simulation_ports)

s2p_name = os.path.join(sim_path, model_basename + '.s2p')
s22 = s11
s12 = s21
utilities.write_snp(np.array([[s11, s21], [s12, s22]]), f, s2p_name,
                     z0=simulation_ports.get_reference_impedance())

results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
os.makedirs(results_dir, exist_ok=True)
np.savez(os.path.join(results_dir, 'sparams_' + variant + '.npz'), f=f, s11=s11, s21=s21)
print('Wrote', os.path.join(results_dir, 'sparams_' + variant + '.npz'))

db = lambda x: 20*np.log10(np.abs(x))
print(f'\nVariant: {variant}')
for ff in [1e9, 2e9, 3e9, 4e9]:
    idx = int(np.argmin(np.abs(f - ff)))
    print(f'  f={f[idx]/1e9:.2f} GHz   S21={db(s21)[idx]:7.3f} dB   S11={db(s11)[idx]:7.3f} dB')
