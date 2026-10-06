#
# Copyright 2026 Volker Muehlhaus and IHP PDK Authors
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

# Fit a stackup material's single-frequency Permittivity/DielectricLossTangent spec to a
# causal, multi-pole (wideband) Debye dispersion model, so that openEMS sees a loss tangent
# that is actually frequency dependent (as any real dielectric's loss must be, by the
# Kramers-Kronig relations) instead of the frequency-independent epsilon that
# util_simulation_setup.py passed to CSX.AddMaterial() previously, which silently dropped
# DielectricLossTangent entirely.
#
# This is the same "wideband" / "multi-pole" Debye construction described by Djordjevic and
# Sarkar for PCB laminates (a sum of Debye poles log-spaced across the frequency range of
# interest, fitted so that the real permittivity and loss tangent stay close to their nominal
# values across that range) - as opposed to a single-pole Debye model, which only matches the
# nominal values at one frequency and drifts increasingly far from them away from that point.
#
# File history:
# 05 Oct 2026: initial version, for stackup DielectricLossTangent -> CSPropDebyeMaterial

__version__ = "1.0.0"

import numpy as np
from scipy.optimize import nnls


def fit_wideband_debye (eps_r, tand, f_start, f_stop, poles_per_decade=4, samples_per_decade=12,
                         extend_decades=0.5, floor_ratio=1e-2, min_poles=4):
  """Fit a causal multi-pole Debye model that reproduces a material's nominal relative
     permittivity `eps_r` and loss tangent `tand` (as given, frequency-independent, in the
     stackup XML) as closely as possible across [f_start, f_stop].

     Because any causal dielectric response must obey the Kramers-Kronig relations, a real
     part (eps_r) that is exactly constant over many decades together with an exactly constant
     loss tangent is not physically realizable - matching both as closely as possible, rather
     than matching one exactly, is the correct (and standard) target for this kind of fit. The
     resulting small roll-off of eps_r with frequency this introduces is real physical
     behavior of lossy dielectrics (see e.g. Djordjevic/Sarkar's wideband Debye model for PCB
     laminates), not a fitting artifact - it grows with how many decades are covered and with
     how lossy the material is, and cannot be fitted away without violating causality.

  Args:
      eps_r (float): nominal relative permittivity (stackup XML "Permittivity")
      tand (float): nominal loss tangent at eps_r (stackup XML "DielectricLossTangent"),
        assumed valid across the whole [f_start, f_stop] range (the stackup XML format has no
        separate "measured at" frequency attribute, so this is the only interpretation
        available - matches how `eps_r` itself was already being applied uniformly across
        the whole simulated band before this function existed)
      f_start (float): lowest frequency of interest, in Hz. 0 (a common choice for the FDTD
        Gaussian excitation's nominal start frequency) is accepted and treated as "near DC
        contributes negligible energy" - the fit's effective lower edge is then
        `f_stop * floor_ratio` instead, since fitting a flat loss tangent down to literal
        0 Hz is both ill-defined (needs log-spaced poles) and physically meaningless (every
        real dielectric's loss mechanism eventually turns off at low enough frequency)
      f_stop (float): highest frequency of interest, in Hz
      poles_per_decade (int): Debye pole density. 4 matches observed loss tangent to within
        roughly 1% per decade of span for typical PCB-laminate-range loss tangents (~0.001 to
        ~0.03); more poles does not meaningfully improve this, since the residual error is the
        physical Kramers-Kronig effect described above, not discretization error
      samples_per_decade (int): frequency points per decade used only to set up the
        least-squares fit itself (not related to the simulation's own frequency sampling)
      extend_decades (float): the pole ladder (and fit sample points) extend this many extra
        decades below f_start and above f_stop, so that [f_start, f_stop] itself sits away
        from the ladder's own edge, where a finite pole count's accuracy is worst
      floor_ratio (float): effective f_start used when the caller passes f_start=0 (see above)
      min_poles (int): floor on the number of poles, regardless of how narrow [f_start,f_stop]
        is (a very narrow band still needs a handful of poles to resolve both eps_r and tand
        simultaneously)

  Returns:
      (eps_inf, poles): eps_inf (float) is the material's non-dispersive ("instantaneous")
        relative permittivity to pass as CSPropMaterial's own `epsilon`; poles is a list of
        (delta_eps, relaxation_time_seconds) tuples, one per surviving pole (poles whose
        fitted weight came out numerically zero are already dropped), to be passed one by one
        to CSPropDebyeMaterial.SetDispersiveMaterialProperty(order_index, eps_delta=...,
        eps_relax=...)
  """
  if tand <= 0:
    # nothing to fit - caller should use a plain (non-dispersive) material instead; returning
    # the trivial non-dispersive equivalent here anyway so this function is safe to call
    # unconditionally
    return eps_r, []

  if f_stop is None or f_stop <= 0:
    print('ERROR: fit_wideband_debye() needs a valid f_stop > 0 to fit DielectricLossTangent='
          , tand, ' - pass fstart/fstop to setupSimulation() (or settings["fstart"]/["fstop"])')
    exit(1)

  f_lo = f_start if (f_start is not None and f_start > 0) else f_stop * floor_ratio

  if f_lo >= f_stop:
    print('ERROR: fit_wideband_debye() needs f_start < f_stop, got f_start=', f_start, ' f_stop=', f_stop)
    exit(1)

  # pole ladder: log-spaced, extended beyond [f_lo, f_stop] on both ends
  f_lo_fit = f_lo / (10 ** extend_decades)
  f_hi_fit = f_stop * (10 ** extend_decades)
  decades = np.log10(f_hi_fit / f_lo_fit)

  n_poles = max(min_poles, int(np.ceil(decades * poles_per_decade)))
  pole_freqs = np.logspace(np.log10(f_lo_fit), np.log10(f_hi_fit), n_poles)
  taus = 1.0 / (2 * np.pi * pole_freqs)

  # sample points across the actual band of interest, used only to set up the fit
  n_samples = max(2 * n_poles, int(np.ceil(decades * samples_per_decade)))
  f_samples = np.logspace(np.log10(f_lo), np.log10(f_stop), n_samples)
  w = 2 * np.pi * f_samples

  wt = w[:, None] * taus[None, :]          # (n_samples, n_poles)
  denom = 1.0 + wt ** 2
  real_part = 1.0 / denom                   # per-pole contribution to eps'/delta_eps
  imag_part = wt / denom                    # per-pole contribution to eps''/delta_eps

  # Linear least-squares system for unknowns x = [eps_inf, delta_eps_1 .. delta_eps_N], with
  # every row scaled to a target of 1 (relative-error weighting): this makes a plain
  # (unweighted) non-negative least-squares fit minimize relative error on eps_r and on
  # tand equally, rather than minimizing absolute error (which would be dominated entirely by
  # eps_r, since tand*eps_r is typically 1-2 orders of magnitude smaller). Non-negativity
  # (scipy.optimize.nnls) is not just a convenience - it is physically required: a Debye pole
  # with delta_eps<0 or a negative instantaneous epsilon would make this material locally
  # active (gain) instead of lossy, which is both unphysical and numerically unstable in FDTD.
  n_rows_each = len(f_samples)
  A = np.zeros((2 * n_rows_each, n_poles + 1))
  b = np.ones(2 * n_rows_each)
  A[0:n_rows_each, 0] = 1.0                       # eps_inf contributes only to the real part
  A[0:n_rows_each, 1:] = real_part / eps_r
  A[n_rows_each:, 1:] = imag_part / tand

  x, _residual = nnls(A, b)

  eps_inf = x[0] * eps_r
  delta_eps = x[1:] * eps_r

  # drop poles with negligible (numerically ~zero) weight, to keep CSPropDebyeMaterial's
  # dispersion order (and so the FDTD solver's per-cell auxiliary state) as small as the fit
  # actually needs
  poles = [(float(d), float(t)) for d, t in zip(delta_eps, taus) if d > 1e-6 * eps_r]

  return float(eps_inf), poles
