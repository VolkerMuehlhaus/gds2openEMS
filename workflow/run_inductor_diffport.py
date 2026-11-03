########################################################################
#
# Copyright 2025 Volker Muehlhaus and IHP PDK Authors
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

import os

from gds2openEMS import *

from openEMS import openEMS
import numpy as np
import matplotlib.pyplot as plt

# Model comments
# Simple inductor model, 1 port only
#
# This model uses the settings{} dictionary syntax and the gds2openEMS PyPI package
# (pip install gds2openEMS) instead of a local copy of the modules folder - see the
# README for the loose-variable / local-modules-copy alternative, still fully supported.


# ======================== workflow settings ================================

settings = {}

# preview model/mesh only?
settings['preview_only'] = True

# ===================== input files and path settings =======================

gds_filename = "L_2n0_simplified.gds"   # geometries
XML_filename = "../XML_stackup/legacy/SG13G2.xml"               # stackup

# preprocess GDSII for safe handling of cutouts/holes?
settings['preprocess_gds'] = False

# merge via polygons with distance less than .. um, set 0 to disable via merging
settings['merge_polygon_size'] = 1.0

# get path for this simulation file
script_path = utilities.get_script_path(__file__)

# use script filename as model basename
model_basename = utilities.get_basename(__file__)

# set and create directory for simulation output
sim_path = utilities.create_sim_path (script_path,model_basename)
print('Simulation data directory: ', sim_path)

# change current path to model script path
os.chdir(os.path.dirname(os.path.abspath(__file__)))


# ======================== simulation settings ================================

settings['unit']   = 1e-6   # geometry is in microns
settings['margin'] = 200    # distance in microns from GDSII geometry boundary to simulation boundary

settings['fstart']  = 0
settings['fstop']   = 30e9
settings['numfreq'] = 401

settings['refined_cellsize'] = 1.0  # mesh cell size in conductor region

# choices for boundary:
# 'PEC' : perfect electric conductor (default)
# 'PMC' : perfect magnetic conductor, useful for symmetries
# 'MUR' : simple MUR absorbing boundary conditions
# 'PML_8' : PML absorbing boundary conditions
settings['Boundaries'] = ['PEC', 'PEC', 'PEC', 'PEC', 'PEC', 'PEC']

settings['cells_per_wavelength'] = 20   # how many mesh cells per wavelength, must be 10 or more
settings['energy_limit'] = -50          # end criteria for residual energy (dB)

# ports from GDSII Data, polygon geometry from specified special layer
# note that for multiport simulation, excitations are switched on/off in simulation_setup.createSimulation below
simulation_ports = simulation_setup.all_simulation_ports()
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=1, voltage=1, port_Z0=50, source_layernum=201, target_layername='TopMetal1', direction='x'))

# ======================== simulation ================================

# get technology stackup data
materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate (XML_filename)
# get list of layers from technology
layernumbers = metals_list.getlayernumbers()
layernumbers.extend(simulation_ports.portlayers)

# read geometries from GDSII, only purpose 0
allpolygons = gds_reader.read_gds(gds_filename, layernumbers, purposelist=[0], metals_list=metals_list, preprocess=settings['preprocess_gds'], merge_polygon_size=settings['merge_polygon_size'])

# maximum cellsize is calculated inside setupSimulation when using settings dictionary


########### create model, run and post-process ###########

FDTD = openEMS(EndCriteria=np.exp(settings['energy_limit']/10 * np.log(10)))
FDTD.SetGaussExcite( (settings['fstart']+settings['fstop'])/2, (settings['fstop']-settings['fstart'])/2 )
FDTD.SetBoundaryCond( settings['Boundaries'] )

settings['simulation_ports'] = simulation_ports
settings['materials_list'] = materials_list
settings['dielectrics_list'] = dielectrics_list
settings['metals_list'] = metals_list
settings['layernumbers'] = layernumbers
settings['allpolygons'] = allpolygons
settings['sim_path'] = sim_path
settings['model_basename'] = model_basename


# Create simulation for port 1 excitation
settings['excite_portnumbers'] = [1]
simulation_setup.setupSimulation (FDTD=FDTD, settings=settings)  # must use named parameters when using settings dict!
simulation_setup.runSimulation   (FDTD=FDTD, settings=settings)  # must use named parameters when using settings dict!


# get results, CSX port definition is read from simulation ports object
CSX_port1 = simulation_ports.get_port_by_number(1).CSXport

# evaluate results for 1-port simulation
if not settings['preview_only']:

  f = np.linspace(settings['fstart'],settings['fstop'],settings['numfreq'])
  s11 = utilities.calculate_Sij (1, 1, f, sim_path, simulation_ports)

  s1p_name = os.path.join(sim_path, model_basename + '.s1p')
  Z0 = simulation_ports.get_reference_impedance()
  utilities.write_snp (np.array([s11]),f, s1p_name, z0=Z0)

  # ignore divide by zero warning during inductor calculation at DC
  np.seterr(divide='ignore', invalid='ignore')

  zdiff = Z0 * (1+s11)/(1-s11)
  omega = 2*np.pi*f
  Qdiff = zdiff.imag/zdiff.real
  Ldiff = zdiff.imag/omega
  Rdiff = zdiff.real

  # print some inductor data
  # get series L and series R at frequency of interest
  targetfreq = 10e9
  findex = np.where (f>=targetfreq)[0]
  findex = findex.item(0)

  print('\nDifferential inductor parameters')
  
  print(f"Frequency [GHz]: {f[findex]/1e9:.3f}")  
  print(f"Series L  [nH] : {Ldiff[findex]*1e9:.3f}")  
  print(f"Series R  [Ohm]: {Rdiff[findex]:.3f}") 
  print(f"Q factor       : {Qdiff[findex]:.2f}")  
  print('----------------------')
  print(f"L_DC      [nH] : {Ldiff[1]*1e9:.3f}") 
  print(f"R_DC      [Ohm]: {Rdiff[0]:.3f}")  
  print(f"Peak Q         : {max(Qdiff):.2f}") 


  fig, axis = plt.subplots(num="Inductance", tight_layout=True)
  axis.plot(f/1e9, Ldiff*1e9, 'k-',  linewidth=2, label='Lseries [nH]')
  axis.grid()
  axis.set_xmargin(0)
  axis.set_ylim([0, 10])
  axis.set_xlabel('Frequency (GHz)')
  axis.set_title("Inductance")
  axis.legend()


  fig, axis = plt.subplots(num="Q factor", tight_layout=True)
  axis.plot(f/1e9, Ldiff*1e9, 'k-',  linewidth=2, label='Lseries [nH]')
  axis.grid()
  axis.set_xmargin(0)
  axis.set_ylim([0, 30])
  axis.set_xlabel('Frequency (GHz)')
  axis.set_title("Q factor")
  axis.legend()

  # show all plots
  plt.show()