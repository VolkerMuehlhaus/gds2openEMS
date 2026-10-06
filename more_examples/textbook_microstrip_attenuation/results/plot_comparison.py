#!/usr/bin/env python3
"""Regenerate the S21/S11 comparison plot from results/sparams_{lossless,lossy}.npz."""
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

c0 = 2.99792458e8
eps_r = 4.3
Wh = 1.9449019476849656
eps_eff = (eps_r + 1) / 2 + (eps_r - 1) / 2 * 1.0 / np.sqrt(1 + 12 / Wh)
tand = 0.02
L_cm = 10.0  # 100 mm line

here = os.path.dirname(os.path.abspath(__file__))
lossless = np.load(os.path.join(here, 'sparams_lossless.npz'))
lossy = np.load(os.path.join(here, 'sparams_lossy.npz'))

f = lossless['f']
db = lambda x: 20 * np.log10(np.abs(x))

# closed-form dielectric attenuation prediction, Pozar-style formula, added on top of the
# simulated (real-copper) lossless-dielectric curve - see ../README.md
k0 = 2 * np.pi * f / c0
alpha_d_Np_per_m = k0 * eps_r * (eps_eff - 1) * tand / (2 * np.sqrt(eps_eff) * (eps_r - 1))
alpha_d_dB_cm = alpha_d_Np_per_m * 8.686 / 100
predicted_s21_db = db(lossless['s21']) - alpha_d_dB_cm * L_cm

fig, axes = plt.subplots(2, 1, figsize=(7, 8), tight_layout=True)

axes[0].plot(f / 1e9, db(lossless['s21']), 'b-', label='S21, simulated, tanδ=0 (conductor loss only)')
axes[0].plot(f / 1e9, db(lossy['s21']), 'r-', label='S21, simulated, tanδ=0.02 (Debye model)')
axes[0].plot(f / 1e9, predicted_s21_db, 'k--', label='S21, tanδ=0 sim + closed-form αd·L')
axes[0].set_xlabel('Frequency (GHz)')
axes[0].set_ylabel('S21 (dB)')
axes[0].set_title('Microstrip insertion loss: simulated vs. textbook closed-form prediction')
axes[0].grid(True)
axes[0].legend(fontsize=8)

axes[1].plot(f / 1e9, db(lossless['s11']), 'b-', label='S11, tanδ=0')
axes[1].plot(f / 1e9, db(lossy['s11']), 'r-', label='S11, tanδ=0.02')
axes[1].set_xlabel('Frequency (GHz)')
axes[1].set_ylabel('S11 (dB)')
axes[1].set_title('Return loss (50-ohm match check)')
axes[1].grid(True)
axes[1].legend(fontsize=8)

out_dir = os.path.join(here, 'plots')
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, 'microstrip_attenuation_comparison.png')
fig.savefig(out_path, dpi=150)
print('Wrote', out_path)
