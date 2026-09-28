"""Regenerate the L6n2 openEMS study's differential L/Q/R plots.

Same calculation, axis limits, colors and line styles as the gds2palace L6n2 study
(gds2palace_ihp_sg13g2/more_examples/measured_vs_simulated/more_accurate_models_L6n2/results/plot_study.py),
so the plots of both studies compare directly.

usage: python plot_study.py [study_dir] [out_dir]
defaults: the study folder this script sits in (results/..), and results/plots
"""
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
import skrf as rf

here = os.path.dirname(os.path.abspath(__file__))
study_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(here)
out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "plots")
res = os.path.join(study_dir, "results")


def run(name, label):
    return (os.path.join(res, name + ".s2p"), label)


MEAS = (os.path.join(study_dir, "meas_L5_6n2_THRU_deemb.S2P"), "Measured (de-embedded)")
MESH1 = run("run_L6n2_mesh1", "Sim: via merge, no correction, 1 µm mesh")
MESH1_CORR = run("run_L6n2_mesh1_mergecorrection", "Sim: via merge + correction, 1 µm mesh")
MESH2_CORR = run("run_L6n2_mesh2_mergecorrection", "Sim: via merge + correction, 2 µm mesh")
MESH0U5_CORR = run("run_L6n2_mesh0u5_mergecorrection", "Sim: via merge + correction, 0.5 µm mesh")
E40 = run("run_L6n2_mergecorrection_sweep_mesh1_limit-40", "Sim: end criterion -40 dB")
E50 = run("run_L6n2_mergecorrection_sweep_mesh1_limit-50", "Sim: end criterion -50 dB")
E60 = run("run_L6n2_mergecorrection_sweep_mesh1_limit-60", "Sim: end criterion -60 dB")
PLANAR_2UM = run("run_L6n2_mergecorrection_sweep_mesh2_limit-60", "Sim: planar passivation, 2 µm mesh")
PASSICUT_2UM = run("run_L6n2_mergecorrection_passicut_sweep_mesh2_limit-60", "Sim: passivation cut, 2 µm mesh")
PASSICUT_1UM = run("run_L6n2_mergecorrection_passicut_sweep_mesh1_limit-60", "Sim: passivation cut, 1 µm mesh")
OEMS_2UM = run("run_L6n2_mergecorrection_passicut_sweep_mesh2_limit-60", "openEMS: passivation cut, 2 µm mesh, -60 dB")
PALACE_REC = run("palace_L6n2_with_ports_2um_passi3D", "Palace: conformal passivation, filled metals, 2 µm mesh")

PLOTS = {
    "step1_via_merge_correction.png": [MEAS, MESH1, MESH1_CORR],
    "step2_mesh.png": [MEAS, MESH2_CORR, MESH1_CORR, MESH0U5_CORR],
    "step3_energy_limit.png": [MEAS, E40, E50, E60],
    "step4_passicut_2um.png": [MEAS, PLANAR_2UM, PASSICUT_2UM],
    "step4_passicut_1um.png": [MEAS, PASSICUT_2UM, PASSICUT_1UM],
    "openems_vs_palace.png": [MEAS, OEMS_2UM, PALACE_REC],
}

colors = ['b', 'r', 'm', 'c', 'g', 'y', 'k', 'w']
linestyles = ['solid', 'dashed', 'dashdot', 'dotted', 'solid', 'dashed', 'dashdot', 'dotted']


def get_diff_model(sub):
    z11 = sub.z[:, 0, 0]
    z21 = sub.z[:, 1, 0]
    z12 = sub.z[:, 0, 1]
    z22 = sub.z[:, 1, 1]
    Zdiff = z11 - z12 - z21 + z22
    freq = sub.frequency.f
    omega = freq * 2 * math.pi
    return freq, Zdiff.real, Zdiff.imag / omega, Zdiff.imag / Zdiff.real


def plot(entries, out_path):
    networks = []
    global_fmax = math.inf
    for path, label in entries:
        nw = rf.Network(path)
        networks.append((nw, label))
        global_fmax = min(global_fmax, max(nw.frequency.f))
    fspec = str(int(100e6 / 1e6)) + '-' + str(int(global_fmax / 1e6)) + 'mhz'

    Lmin, Rmin, Qmax = math.inf, math.inf, 0
    for nw, _ in networks:
        freq0, Rdiff0, Ldiff0, Qdiff0 = get_diff_model(nw[fspec])
        Lmin = min(Lmin, Ldiff0[1] * 1e9)
        Rmin = min(Rmin, Rdiff0[1])
        Qmax = max(Qmax, max(Qdiff0))
    # like plot_inductor: SRF-based x range from the LAST file's data
    srf_index = rf.util.find_nearest_index(Ldiff0, min(Ldiff0))
    plot_fmax_ghz = 1.2 * freq0[srf_index] / 1e9 if srf_index > 20 else global_fmax / 1e9

    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle("Differential Inductor Parameters")
    panels = [
        (axes[0, 0], lambda f, R, L, Q: L * 1e9, "Diff. Inductance (nH)", (0, 3 * Lmin), plot_fmax_ghz),
        (axes[0, 1], lambda f, R, L, Q: Q, "Diff. Q factor", (0, 1.2 * Qmax), plot_fmax_ghz),
        (axes[1, 0], lambda f, R, L, Q: R, "Diff. Resistance (Ohm)", (0, 5 * Rmin), plot_fmax_ghz),
        (axes[1, 1], lambda f, R, L, Q: R, "Diff. Resistance (Ohm)", (0.5 * Rmin, 3 * Rmin), 4.0),  # low-frequency detail, fixed 4 GHz
    ]
    for ax, value, ylabel, ylim, xmax in panels:
        ax.set_ylim(*ylim)
        ax.set_xlim(0, xmax)
        for n, (nw, label) in enumerate(networks):
            freq, R, L, Q = get_diff_model(nw[fspec])
            ax.plot(freq / 1e9, value(freq, R, L, Q), color=colors[n % 8], linestyle=linestyles[n % 8], label=label)
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel(ylabel)
        ax.set_xmargin(0)
        ax.legend(fontsize=9)
        ax.grid()
    fig.tight_layout()
    fig.savefig(out_path, dpi=125)
    plt.close(fig)
    print("wrote", out_path)


os.makedirs(out_dir, exist_ok=True)
for name, entries in PLOTS.items():
    plot(entries, os.path.join(out_dir, name))
