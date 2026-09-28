"""Excitation spectrum and port voltage (time domain) plots for Step 3 of the L6n2 openEMS study.

Reads the raw openEMS time signals (sub-1/et, sub-1/port_ut_1/2) of the planar sweep at 1 um mesh,
end criteria -40, -50 and -60 dB, from output/<run>_data. These folders are not in git (output/ is
ignored); rerun run_L6n2_mergecorrection_sweep.py first.
Writes results/plots/L6n2_excitation_spectrum.png, L6n2_port_voltages_time_domain.png and
L6n2_port_voltages_time_domain_linear.png.

usage: python plot_time_signals.py
"""
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

here = os.path.dirname(os.path.abspath(__file__))
plots = os.path.join(here, 'plots')
os.makedirs(plots, exist_ok=True)
os.chdir(os.path.join(os.path.dirname(here), 'output'))

INK, INK2, GRID, SURF = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
# (data dir, label, color, linestyle, marker); fixed categorical color order
RUNS = [('run_L6n2_mergecorrection_sweep_mesh1_limit-40_data', 'end criterion −40 dB', '#2a78d6', '--', 'o'),
        ('run_L6n2_mergecorrection_sweep_mesh1_limit-50_data', 'end criterion −50 dB', '#eb6834', '-.', 's'),
        ('run_L6n2_mergecorrection_sweep_mesh1_limit-60_data', 'end criterion −60 dB', '#1baf7a', '-', '^')]
# longest run first, so the shorter (identical until they stop) runs stay visible on top
DRAW_ORDER = (RUNS[2], RUNS[1], RUNS[0])
FSTOP = 14e9


def style(ax):
    ax.set_facecolor(SURF)
    ax.grid(True, color=GRID, lw=0.8)
    ax.tick_params(colors=INK2, labelsize=8)
    for s in ax.spines.values():
        s.set_color(GRID)


def pulse_end_ps():
    t = np.loadtxt(os.path.join(RUNS[0][0], 'sub-1', 'et'), usecols=0)
    return t[-1]*1e12


def legend_in_run_order(ax, **kw):
    h, l = ax.get_legend_handles_labels()
    order = [l.index(r[1]) for r in RUNS]
    ax.legend([h[i] for i in order], [l[i] for i in order], **kw)


def excitation_spectrum():
    t, e = np.loadtxt(os.path.join(RUNS[0][0], 'sub-1', 'et'), unpack=True)
    dt = np.diff(t).mean()
    f = np.arange(0, 30.001e9, 0.02e9)
    E = np.array([np.sum(e*np.exp(-2j*np.pi*fi*t))*dt for fi in f])   # direct DFT, fine df at low f
    P = np.abs(E)**2
    PdB = 10*np.log10(P/P.max())
    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=150, facecolor=SURF)
    style(ax)
    ax.plot(f/1e9, PdB, color=RUNS[0][2], lw=2)
    ax.axvline(FSTOP/1e9, color=INK2, lw=1, ls=':')
    ax.text(FSTOP/1e9, -57, ' fstop 14 GHz', color=INK2, fontsize=8, va='bottom')
    k = np.argmin(abs(f - 0.1e9))
    ax.plot(f[k]/1e9, PdB[k], 'o', ms=6, color=RUNS[0][2], mec=SURF, mew=2)
    ax.text(0.4, PdB[k] - 3, f'{PdB[k]:.1f} dB at 0.1 GHz', color=INK, fontsize=8)
    ax.set_xlim(0, 30)
    ax.set_ylim(-60, 5)
    ax.set_xlabel('Frequency (GHz)', color=INK2)
    ax.set_ylabel('Excitation power (dB rel. peak)', color=INK2)
    ax.set_title(f'L6n2 openEMS excitation power spectrum, fstop 14 GHz ({t[-1]*1e12:.0f} ps pulse)',
                 fontsize=10, color=INK, loc='left')
    fig.tight_layout()
    out = os.path.join(plots, 'L6n2_excitation_spectrum.png')
    fig.savefig(out, facecolor=SURF)
    plt.close(fig)
    print(out)


def port_voltages_db():
    texc = pulse_end_ps()
    fig, axes = plt.subplots(2, 1, figsize=(8, 6.4), dpi=150, sharex=True, facecolor=SURF)
    for p, ax in zip((1, 2), axes):
        style(ax)
        data = {r[0]: np.loadtxt(f'{r[0]}/sub-1/port_ut_{p}', comments='%') for r in RUNS}
        ref = max(np.abs(d[:, 1]).max() for d in data.values())
        for d, label, col, ls, mk in DRAW_ORDER:
            t, u = data[d][:, 0]*1e12, data[d][:, 1]
            udb = 20*np.log10(np.abs(u)/ref + 1e-12)
            top = d != RUNS[2][0]
            ax.plot(t, udb, color=col, lw=2.4 if top else 2, ls=ls, marker=mk, ms=4, mfc=col, mec=SURF, mew=1,
                    zorder=3 if top else 2, label=label)
            ax.plot(t[-1], udb[-1], marker='X', ms=10, color=col, mec=SURF, mew=1.5, zorder=5)
        ax.axvline(texc, color=INK2, lw=1, ls=':')
        ax.set_ylim(-120, 5)
        ax.set_xlim(0, 800)
        ax.set_ylabel(f'|u{p}| (dB rel. max)', color=INK2)
        ax.set_title(f'Port {p} voltage' + (' (excited port)' if p == 1 else ' (receiving port)') + ', port 1 excitation',
                     fontsize=9, color=INK, loc='left')
    axes[0].text(texc + 2, -115, ' pulse end', color=INK2, fontsize=7, rotation=90, va='bottom')
    legend_in_run_order(axes[0], loc='upper right', fontsize=8, frameon=False, labelcolor=INK,
                        title='X = run stops', title_fontsize=7)
    axes[1].annotate('all runs are identical\nuntil each one stops', (402, -38), xytext=(455, -12), fontsize=8, color=INK,
                     arrowprops=dict(arrowstyle='-', color=INK2, lw=0.8))
    axes[1].set_xlabel('Time (ps)', color=INK2)
    fig.suptitle('L6n2 openEMS port voltages, 1 µm mesh: the −40 dB run stops at the end of the excitation pulse',
                 x=0.02, ha='left', fontsize=10, color=INK)
    fig.tight_layout()
    out = os.path.join(plots, 'L6n2_port_voltages_time_domain.png')
    fig.savefig(out, facecolor=SURF)
    plt.close(fig)
    print(out)


def port_voltages_linear(zoom_from=380):
    texc = pulse_end_ps()
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.4), dpi=150, facecolor=SURF, gridspec_kw={'width_ratios': [3, 2]})
    for row, p in enumerate((1, 2)):
        full, zoom = axes[row]
        style(full)
        style(zoom)
        data = {r[0]: np.loadtxt(f'{r[0]}/sub-1/port_ut_{p}', comments='%') for r in RUNS}
        for d, label, col, ls, mk in DRAW_ORDER:
            t, u = data[d][:, 0]*1e12, data[d][:, 1]*1e6   # ps, uV
            top = d != RUNS[2][0]
            kw = dict(color=col, lw=2.4 if top else 1.8, ls=ls, marker=mk, ms=3.5, mfc=col, mec=SURF, mew=0.8,
                      zorder=3 if top else 2)
            full.plot(t, u, label=label, **kw)
            zoom.plot(t, u, **kw)
            for a in (full, zoom):
                a.plot(t[-1], u[-1], marker='X', ms=9, color=col, mec=SURF, mew=1.2, zorder=5)
        for a in (full, zoom):
            a.axvline(texc, color=INK2, lw=1, ls=':')
            a.axhline(0, color=INK2, lw=0.6)
        tail = data[RUNS[2][0]]
        tt, uu = tail[:, 0]*1e12, tail[:, 1]*1e6
        lim = np.abs(uu[tt > zoom_from]).max()*1.15
        zoom.set_xlim(zoom_from, 790)
        zoom.set_ylim(-lim, lim)
        full.set_xlim(0, 800)
        full.axvspan(zoom_from, 800, color=GRID, alpha=0.35, lw=0)
        full.set_ylabel(f'u{p} (µV)', color=INK2)
        full.set_title(f'Port {p} voltage' + (' (excited port)' if p == 1 else ' (receiving port)') + ', port 1 excitation',
                       fontsize=9, color=INK, loc='left')
        zoom.set_title(f'zoom: after {zoom_from} ps (shaded on the left)', fontsize=9, color=INK2, loc='left')
    axes[1][0].set_xlabel('Time (ps)', color=INK2)
    axes[1][1].set_xlabel('Time (ps)', color=INK2)
    h, l = axes[0][0].get_legend_handles_labels()
    order = [l.index(r[1]) for r in RUNS]
    fig.legend([h[i] for i in order], [l[i] for i in order], loc='upper left', ncol=3, fontsize=8, frameon=False,
               labelcolor=INK, bbox_to_anchor=(0.01, 0.945))
    fig.suptitle('L6n2 openEMS port voltages, 1 µm mesh, linear scale (X = run stops, dotted = pulse end)',
                 x=0.01, y=0.975, ha='left', fontsize=10, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    out = os.path.join(plots, 'L6n2_port_voltages_time_domain_linear.png')
    fig.savefig(out, facecolor=SURF)
    plt.close(fig)
    print(out)


def summary():
    et = np.loadtxt(os.path.join(RUNS[0][0], 'sub-1', 'et'))
    dt = et[1, 0] - et[0, 0]
    print(f'time step {dt*1e15:.3f} fs, pulse {et[-1, 0]*1e12:.1f} ps = {len(et)} steps')
    for d, label, *_ in RUNS:
        u2 = np.loadtxt(f'{d}/sub-1/port_ut_2', comments='%')
        u1 = np.loadtxt(f'{d}/sub-1/port_ut_1', comments='%')
        tend = u2[-1, 0]
        print(f'{label.replace(chr(0x2212), "-")}: stops at {tend*1e12:.1f} ps = {tend/dt/1e3:.0f} k steps, '
              f'last |u2| {-20*np.log10(abs(u2[-1, 1])/abs(u2[:, 1]).max()):.1f} dB below max')
    u = np.loadtxt(f'{RUNS[2][0]}/sub-1/port_ut_1', comments='%')
    for p in (1, 2):
        u = np.loadtxt(f'{RUNS[2][0]}/sub-1/port_ut_{p}', comments='%')
        m = (u[:, 0] > 420e-12) & (u[:, 0] < 520e-12)
        tau = -1/np.polyfit(u[m, 0], np.log(np.abs(u[m, 1])), 1)[0]
        print(f'port {p}: tail time constant 420-520 ps = {tau*1e12:.1f} ps, peak {np.abs(u[:, 1]).max()*1e6:.1f} uV, '
              f'at 420 ps {np.interp(420e-12, u[:, 0], np.abs(u[:, 1]))*1e6:.3f} uV')


excitation_spectrum()
port_voltages_db()
port_voltages_linear()
summary()
