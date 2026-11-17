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


def run(name, label, **style):
    """(path, label, style): style overrides the plot's color/line style/width for this curve"""
    return (os.path.join(res, name + ".s2p"), label, style)


BOLD = dict(color='g', linestyle='solid', linewidth=2.5)   # the 0.5 µm models: the best result, easy to miss otherwise


MEAS = (os.path.join(study_dir, "meas_L5_6n2_THRU_deemb.S2P"), "Measured (de-embedded)", {})
MESH1 = run("run_L6n2_mesh1", "Sim: via merge, no correction, 1 µm mesh")
E40 = run("run_L6n2_mergecorrection_sweep_mesh1_limit-40", "Sim: end criterion -40 dB")
E40_CORR = run("run_L6n2_mergecorrection_sweep_mesh1_limit-40", "Sim: via merge + correction, 1 µm mesh")
E50 = run("run_L6n2_mergecorrection_sweep_mesh1_limit-50", "Sim: end criterion -50 dB")
E60 = run("run_L6n2_mergecorrection_sweep_mesh1_limit-60", "Sim: end criterion -60 dB")
PLANAR_2UM = run("run_L6n2_mergecorrection_sweep_mesh2_limit-60", "Sim: planar passivation, 2 µm mesh")
PASSICUT_2UM = run("run_L6n2_mergecorrection_passicut_sweep_mesh2_limit-60", "Sim: passivation cut, 2 µm mesh")
PASSICUT_1UM = run("run_L6n2_mergecorrection_passicut_sweep_mesh1_limit-60", "Sim: passivation cut, 1 µm mesh")
M60_2UM = run("run_L6n2_mergecorrection_sweep_mesh2_limit-60", "Sim: 2 µm mesh, -60 dB")
M60_1UM = run("run_L6n2_mergecorrection_sweep_mesh1_limit-60", "Sim: 1 µm mesh, -60 dB")
M60_0U5 = run("run_L6n2_mergecorrection_mesh0u5", "Sim: 0.5 µm mesh, -60 dB", **BOLD)
PASSICUT_0U5 = run("run_L6n2_mergecorrection_passicut_sweep_mesh0.5_limit-60", "Sim: passivation cut, 0.5 µm mesh", **BOLD)
OEMS_FINAL = run("run_L6n2_mergecorrection_passicut_sweep_mesh0.5_limit-60", "openEMS: passivation cut, 0.5 µm mesh, −60 dB")
PALACE_V5 = run("palace_L6n2_v5_2um_passicut", "Palace 0.19: PassiCut, filled metals, 2 µm mesh")
# the box (step 0): air around in µm, 250 µm margin, the final model; the 750 µm wafer on the chuck as a check
BOX = "run_L6n2_mergecorrection_passicut_boundary_mesh1_"
AIR = (0, 100, 200, 400, 800, 1600)
AIR_FILES = [BOX + f"m250_a{air}" for air in AIR]
WAFER = (BOX + "w750_m250_a800", 800, "750 µm wafer on the chuck, 800 µm air (not below)")

PLOTS = {
    "step1_via_merge_correction.png": [MEAS, MESH1, E40_CORR],
    "step2_energy_limit.png": [MEAS, E40, E50, E60],
    "step3_mesh.png": [MEAS, M60_2UM, M60_1UM, M60_0U5],
    "step4_passicut_2um.png": [MEAS, PLANAR_2UM, PASSICUT_2UM],
    "step4_passicut_mesh.png": [MEAS, PASSICUT_2UM, PASSICUT_1UM, PASSICUT_0U5],
    "openems_vs_palace.png": [MEAS, OEMS_FINAL, PALACE_V5],
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
    for path, label, style in entries:
        nw = rf.Network(path)
        networks.append((nw, label, style))
        global_fmax = min(global_fmax, max(nw.frequency.f))
    fspec = str(int(100e6 / 1e6)) + '-' + str(int(global_fmax / 1e6)) + 'mhz'

    Lmin, Rmin, Qmax = math.inf, math.inf, 0
    for nw, _, _ in networks:
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
        for n, (nw, label, style) in enumerate(networks):
            freq, R, L, Q = get_diff_model(nw[fspec])
            ax.plot(freq / 1e9, value(freq, R, L, Q), label=label,
                    **{"color": colors[n % 8], "linestyle": linestyles[n % 8], **style})
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel(ylabel)
        ax.set_xmargin(0)
        ax.legend(fontsize=9)
        ax.grid()
    fig.tight_layout()
    fig.savefig(out_path, dpi=125)
    plt.close(fig)
    print("wrote", out_path)


def plot_ripple(reference, others, pulse_center_ps, out_path, fmax_ghz=8):
    """Difference in differential resistance of each run vs. a reference run of the same model.
    others: list of (path, label, stop_time_ps). S-parameters are referenced to the incident pulse,
    so the ripple period is 1/(stop time - pulse center), with a zero crossing every half period."""
    ref = rf.Network(reference[0])
    fr, Rr, _, _ = get_diff_model(ref['100-' + str(int(max(ref.frequency.f) / 1e6)) + 'mhz'])
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.axhline(0, color='k', linewidth=0.8)
    for n, (path, label, stop_ps) in enumerate(others):
        nw = rf.Network(path)
        freq, R, _, _ = get_diff_model(nw['100-' + str(int(max(nw.frequency.f) / 1e6)) + 'mhz'])
        m = freq <= fmax_ghz * 1e9
        dR = (R - Rr)[m]
        ymax = max(ymax, abs(dR).max()) if n else abs(dR).max()
        ax.plot(freq[m] / 1e9, dR, color=colors[n % 8], linestyle=linestyles[n % 8],
                label=f"{label}: stops {stop_ps - pulse_center_ps:.0f} ps after pulse center, "
                      f"expected ripple period {1e3 / (stop_ps - pulse_center_ps):.1f} GHz")
    ax.set_xlim(0, fmax_ghz)
    ax.set_ylim(-1.2 * ymax, 1.2 * ymax)
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("Diff. resistance minus " + reference[1] + " (Ohm)")
    ax.set_title("Truncation ripple: difference to the " + reference[1] + " run")
    ax.legend(fontsize=9)
    ax.grid()
    fig.tight_layout()
    fig.savefig(out_path, dpi=125)
    plt.close(fig)
    print("wrote", out_path)


def figures_of_merit(path):
    """L at 1 GHz (nH), peak Q and SRF (GHz, first zero crossing of Im Zdiff) of a 2-port file"""
    nw = rf.Network(path)
    freq, R, L, Q = get_diff_model(nw['100-' + str(int(max(nw.frequency.f) / 1e6)) + 'mhz'])
    X = L * 2 * math.pi * freq
    k = next(i for i in range(len(X) - 1) if X[i] > 0 >= X[i + 1])
    srf = freq[k] - X[k] * (freq[k + 1] - freq[k]) / (X[k + 1] - X[k])
    L1 = L[min(range(len(freq)), key=lambda i: abs(freq[i] - 1e9))]
    return L1 * 1e9, max(Q), srf / 1e9


def plot_air_sweep(air, files, wafer, out_path):
    """Change of L at 1 GHz, peak Q and SRF against air around 0, one point per air value (equally spaced), and the
    750 µm wafer on the chuck as a single marker"""
    values = [figures_of_merit(os.path.join(res, name + ".s2p")) for name in files]
    ref = values[0]
    w = figures_of_merit(os.path.join(res, wafer[0] + ".s2p"))
    x = list(range(len(air)))
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    for ax, k, title in zip(axes, range(3), ("L at 1 GHz", "peak Q", "SRF")):
        changes = [100 * (v[k] / ref[k] - 1) for v in values]
        ax.plot(x, changes, color=colors[0], marker="o", label="250 µm margin, air on all sides")
        ax.plot([x[air.index(wafer[1])]], [100 * (w[k] / ref[k] - 1)], color=colors[1], marker="s", linestyle="",
                label=wafer[2])
        ax.axhline(0, color="k", linewidth=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels([str(a) for a in air])
        ax.set_xlabel("Air around (µm)")
        ax.set_ylabel("Change against no air (%)")
        ax.set_title(title)
        ax.set_ylim(-2.5, 2.5)
        ax.grid()
    axes[0].legend(fontsize=9, loc="lower right")
    fig.suptitle("Simulation box: 250 µm margin, air around added on all sides (1 µm mesh, passivation cut, −60 dB)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=125)
    plt.close(fig)
    print("wrote", out_path)


os.makedirs(out_dir, exist_ok=True)
for name, entries in PLOTS.items():
    plot(entries, os.path.join(out_dir, name))
plot_air_sweep(list(AIR), AIR_FILES, WAFER, os.path.join(out_dir, "step0_box_air.png"))

# stop times from the end of the port probe signals, see plot_time_signals.py
plot_ripple((E60[0], "-60 dB"),
            [(E40[0], "end criterion -40 dB", 419.6), (E50[0], "end criterion -50 dB", 535.7)],
            204.7,  # center of the 409 ps fstop 14 GHz excitation pulse
            os.path.join(out_dir, "step2_ripple.png"))
