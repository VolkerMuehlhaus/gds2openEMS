"""Excitation spectrum and port voltage (time domain) plots for Step 3 of the L6n2 openEMS study.

Reads the raw openEMS time signals (sub-1/et, sub-1/port_ut_1/2) from output/<run>_data. These folders are
not in git (output/ is ignored); rerun run_L6n2_mesh1_mergecorrection.py and run_L6n2_mergecorrection_sweep.py first.
Writes results/plots/L6n2_excitation_spectrum_fstop14_vs_20.png, L6n2_port_voltages_time_domain.png and
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


def excitation_spectrum():
    INK, INK2, GRID, SURF = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
    runs = [('run_L6n2_mesh1_mergecorrection_data', 20e9, 'fstop 20 GHz', '#2a78d6', '-'),
            ('run_L6n2_mergecorrection_sweep_mesh1_limit-60_data', 14e9, 'fstop 14 GHz', '#eb6834', '--')]
    f = np.arange(0, 30.001e9, 0.02e9)
    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=150, facecolor=SURF); ax.set_facecolor(SURF)
    for d, fstop, label, col, ls in runs:
        t, e = np.loadtxt(os.path.join(d, 'sub-1', 'et'), unpack=True)
        dt = np.diff(t).mean()
        E = np.array([np.sum(e*np.exp(-2j*np.pi*fi*t))*dt for fi in f])
        P = np.abs(E)**2; PdB = 10*np.log10(P/P.max())
        k = np.argmax(P)
        ax.plot(f/1e9, PdB, color=col, lw=2, ls=ls, label=f'{label} (peak {f[k]/1e9:.0f} GHz, {t[-1]*1e12:.0f} ps pulse)')
        ax.axvline(fstop/1e9, color=col, lw=1, ls=':')
        ax.text(fstop/1e9, -57, f' {label}', color=INK2, fontsize=8, va='bottom')
    ax.set_xlim(0, 30); ax.set_ylim(-60, 5)
    ax.set_xlabel('Frequency (GHz)', color=INK2); ax.set_ylabel('Excitation power (dB rel. own peak)', color=INK2)
    ax.set_title('L6n2 openEMS excitation power spectrum: fstop 20 GHz vs. 14 GHz', fontsize=10, color=INK, loc='left')
    ax.text(0.3, -16, 'both −13.5 dB at 0.1 GHz', color=INK, fontsize=8)
    ax.grid(True, color=GRID, lw=0.8); ax.tick_params(colors=INK2, labelsize=8)
    for s in ax.spines.values(): s.set_color(GRID)
    ax.legend(loc='upper right', fontsize=8, frameon=False, labelcolor=INK)
    fig.tight_layout()
    out = os.path.join(plots, 'L6n2_excitation_spectrum_fstop14_vs_20.png'); fig.savefig(out, facecolor=SURF); print(out)


def port_voltages_db():
    INK, INK2, GRID, SURF = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
    # (data dir, label, color, linestyle, marker, excitation pulse end in ps)
    runs = [('run_L6n2_mesh1_mergecorrection_data', 'fstop 20 GHz, −40 dB', '#2a78d6', '-', 'o', 286.5),
            ('run_L6n2_mergecorrection_sweep_mesh1_limit-40_data', 'fstop 14 GHz, −40 dB', '#eb6834', '--', 's', 409.3),
            ('run_L6n2_mergecorrection_sweep_mesh1_limit-60_data', 'fstop 14 GHz, −60 dB', '#1baf7a', '-', '^', 409.3)]
    draw_order = (runs[2], runs[0], runs[1])   # -60 dB first, so the identical -40 dB run stays visible on top

    fig, axes = plt.subplots(2, 1, figsize=(8, 6.4), dpi=150, sharex=True, facecolor=SURF)
    for p, ax in zip((1, 2), axes):
        ax.set_facecolor(SURF)
        data = {r[0]: np.loadtxt(f'{r[0]}/sub-1/port_ut_{p}', comments='%') for r in runs}
        ref = max(np.abs(d[:, 1]).max() for d in data.values())
        for d, label, col, ls, mk, texc in draw_order:
            t, u = data[d][:, 0]*1e12, data[d][:, 1]
            udb = 20*np.log10(np.abs(u)/ref + 1e-12)
            top = ls == '--'
            ax.plot(t, udb, color=col, lw=2.6 if top else 2, ls=ls, marker=mk, ms=4, mfc=col, mec=SURF, mew=1,
                    zorder=3 if top else 2, label=label)
            ax.plot(t[-1], udb[-1], marker='X', ms=10, color=col, mec=SURF, mew=1.5, zorder=5)
        for texc, col in ((286.5, '#2a78d6'), (409.3, '#eb6834')):
            ax.axvline(texc, color=col, lw=1, ls=':')
        ax.set_ylim(-120, 5); ax.set_xlim(0, 800)
        ax.set_ylabel(f'|u{p}| (dB rel. max)', color=INK2)
        ax.set_title(f'Port {p} voltage' + (' (excited port)' if p == 1 else ' (receiving port)') + ', port 1 excitation',
                     fontsize=9, color=INK, loc='left')
        ax.grid(True, color=GRID, lw=0.8); ax.tick_params(colors=INK2, labelsize=8)
        for s in ax.spines.values(): s.set_color(GRID)

    axes[0].text(288, -115, ' pulse end, fstop 20 GHz', color=INK2, fontsize=7, rotation=90, va='bottom')
    axes[0].text(411, -115, ' pulse end, fstop 14 GHz', color=INK2, fontsize=7, rotation=90, va='bottom')
    h, l = axes[0].get_legend_handles_labels()
    order = [l.index(r[1]) for r in runs]
    axes[0].legend([h[i] for i in order], [l[i] for i in order], loc='upper right', fontsize=8, frameon=False,
                   labelcolor=INK, title='X = run stops', title_fontsize=7)
    axes[1].annotate('fstop 14 GHz, −40 dB: identical to the\n−60 dB run until it stops at the pulse end',
                     (402, -38), xytext=(455, -12), fontsize=8, color=INK,
                     arrowprops=dict(arrowstyle='-', color=INK2, lw=0.8))
    axes[1].annotate('slow low-frequency tail,\nonly captured by the −60 dB run',
                     (720, -82), xytext=(560, -112), fontsize=8, color=INK,
                     arrowprops=dict(arrowstyle='-', color=INK2, lw=0.8))
    axes[1].set_xlabel('Time (ps)', color=INK2)
    fig.suptitle('L6n2 openEMS port voltages: −40 dB runs stop at the end of the excitation pulse',
                 x=0.02, ha='left', fontsize=10, color=INK)
    fig.tight_layout()
    out = os.path.join(plots, 'L6n2_port_voltages_time_domain.png')
    fig.savefig(out, facecolor=SURF)
    print(out)
    for d, label, *_ in runs:
        u = np.loadtxt(f'{d}/sub-1/port_ut_2', comments='%')
        print(label.replace('−', '-'), ': last |u2| %.1f dB below its max' % (-20*np.log10(abs(u[-1, 1])/abs(u[:, 1]).max())))


def port_voltages_linear():
    INK, INK2, GRID, SURF = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
    runs = [('run_L6n2_mesh1_mergecorrection_data', 'fstop 20 GHz, −40 dB', '#2a78d6', '-', 'o'),
            ('run_L6n2_mergecorrection_sweep_mesh1_limit-40_data', 'fstop 14 GHz, −40 dB', '#eb6834', '--', 's'),
            ('run_L6n2_mergecorrection_sweep_mesh1_limit-60_data', 'fstop 14 GHz, −60 dB', '#1baf7a', '-', '^')]
    draw_order = (runs[2], runs[0], runs[1])   # identical -40 dB run drawn on top of the -60 dB run
    ZOOM_FROM = 380  # ps

    def style(ax):
        ax.set_facecolor(SURF); ax.grid(True, color=GRID, lw=0.8); ax.tick_params(colors=INK2, labelsize=8)
        for s in ax.spines.values(): s.set_color(GRID)

    fig, axes = plt.subplots(2, 2, figsize=(10, 6.4), dpi=150, facecolor=SURF, gridspec_kw={'width_ratios': [3, 2]})
    for row, p in enumerate((1, 2)):
        full, zoom = axes[row]
        style(full); style(zoom)
        data = {r[0]: np.loadtxt(f'{r[0]}/sub-1/port_ut_{p}', comments='%') for r in runs}
        for d, label, col, ls, mk in draw_order:
            t, u = data[d][:, 0]*1e12, data[d][:, 1]*1e6   # ps, uV
            top = ls == '--'
            kw = dict(color=col, lw=2.4 if top else 1.8, ls=ls, marker=mk, ms=3.5, mfc=col, mec=SURF, mew=0.8,
                      zorder=3 if top else 2)
            full.plot(t, u, label=label, **kw)
            zoom.plot(t, u, **kw)
            for a in (full, zoom):
                a.plot(t[-1], u[-1], marker='X', ms=9, color=col, mec=SURF, mew=1.2, zorder=5)
        for a in (full, zoom):
            for texc, col in ((286.5, '#2a78d6'), (409.3, '#eb6834')):
                a.axvline(texc, color=col, lw=1, ls=':')
            a.axhline(0, color=INK2, lw=0.6)
        tail = data[runs[2][0]]; tt = tail[:, 0]*1e12; uu = tail[:, 1]*1e6
        lim = np.abs(uu[tt > ZOOM_FROM]).max()*1.15
        zoom.set_xlim(ZOOM_FROM, 790); zoom.set_ylim(-lim, lim)
        full.set_xlim(0, 800)
        full.axvspan(ZOOM_FROM, 800, color=GRID, alpha=0.35, lw=0)
        full.set_ylabel(f'u{p} (µV)', color=INK2)
        full.set_title(f'Port {p} voltage' + (' (excited port)' if p == 1 else ' (receiving port)') + ', port 1 excitation',
                       fontsize=9, color=INK, loc='left')
        zoom.set_title(f'zoom: after {ZOOM_FROM} ps (shaded on the left)', fontsize=9, color=INK2, loc='left')
    axes[1][0].set_xlabel('Time (ps)', color=INK2); axes[1][1].set_xlabel('Time (ps)', color=INK2)
    h, l = axes[0][0].get_legend_handles_labels(); order = [l.index(r[1]) for r in runs]
    fig.legend([h[i] for i in order], [l[i] for i in order] , loc='upper left', ncol=3, fontsize=8, frameon=False,
               labelcolor=INK, bbox_to_anchor=(0.01, 0.945))
    fig.suptitle('L6n2 openEMS port voltages, linear scale (X = run stops, dotted = pulse end)',
                 x=0.01, y=0.975, ha='left', fontsize=10, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(os.path.join(plots, 'L6n2_port_voltages_time_domain_linear.png'), facecolor=SURF)
    print('ok')


excitation_spectrum()
port_voltages_db()
port_voltages_linear()
