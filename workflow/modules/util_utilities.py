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

import os, tempfile, platform, sys


# ============================== filename and path  =================================

def get_script_path(filename):
    # Define paths and directories
    script_path = os.path.normcase(os.path.dirname(filename))
    return script_path

def get_basename (filename):
    # get file basename without .gds or .py extension
    basename = os.path.basename(filename).replace('.gds', '')
    basename = basename.replace('.py','')
    return basename

def create_sim_path (script_path, model_basename):
    # set directory for simulation output, create path if it does not exist
    base_path = os.path.join(script_path, 'output')

    # check if we might run into path length issues, leave some margin for nested subdiretories and filenames
    if platform.system() == "Windows" and len(base_path) > 200:
        print('[WARNING] Path length limitation, using temp directory for simulation data')
        base_path =  os.path.join(tempfile.gettempdir(), 'openEMS')

    # try to create data directory
    try: 
        sim_path = os.path.join(base_path, model_basename + '_data')
        if not os.path.exists(sim_path):
            os.makedirs(sim_path, exist_ok=True)
    except:
        print('[WARNING] Could not create simulation data directory ', sim_path)
        print('Now trying to use temp directory for simulation data!\n')
        base_path =  os.path.join(tempfile.gettempdir(), 'openEMS')
        sim_path = os.path.join(base_path, model_basename + '_data')

    return sim_path


def get_excitation_path (sim_path, ports, create=True):
    # get path for one specific port excitation, input is list of excited ports, because sometimes multiple ports are excited together
    # create=False is used for read-only lookups (e.g. calculate_Sij), so that checking whether
    # a port was ever excited does not itself create the folder and mask the "missing" case
    portnumber = ports[0]
    ex_path = os.path.join(sim_path, 'sub-' + str(portnumber))
    if create and not os.path.exists(ex_path):
        os.makedirs(ex_path)
    return ex_path

# ========================= S-parameter calculations  =============================

def calculate_Sij (i, j, f, sim_path, simulation_ports):
    # S-parameter calculation for one element of the S matrix.
    # Returns None if port j was never excited - this is the normal case for a port with
    # voltage=0 that a model script left out of its excite_portnumbers, not necessarily an
    # error. Callers must check for None before using the result (see write_snp,
    # calculate_Yij_2port, calculate_Zij_2port, calculate_Zij).
    excitation_path = get_excitation_path (sim_path, [j], create=False)

    if not os.path.exists(excitation_path):
        print(f'[INFO] Port {j} was never run as an excitation (its data folder does not exist) - '
              f'this happens when voltage=0 for that port, it was excluded from '
              f'excite_portnumbers, or its simulation has not been run yet. S{i}{j} is not available.')
        return None

    try:
        CSX_port_i = simulation_ports.get_port_by_number(i).CSXport
        CSX_port_i.CalcPort(excitation_path, f, simulation_ports.get_port_by_number(i).port_Z0)
        if i==j:
            Sij = CSX_port_i.uf_ref  / CSX_port_i.uf_inc
        else:
            CSX_port_j = simulation_ports.get_port_by_number(j).CSXport
            CSX_port_j.CalcPort(excitation_path, f, simulation_ports.get_port_by_number(j).port_Z0)
            Sij = CSX_port_i.uf_ref  / CSX_port_j.uf_inc

        return Sij

    except FileNotFoundError as e:
        # the excitation folder exists but its result data is missing/incomplete - this is a
        # genuine error (e.g. a crashed or still-running simulation), unlike the "never excited"
        # case above which returns None instead of failing here
        print('[ERROR] FileNotFoundError when evaluting S',i,j,'\n', e)
        sys.exit(1)


def calculate_Yij_2port (i, j, f, sim_path, simulation_ports, symmetry=False):
    # Y parameter calculation for 2-port data, returns  one element of the Y matrix, 
    # requires all ports excitations to be simulated because we need full S matrix
    try:
        Z0 = simulation_ports.get_port_by_number(1).port_Z0
        # check if we have the same impedance at both ports
        if Z0 != simulation_ports.get_port_by_number(2).port_Z0:
            print('[ERROR] Y-parameter calculation requires same port impedance on both ports')
            sys.exit(1)

        # get S matrix elements
        s11 = calculate_Sij (1, 1, f, sim_path, simulation_ports)
        s21 = calculate_Sij (2, 1, f, sim_path, simulation_ports)
        if symmetry:
            s22 = s11
            s12 = s21
        else:
            s12 = calculate_Sij (1, 2, f, sim_path, simulation_ports)
            s22 = calculate_Sij (2, 2, f, sim_path, simulation_ports)

        if s11 is None or s21 is None or s12 is None or s22 is None:
            raise ValueError('Cannot compute Y-parameters: one or more ports were never excited '
                              '(voltage=0, excluded from excite_portnumbers, or not yet run).')

        Y0 = 1/Z0

        if (i==1) and (j==1):
            # Y11
            return Y0*((1-s11)*(1+s22)+s12*s21)/((1+s11)*(1+s22)-s12*s21)
        elif (i==1) and (j==2):    
            # Y12
            return Y0*(-2*s12)/((1+s11)*(1+s22)-s12*s21)
        elif (i==2) and (j==1):    
            # Y21
            return Y0*(-2*s21)/((1+s11)*(1+s22)-s12*s21)
        elif (i==2) and (j==2):    
            # Y22
            return Y0*((1+s11)*(1-s22)+s12*s21)/((1+s11)*(1+s22)-s12*s21)
        else:
            print('[ERROR] Invalid parameter requested: Y',i,j)
            sys.exit(1)


    except Exception as e:
        print('[ERROR] Error in Y-parameter calculation:', e)
        sys.exit(1)


        
def calculate_Zij_2port (i, j, f, sim_path, simulation_ports, symmetry=False):
    # Z parameter calculation for 2-port data, returns  one element of the Z matrix, 
    # requires all ports excitations to be simulated because we need full S matrix
    try:
        Z0 = simulation_ports.get_port_by_number(1).port_Z0

        # check if we have the same impedance at both ports
        if Z0 != simulation_ports.get_port_by_number(2).port_Z0:
            print('[ERROR] Z-parameter calculation requires same port impedance on both ports')
            sys.exit(1)

        # get S matrix elements
        s11 = calculate_Sij (1, 1, f, sim_path, simulation_ports)
        s21 = calculate_Sij (2, 1, f, sim_path, simulation_ports)
        if symmetry:
            s22 = s11
            s12 = s21
        else:
            s12 = calculate_Sij (1, 2, f, sim_path, simulation_ports)
            s22 = calculate_Sij (2, 2, f, sim_path, simulation_ports)

        if s11 is None or s21 is None or s12 is None or s22 is None:
            raise ValueError('Cannot compute Z-parameters: one or more ports were never excited '
                              '(voltage=0, excluded from excite_portnumbers, or not yet run).')

        if (i==1) and (j==1):
            # Z11
            return Z0*((1+s11)*(1-s22)+s12*s21)/((1-s11)*(1-s22)-s12*s21)
        elif (i==1) and (j==2):    
            # Z12
            return Z0*(2*s12)/((1-s11)*(1-s22)-s12*s21)
        elif (i==2) and (j==1):    
            # Z21
            return Z0*(2*s21)/((1-s11)*(1-s22)-s12*s21)
        elif (i==2) and (j==2):    
            # Z22
            return Z0*((1-s11)*(1+s22)+s12*s21)/((1-s11)*(1-s22)-s12*s21)
        else:
            print('[ERROR] Invalid parameter requested: Z',i,j)
            sys.exit(1)


    except Exception as e:
        print('[ERROR] Error in Z-parameter calculation:', e)
        sys.exit(1)

        
def calculate_Zij(i, j, f, sim_path, simulation_ports):
    import numpy as np
    import sys
    try:
        # -------------------------------------------------------------
        # Determine number of ports
        # -------------------------------------------------------------
        n_ports = simulation_ports.portcount
        if n_ports == 0:
            raise RuntimeError("No ports found.")

        Z0 = simulation_ports.get_port_by_number(1).port_Z0

        for p in range(2, n_ports + 1):
            if simulation_ports.get_port_by_number(p).port_Z0 != Z0:
                raise RuntimeError("All ports must use the same reference impedance.")

        nf = len(f)

        # -------------------------------------------------------------
        # Build S matrix
        # Shape = (ports, ports, frequencies)
        # -------------------------------------------------------------
        S = np.zeros((n_ports, n_ports, nf), dtype=complex)

        for r in range(n_ports):
            for c in range(n_ports):
                Sij = calculate_Sij(
                    r + 1,
                    c + 1,
                    f,
                    sim_path,
                    simulation_ports
                )
                if Sij is None:
                    raise ValueError(
                        f'Cannot compute Z-parameters: port {c + 1} was never excited '
                        '(voltage=0, excluded from excite_portnumbers, or not yet run).'
                    )
                S[r, c, :] = Sij

        # -------------------------------------------------------------
        # Compute requested Zij(f)
        # -------------------------------------------------------------
        Zij = np.zeros(nf, dtype=complex)
        I = np.eye(n_ports, dtype=complex)

        for k in range(nf):
            Sk = S[:, :, k]
            Zk = Z0 * (I + Sk) @ np.linalg.inv(I - Sk)
            Zij[k] = Zk[i-1, j-1]

        return Zij

    except Exception as e:
        print("[ERROR] Error in Z-parameter calculation:", e)
        sys.exit(1)


# =========================== S-parameter output  =================================

def write_snp (Smatrix,f, filename, z0=50):
    # Smatrix input must np.array[s11] or np.array[[s11,s21],[s12,s22]], more ports are also supported

    matrixsize = len(Smatrix)
    numfreq = len(f)

    # calculate_Sij() leaves a matrix entry as None if that port was never excited (voltage=0,
    # excluded from excite_portnumbers, or not yet run). Writing that into a Touchstone file
    # would silently produce a corrupt/incomplete result, so check for it up front and fail
    # clearly instead.
    missing = set()
    if matrixsize == 1:
        if any(Smatrix[0, index] is None for index in range(numfreq)):
            missing.add('S11')
    else:
        for j in range(0, matrixsize):
            for i in range(0, matrixsize):
                if any(Smatrix[i, j, index] is None for index in range(numfreq)):
                    missing.add(f'S{i+1}{j+1}')
    if missing:
        raise ValueError(
            'Cannot write Touchstone file: the following S-parameter(s) were never computed - '
            + ', '.join(sorted(missing)) +
            '. This happens when a port was never excited (voltage=0, excluded from '
            'excite_portnumbers, or its simulation has not been run yet). Exclude that port, '
            'or make sure it is actually excited, before writing the .sNp file.'
        )

    print('Creating  S-parameter file')

    with open(filename, 'w') as snp_file:
        snp_file.write(f'#   Hz   S  RI   R   {z0:g}\n')
        snp_file.write('!\n')

        # address elements as Sij
        for index in range(0, numfreq):
            freq = f[index]
            line = f"{freq:.6e}"

            if matrixsize==1:
                #1-port data
                line = line + f" {Smatrix[0,index].real:.6e} {Smatrix[0,index].imag:.6e}"
            elif matrixsize==2:
                # 2-port data: one line in the order S11 S21 S12 S22 (Touchstone special case)
                for j in range(0,matrixsize):
                    for i in range(0,matrixsize):
                        line = line + f" {Smatrix[i, j, index].real:.6e} {Smatrix[i, j, index].imag:.6e}"
            else:
                # 3 ports and more: matrix row-wise (S11 S12 S13 ...), each row on a new line, and
                # at most 4 pairs per line, as required by the Touchstone 1.x format
                rows = []
                for i in range(0,matrixsize):
                    pairs = [f" {Smatrix[i, j, index].real:.6e} {Smatrix[i, j, index].imag:.6e}" for j in range(0,matrixsize)]
                    rows += [''.join(pairs[k:k+4]) for k in range(0, matrixsize, 4)]
                line = line + ('\n' + ' ' * len(line)).join(rows)

            snp_file.write(line + '\n')




