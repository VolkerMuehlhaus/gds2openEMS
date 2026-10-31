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

# de-embed Empire S-parameter file using port geometry metadata file
# this removes parasitic port inductance (flat ribbon calculation)
# 
# De-embeeding requires port geometry information file "port_information.json" in the same directory.
# Functionality to create this file was added to openEMS workflow code on 18-Jan-2026.
#
# usage: python deembed_empire.py empire_data.snp
# 
# Output file is a new *.snp file with suffix "_deembedded"

import os, json, math
import skrf as rf
from skrf.circuit import Circuit
import argparse


def flat_strip_inductance(length, width, thickness, unit):
    """
       Flat Wire Inductor Calculator
       The original for this equation is by F.E. Terman and can be found in the Radio Engineers Handbook, McGraw-Hill, New York, 1945.
    """
    return 2e-7* length * unit * (math.log(2*length/(width+thickness)) + 0.5 + 0.2235*(width+thickness)/length)



def port_deembedding (snp_filename, port_info_available, port_info_data):
    if port_info_available:
        print('Port de-embedding based on port geometry data')
        unit = port_info_data.get("unit", 1e-6) # default dimension is micron 

        # calculate parasitic port inductance for all ports
        Lport = {}
        portlist = port_info_data["ports"]
        for port in portlist:
            portnum = port.get("portnumber", None)    
            length  = port.get("length", None)
            width   = port.get("width", None)
            if (length is not None) and (width is not None) and (portnum is not None):
                thickness = 0 # Palace ports are 2D sheets with no thickness
                L = flat_strip_inductance(length, width, thickness, unit)
                # store into dict for this port number, just in case the port numbers in the file are in wrong sorting order;
                # a multielement port has one entry per element: the elements are in parallel, so are their inductances
                if str(portnum) in Lport:
                    L = 1.0 / (1.0 / Lport[str(portnum)] + 1.0 / L)
                Lport[str(portnum)]=L

        # load SnP data and apply negative series L at each port
        ntwk  = rf.Network(snp_filename)
        freq = ntwk.frequency
        N = ntwk.nports

        # Create a Media object (needed for Media.inductor)
        media = rf.media.DefinedGammaZ0(frequency=freq, z0=50)

        # Build the de-embedding circuit with explicit, named connections:
        # external port n -- series L of port n -- DUT port n
        # Chaining skrf connect() instead renumbers the remaining ports on every call, which is easy
        # to get wrong (it put all L values at port 1 before). The L values are looked up by port
        # number, a port without geometry data is connected directly (L = 0).
        dut = ntwk.copy()
        dut.name = 'dut'
        connections = []
        for n in range(N):
            if str(n+1) in Lport:
                L = -Lport[str(n+1)]
                print(f'Cascading L= {L*1e12:.2f} pH at port {n+1}')
            else:
                L = 0.0
                print(f'No geometry data for port {n+1}, port not de-embedded')
            inductor = media.inductor(L=L, name=f'L{n+1}')
            port = Circuit.Port(freq, name=f'P{n+1}', z0=dut.z0[:, n])
            connections += [[(port, 0), (inductor, 0)], [(inductor, 1), (dut, n)]]
        ntwk = Circuit(connections).network

        filename, file_extension = os.path.splitext(snp_filename)
        out_filename = filename + '_deembedded' # without extension
        ntwk.write_touchstone(out_filename, skrf_comment='De-embedded by adding negative series L at ports', form='db', write_noise=True)
        print('Created file with de-embedding (cascaded negative port L): ', out_filename,'\n')
    else:
        print('Skipping port de-embedding, no port geometry information available')    



# evaluate commandline
parser = argparse.ArgumentParser()
parser.add_argument("s2p",  help="S2P input filename (Touchstone format)")
args = parser.parse_args()

input_file = args.s2p

if os.path.isfile(input_file):

    # Before we evaluate S-parameters, also check if we have a file port_information.json
    port_info_available = False
    # Get the directory two levels up
    data_dir = os.path.dirname(input_file)
    # Possible full filename for port_information.json
    port_info_filename = os.path.join(data_dir, "port_information.json")
    
    # Check if it exists
    if os.path.isfile(port_info_filename):
        print(f"Found extra file with port information: {port_info_filename}")

        # Load the JSON data
        with open(port_info_filename, "r") as f:
            port_info_data = json.load(f)

        # Extract all Z0 values
        Z0_values = [port["Z0"] for port in port_info_data.get("ports", []) if "Z0" in port]
        print("Port Z0 values found:", Z0_values)

        Z0_string = str(Z0_values[0])
        for Z in Z0_values:
            if Z != Z0_values[0]:
                Z0_string = Z0_string + ' ' + str(Z)
        # If string is filled, we have a Z0 parameter for Touchstone header line. 
        # For mixed port impedance, we have multiple values there
        port_info_available = True
        print("Port impedance for Touchstone header: ", Z0_string)

        # We might also get the model basename from the port information file. 
        # This can be useful for Elmer files where the output file and directory 
        # name is always "mesh"
        modelname_from_portinfo = port_info_data.get("name", "")

    else:
        Z0_string = "50"       # default 
        modelname_from_portinfo = ""

    # try port-deembedding of port geometry information is available
    if port_info_available: 
        port_deembedding (input_file, port_info_available, port_info_data)
    else:
        print('Skipping port de-embedding, no port geometry data file available')    

else:
    print(f"Could not load file {input_file}")
