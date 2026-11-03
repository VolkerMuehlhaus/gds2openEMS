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
#
# Dual dipole 245 GHz, design by IHP Klaus Schmalz
# Port defined in GDSIIfile on layer 201
# nf2ff_box field sampling at boundary for pattern calculation
# Model update Jan-2026: used MUR boundary instead of PML8 for faster simulation, removed extra margin required for PML
#
# This model uses the settings{} dictionary syntax and the gds2openEMS PyPI package
# (pip install gds2openEMS) instead of a local copy of the modules folder - see the
# README for the loose-variable / local-modules-copy alternative, still fully supported.
# wavelength_air/max_cellsize are still computed manually here (not left to setupSimulation's
# own settings-dict auto-computation) because CreateNF2FFBox() below needs max_cellsize too,
# and settings dict values are not written back after the setupSimulation() call.

# ======================== workflow settings ================================

settings = {}

# preview model/mesh only?
settings['preview_only'] = False

# ===================== input files and path settings =======================

gds_filename = "dipole_port_sg13.gds"   # geometries
XML_filename = "../XML_stackup/legacy/SG13G2_200um_backsideGND.xml"       # stackup

# preprocess GDSII for safe handling of cutouts/holes?
settings['preprocess_gds'] = True

# merge via polygons with distance less than .. microns, set to 0 to disable via merging.
settings['merge_polygon_size'] = 0

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

settings['unit']   = 1e-6   # geometry dimensions and all lengths unit is µm (micrometer)
settings['margin'] = 100    # distance in microns from GDSII geometry boundary to chip boundary

settings['fstart'] = 200e9
settings['fstop']  = 300e9
num_freq = 401

ftarget = 245e9  # frequency for antenna pattern calculation

settings['refined_cellsize'] = 2.5  # mesh cell size in conductor region

# choices for boundary:
# 'PEC' : perfect electric conductor (default)
# 'PMC' : perfect magnetic conductor, useful for symmetries
# 'MUR' : simple MUR absorbing boundary conditions
# 'PML_8' : PML absorbing boundary conditions
settings['Boundaries'] = ['MUR', 'MUR', 'MUR', 'MUR', 'MUR', 'MUR']

settings['cells_per_wavelength'] = 12   # how many mesh cells per wavelength, must be 10 or more
settings['energy_limit'] = -40          # end criteria for residual energy (dB)

# ports from GDSII Data, polygon geometry from specified special layer
# note that for multiport simulation, excitations are switched on/off in simulation_setup.createSimulation below
simulation_ports = simulation_setup.all_simulation_ports()
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=1, voltage=1, port_Z0=50, source_layernum=201, target_layername='TopMetal2', direction='x'))

# ======================== simulation ================================

# get technology stackup data
materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate (XML_filename)
# get list of layers from technology
layernumbers = metals_list.getlayernumbers()
layernumbers.extend(simulation_ports.portlayers)

# read geometries from GDSII, only purpose 0
allpolygons = gds_reader.read_gds(gds_filename, layernumbers, purposelist=[0], metals_list=metals_list, preprocess=settings['preprocess_gds'], merge_polygon_size=settings['merge_polygon_size'])

# calculate maximum cellsize from wavelength in dielectric - needed below for CreateNF2FFBox(),
# so kept as a manual computation instead of setupSimulation's internal settings-dict version
wavelength_air = 3e8/settings['fstop'] / settings['unit']
max_cellsize = (wavelength_air)/(np.sqrt(materials_list.eps_max)*settings['cells_per_wavelength'])

settings['simulation_ports'] = simulation_ports
settings['materials_list'] = materials_list
settings['dielectrics_list'] = dielectrics_list
settings['metals_list'] = metals_list
settings['layernumbers'] = layernumbers
settings['allpolygons'] = allpolygons
settings['sim_path'] = sim_path
settings['model_basename'] = model_basename
settings['air_around'] = 0.5*wavelength_air


########### create model, run and post-process ###########

# Prepare simulation for port 1 excitation
settings['excite_portnumbers'] = [1]
FDTD = openEMS(EndCriteria=np.exp(settings['energy_limit']/10 * np.log(10)))
FDTD.SetGaussExcite( (settings['fstart']+settings['fstop'])/2, (settings['fstop']-settings['fstart'])/2 )
FDTD.SetBoundaryCond( settings['Boundaries'] )

FDTD = simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)  # must use named parameters when using settings dict!

# add nf2ff box for antenna pattern calculation
nf2ff_box = FDTD.CreateNF2FFBox(opt_resolution = [max_cellsize]*3, frequency = [ftarget])

# run simulation
sub1_data_path = simulation_setup.runSimulation(FDTD=FDTD, settings=settings)  # must use named parameters when using settings dict!

# simulation is finished, get results, CSX port definition is read from simulation ports object
CSX_port1 = simulation_ports.get_port_by_number(1).CSXport

# definition of some utility functions
def dB(value, factor=20):
    return factor*np.log10(np.abs(value))
def dBm(value, factor=20):
    return dB(value/1e-3, factor=factor)

# evaluate results for 1-port simulation
if not settings['preview_only']:
    f = np.linspace(settings['fstart'], settings['fstop'], num_freq)

    s11 = utilities.calculate_Sij(1, 1, f, sim_path, simulation_ports)
    s11_dB = dB(s11)

    # write Touchstone S1P file
    s1p_name = os.path.join(sim_path, model_basename + '.s1p')
    utilities.write_snp (np.array([s11]),f, s1p_name, z0=simulation_ports.get_reference_impedance())

    # plot return loss
    fig, axis = plt.subplots(num="Return Loss", tight_layout=True)
    axis.plot(f/1e9, s11_dB, 'k-', linewidth=2, label='S11 (dB)')
    axis.grid()
    axis.set_xmargin(0)
    axis.set_xlabel('Frequency (GHz)')
    axis.set_title("Return Loss")
    axis.legend()
    
    print('Calculating antenna pattern, this will take a while!')
    
    theta = np.arange(-180.0, 180.0, 2.0)
    phi   = [0., 90.]
    nf2ff_res = nf2ff_box.CalcNF2FF(sub1_data_path, ftarget, theta, phi)

    # INPUT POWER values into feed port at evaluation frequency
    # P_acc = accepted power (incoming - reflected)
    # P_inc = incident power (incoming), regardless of reflection
    
    # get accepted power into port
    Pin_accepted = np.interp(ftarget, f, CSX_port1.P_acc)
    # get incident power
    P_incident = np.interp(ftarget, f, CSX_port1.P_inc)

    # get total radiated power at nf2ff frequency 
    Prad_total = nf2ff_res.Prad[0]
    # get directivity (peak value) at nf2ff frequency 
    Dmax_dB = dB(nf2ff_res.Dmax[0], 10)
    # calculate radiation efficiency (lossless antenna is 1, regardless of input matching)
    radiation_efficiency = Prad_total/Pin_accepted
    radiation_efficiency_dB = dB(radiation_efficiency, 10)  # negative for lossy antenna
    # loss from reflection due to mismatch
    mismatch_loss =  Pin_accepted/P_incident
    mismatch_loss_dB = dB(mismatch_loss, 10)

    # evaluate far field components
    # normalize E field components to peak value of absolute field, and multiply by directivity
    directivity_abs  = dB(nf2ff_res.E_norm[0]/np.max(nf2ff_res.E_norm[0])) + Dmax_dB
    directivity_abs_xz = directivity_abs[:,0] # get field in xz plane, that is phi=0, which is index 0 
    directivity_abs_yz = directivity_abs[:,1] # get field in yz plane, that is phi=90, which is index 1 

    gain_abs_xz = directivity_abs_xz + radiation_efficiency_dB
    gain_abs_yz = directivity_abs_yz + radiation_efficiency_dB

    # display radiated power and directivity
    print(f"Antenna parameters at {ftarget/1e9:g} GHz:")
    print(f"    Incident power P_incident  =  {P_incident:.3e} W  =  {dBm(P_incident, 10):g} dBm")
    print(f"    Accepted power Pin_accepted  =  {Pin_accepted:.3e} W  =  {dBm(Pin_accepted, 10):g} dBm")
    print(f"    Radiated power Prad_total  =  {Prad_total:.3e} W  =  {dBm(Prad_total, 10):g} dBm")
    print(f"    Directivity Dmax  =  {Dmax_dB:g} dBi")
    print(f"    efficiency nu_rad  =  {100*radiation_efficiency:g} %  =  {radiation_efficiency_dB:g} dB")
    print(f"    mismatch loss  =  {mismatch_loss:g} (linear)  =  {mismatch_loss_dB:g} dB")


    fig, axis = plt.subplots(num="Directivity", tight_layout=True)
    axis.plot(theta, np.squeeze(directivity_abs_xz), 'k-',  linewidth=2, label='xz-plane')
    axis.plot(theta, np.squeeze(directivity_abs_yz), 'r--', linewidth=2, label='yz-plane')
    axis.grid()
    axis.set_xmargin(0)
    axis.set_xlabel('Theta (deg)')
    axis.set_ylabel('Directivity (dBi)')
    axis.set_title(f'Directivity at Frequency: {ftarget/1e9:g} GHz')
    axis.legend()

    fig, axis = plt.subplots(num="Gain", tight_layout=True)
    axis.plot(theta, np.squeeze(gain_abs_xz), 'k-',  linewidth=2, label='xz-plane')
    axis.plot(theta, np.squeeze(gain_abs_yz), 'r--', linewidth=2, label='yz-plane')
    axis.grid()
    axis.set_xmargin(0)
    axis.set_xlabel('Theta (deg)')
    axis.set_ylabel('Gain (dBi)')
    axis.set_title(f'Gain at Frequency: {ftarget/1e9:g} GHz')
    axis.legend()

    # show all plots
    plt.show()
    
