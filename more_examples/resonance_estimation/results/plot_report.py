"""Plots and tables for the resonance estimation report (README.md in the folder above).

Reads the openEMS output of run_L6n2_energy_limit.py (../output/run_L6n2_energy_limit_<case>_data):
the port time signals, the extended signals written by resonance estimation, the solve times and the
Touchstone files. Copies the Touchstone files to results/, writes the plots to results/plots/ and prints
the tables of the README.

usage: python plot_report.py
"""
import glob
import math
import os
import re
import shutil

import numpy as np
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
import skrf as rf

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'output')
PLOTS = os.path.join(HERE, 'plots')
BASENAME = 'run_L6n2_energy_limit_'

INK, INK2, GRID, SURF = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
# case, label, color, linestyle; fixed colors per case in all plots
CASES = [('limit-40', 'end criterion −40 dB', '#2a78d6', '--'),
         ('limit-50', 'end criterion −50 dB', '#eb6834', '-.'),
         ('limit-60', 'end criterion −60 dB', '#1baf7a', '-'),
         ('resonance_estimation', 'resonance estimation', '#4a3aa7', '-'),
         ('limit-90', 'end criterion −90 dB (reference)', INK2, ':')]
STYLE = {c: (label, color, ls) for c, label, color, ls in CASES}


def data_path(case):
    return os.path.join(OUT, BASENAME + case + '_data')


def read_probe(path):
    d = np.loadtxt(path, comments='%')
    return d[:, 0], d[:, 1]


def solve_time(case):
    total = 0
    for f in glob.glob(os.path.join(data_path(case), 'sub-*', 'time_information.txt')):
        total += int(re.search(r'solve time for this excitation: (\d+)', open(f).read()).group(1))
    return total


def stop_time(case, sub=1):
    t, _ = read_probe(os.path.join(data_path(case), f'sub-{sub}', 'port_ut_1'))
    return t[-1]


def network(case):
    snp = os.path.join(data_path(case), BASENAME + case + '.s2p')
    shutil.copy(snp, HERE)
    return rf.Network(snp)


def inductor(nw):
    """Differential series impedance of the inductor between its two ports: R, L, Q against frequency."""
    z = nw.z
    zdiff = z[:, 0, 0] - z[:, 0, 1] - z[:, 1, 0] + z[:, 1, 1]
    f = nw.frequency.f
    ok = f > 0
    f, zdiff = f[ok], zdiff[ok]
    return f, zdiff.real, zdiff.imag / (2 * math.pi * f), zdiff.imag / zdiff.real


def style(ax):
    ax.set_facecolor(SURF)
    ax.grid(True, color=GRID, lw=0.8)
    ax.tick_params(colors=INK2, labelsize=8)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.xaxis.label.set_color(INK2)
    ax.yaxis.label.set_color(INK2)


def figure(nrows, ncols, size):
    fig, axes = plt.subplots(nrows, ncols, figsize=size, dpi=150, facecolor=SURF, squeeze=False)
    for ax in axes.flat:
        style(ax)
    return fig, axes


def plot_time_signals():
    """The problem: port 2 voltage of the -90 dB run, with the points where the other runs stop."""
    t, u = read_probe(os.path.join(data_path('limit-90'), 'sub-1', 'port_ut_2'))
    te, e = read_probe(os.path.join(data_path('limit-90'), 'sub-1', 'et'))
    t_pulse = te[-1]
    ps = t * 1e12
    db = 20 * np.log10(abs(u) / abs(u).max() + 1e-30)
    fig, axes = figure(2, 1, (7.5, 6.6))
    ax1, ax2 = axes[:, 0]
    ax1.plot(ps, db, color=INK2, lw=1.5)
    ax2.plot(ps, u * 1e6, color=INK2, lw=1.5, label='port 2 voltage (−90 dB run)')
    for case in ('limit-40', 'limit-50', 'limit-60'):
        label, color, _ = STYLE[case]
        ts = stop_time(case)
        i = np.searchsorted(t, ts)
        for ax, y in ((ax1, db[i]), (ax2, u[i] * 1e6)):
            ax.plot(ts * 1e12, y, 'X', color=color, ms=9, mec='white', mew=1, zorder=5,
                    label=label + f': stops at {ts * 1e12:.0f} ps' if ax is ax2 else None)
    for ax in (ax1, ax2):
        ax.axvline(t_pulse * 1e12, color=INK, lw=0.8, ls=':')
    ax1.text(t_pulse * 1e12 + 8, -10, 'excitation pulse\nends', fontsize=8, color=INK2, va='top')
    ax1.set_ylim(-120, 5)
    ax1.set_xlim(0, ps[-1])
    ax1.set_ylabel('|u2| (dB rel. max)')
    ax1.set_title('Port 2 voltage, port 1 excited: log scale', fontsize=10, color=INK, loc='left')
    ts40 = stop_time('limit-40')
    cut = t >= ts40
    ax2.fill_between(ps[cut], u[cut] * 1e6, 0, color=STYLE['limit-40'][1], alpha=0.18, lw=0,
                     label='cut off by the −40 dB run: its area is the missing low-frequency content')
    ax2.set_xlim(380, 830)
    ax2.set_ylim(-0.07, 0.015)
    ax2.axhline(0, color=INK, lw=0.8)
    ax2.set_ylabel('u2 (µV)')
    ax2.set_xlabel('Time (ps)')
    ax2.set_title('Zoom after the pulse, linear scale: the signal has not returned to zero', fontsize=10,
                  color=INK, loc='left')
    ax2.legend(fontsize=8, frameon=False, loc='lower right')
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, 'time_signals.png'), facecolor=SURF)
    plt.close(fig)


def plot_rlq(cases, name, title):
    fig, axes = figure(1, 3, (11, 3.8))
    for case in cases:
        label, color, ls = STYLE[case]
        f, R, L, Q = inductor(network(case))
        for ax, y in zip(axes[0], (R, L * 1e9, Q)):
            ax.plot(f / 1e9, y, color=color, ls=ls, lw=1.6, label=label)
    for ax, yl in zip(axes[0], ('R (Ω)', 'L (nH)', 'Q')):
        ax.set_xlabel('Frequency (GHz)')
        ax.set_ylabel(yl)
        ax.set_xlim(0, 14)
    axes[0, 0].set_ylim(0, 12)
    axes[0, 1].set_ylim(4, 8)
    axes[0, 2].set_ylim(0, 16)
    axes[0, 0].legend(fontsize=8, frameon=False, loc='upper left')
    fig.suptitle(title, fontsize=10, color=INK, x=0.01, ha='left')
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, name), facecolor=SURF)
    plt.close(fig)


def plot_extrapolated_tail():
    """Resonance estimation: recorded signal, extrapolated tail, and the -90 dB run for comparison."""
    t90, u90 = read_probe(os.path.join(data_path('limit-90'), 'sub-1', 'port_ut_2'))
    sub = os.path.join(data_path('resonance_estimation'), 'sub-1')
    tr, ur = read_probe(os.path.join(sub, 'port_ut_2'))
    tx, ux = read_probe(os.path.join(sub, 'resonance_estimation', 'port_ut_2'))
    ref = abs(u90).max()
    db = lambda u: 20 * np.log10(abs(u) / ref + 1e-30)
    tail = tx > tr[-1]
    fig, axes = figure(1, 1, (7.5, 3.8))
    ax = axes[0, 0]
    ax.plot(t90 * 1e12, db(u90), color=INK2, lw=4, alpha=0.35, label='−90 dB run (for comparison)')
    ax.plot(tr * 1e12, db(ur), color=STYLE['resonance_estimation'][1], lw=1.6,
            label=f'recorded until openEMS was stopped ({tr[-1] * 1e12:.0f} ps)')
    ax.plot(tx[tail] * 1e12, db(ux[tail]), color=STYLE['resonance_estimation'][1], lw=1.6, ls='--',
            label='extrapolated by resonance estimation')
    ax.axvline(tr[-1] * 1e12, color=INK, lw=0.8, ls=':')
    ax.set_xlim(0, t90[-1] * 1e12)
    ax.set_ylim(-140, 5)
    ax.set_xlabel('Time (ps)')
    ax.set_ylabel('|u2| (dB rel. max)')
    ax.set_title('Port 2 voltage, port 1 excited', fontsize=10, color=INK, loc='left')
    ax.legend(fontsize=8, frameon=False, loc='upper right')
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, 'extrapolated_tail.png'), facecolor=SURF)
    plt.close(fig)


def plot_accuracy():
    """S-parameter error against the -90 dB run, worst of the four S-parameters at each frequency."""
    ref = network('limit-90')
    fig, axes = figure(1, 1, (7.5, 3.8))
    ax = axes[0, 0]
    for case in ('limit-40', 'limit-50', 'limit-60', 'resonance_estimation'):
        label, color, ls = STYLE[case]
        nw = network(case)
        err = abs(nw.s - ref.s).max(axis=(1, 2))
        ax.semilogy(nw.frequency.f / 1e9, err, color=color, ls=ls, lw=1.6,
                    label=f'{label}, {solve_time(case)} s')
    ax.set_xlim(0, 14)
    ax.set_ylim(1e-6, 3e-2)
    ax.set_xlabel('Frequency (GHz)')
    ax.set_ylabel('max |ΔS| vs. −90 dB run')
    ax.set_title('S-parameter error and openEMS solve time (both excitations)', fontsize=10, color=INK, loc='left')
    ax.legend(fontsize=8, frameon=False, loc='upper right')
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, 'accuracy.png'), facecolor=SURF)
    plt.close(fig)


def at(f, y, fx):
    return np.interp(fx, f, y)


def table():
    ref = network('limit-90')
    t60 = solve_time('limit-60')
    print('| Run | Stops at | Solve time | R @ 0.1 GHz | R @ 1 GHz | L @ 1 GHz | Peak Q | SRF | max |ΔS| |')
    print('|---|---|---|---|---|---|---|---|---|')
    for case, label, _, _ in CASES:
        nw = network(case)
        f, R, L, Q = inductor(nw)
        down = np.where(np.diff(np.sign(L)) < 0)[0]               # SRF: Im(Zdiff) crosses zero
        srf = f[down[0]] if len(down) else np.nan
        k = np.argmax(np.where(f < srf, Q, -np.inf))
        stops = ', '.join(f'{stop_time(case, s) * 1e12:.0f}' for s in (1, 2))
        ds = abs(nw.s - ref.s).max()
        print(f'| {label} | {stops} ps | {solve_time(case)} s ({solve_time(case) / t60:.2f}×) | {at(f, R, 0.1e9):.2f} Ω | '
              f'{at(f, R, 1e9):.2f} Ω | {at(f, L, 1e9) * 1e9:.2f} nH | {Q[k]:.2f} @ {f[k] / 1e9:.2f} GHz | '
              f'{srf / 1e9:.2f} GHz | {ds:.1e} |')
    for sub in (1, 2):
        log = os.path.join(data_path('resonance_estimation'), f'sub-{sub}', 'resonance_estimation.txt')
        print('\n' + open(log).read())


def main():
    os.makedirs(PLOTS, exist_ok=True)
    plot_time_signals()
    plot_rlq(['limit-40', 'limit-50', 'limit-60', 'limit-90'], 'energy_limit_RLQ.png',
             'L6n2 inductor: R, L and Q for different end criteria')
    plot_extrapolated_tail()
    plot_accuracy()
    table()


if __name__ == '__main__':
    main()
