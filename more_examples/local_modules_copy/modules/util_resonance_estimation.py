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

# Resonance estimation, enabled with settings['resonance_estimation'] = True.
#
# FDTD stops when the energy left in the model is below settings['energy_limit']. If that is too
# early, the port signals are cut off before they have decayed, and the S-parameters get a truncation
# error, largest at low frequency. Resonance estimation fits a model to the recorded port signals and
# extends them beyond the point where openEMS stopped (like the "AR filter" in CST or "resonance
# estimation" in Empire XPU). A monitor thread does this while openEMS is running, and stops openEMS
# as soon as the extrapolated S-parameters no longer change. energy_limit stays the upper limit.
#
# Two ways to extend the signals, chosen automatically:
#  - free-decay fit (matrix pencil): damped oscillations fitted to the samples recorded after the
#    excitation is over; used when enough of them exist (MP_MIN_SAMPLES).
#  - known-input fit (ARX model): each port signal is the known excitation passed through a filter
#    whose poles are the resonances of the structure; also works when openEMS stops at the end of
#    the excitation pulse.
# All port signals of one excitation share the same poles.
#
# The extended signals are written to <excitation folder>/resonance_estimation/, with the same file
# names as the openEMS probe files. utilities.calculate_Sij() uses them when they exist, so the
# S-parameters are calculated exactly like from the original openEMS data.
#
# If the model has field dumps or nf2ff boxes, openEMS is not stopped early (they collect their data
# during the run and would be truncated); only the port signals are extended after the run.
#
# Tested on six models (inductors, MIM capacitor, PA core layouts up to 350 GHz): stops at 0.4-0.8x
# the run time of a -60 dB end criterion, with max |dS| 7e-5 to 2e-3 against -90 dB runs.

import json
import os
import threading
import time

import numpy as np

RESULT_FOLDER = 'resonance_estimation'      # extended probe signals, inside the excitation folder
LOG_FILE = 'resonance_estimation.txt'       # what was done, inside the excitation folder

TOLERANCE = 3e-4        # stop when extrapolations LAG samples apart differ less than this (max |dS|)
LAG = 4                 # probe samples between the compared extrapolations
CHECK_INTERVAL = 2.0    # seconds between checks while openEMS is running
SELF_CHECK = 3e-3       # final result: larger change between the last extrapolations -> keep raw data

HOLDOUT = 6             # ARX order: samples held out to choose the order
HOLDOUT_TOL = 1e-2      # raise the order while the holdout error (relative energy) is above this,
ORDER_GAIN = 10         # or while the next order still improves it this much
ORDERS = range(1, 13)
SM_ITER = 5             # Steiglitz-McBride iterations for the ARX fit
MP_MIN_SAMPLES = 30     # free-decay samples needed for the matrix pencil fit (20 was not always stable)
FREE_DECAY_DB = -60     # the excitation is over when it is this far below its peak
TAIL_REL = 1e-7         # extend the signals until the slowest pole has decayed to this level,
MAX_TAIL_FACTOR = 20    #   but not longer than this many times the record (tail_check() rejects slower tails)
NUM_FREQ = 201          # frequency points for the convergence check
TAU_FACTOR = 3.0        # tail_check(): effective time constant of the tail at most this many times the
MIN_RECORD_SAMPLES = 8  #   free decay recorded (at least this many samples), and the tail does not
MAX_GROWTH = 3.0        #   exceed this many times the signal level at the end of the record


# ------------------------------------------------------------------------------------ file access

def _read_probe(filename):
    """Time and value columns of an openEMS probe file. Tolerates a half-written last line, because
    the monitor reads the files while openEMS is still writing them."""
    t, x = [], []
    with open(filename, 'r') as f:
        lines = f.readlines()
    for line in lines:
        if line.startswith('%'):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            tv, xv = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        t.append(tv)
        x.append(xv)
    if lines and not lines[-1].endswith('\n') and t:     # last line may still be incomplete
        t, x = t[:-1], x[:-1]
    return np.array(t), np.array(x)


def _probe_files(excitation_path, ports):
    return [(i, q, os.path.join(excitation_path, f'port_{q}t_{i}')) for i in ports for q in ('u', 'i')]


def read_signals(excitation_path, ports):
    """{(port, 'u'|'i'): (t, x)} of one excitation, or None while files are missing or empty."""
    sig = {}
    for i, q, fn in _probe_files(excitation_path, ports):
        if not os.path.exists(fn):
            return None
        t, x = _read_probe(fn)
        if len(t) < 3:
            return None
        sig[(i, q)] = (t, x)
    return sig


def read_excitation(excitation_path):
    """The excitation signal (et), or None while openEMS has not written it yet."""
    fn = os.path.join(excitation_path, 'et')
    if not os.path.exists(fn):
        return None
    t, e = _read_probe(fn)
    return (t, e) if len(t) > 10 else None


def read_port_information(sim_path):
    """Port numbers and reference impedances from port_information.json (written by runSimulation)."""
    with open(os.path.join(sim_path, 'port_information.json'), 'r', encoding='utf-8') as f:
        info = json.load(f)
    return {p['portnumber']: p['Z0'] for p in info['ports']}


def remove_results(excitation_path):
    """Remove extended signals and log of an earlier run, before openEMS writes new data."""
    folder = os.path.join(excitation_path, RESULT_FOLDER)
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        os.rmdir(folder)
    log = os.path.join(excitation_path, LOG_FILE)
    if os.path.exists(log):
        os.remove(log)


def result_path(excitation_path):
    """Folder with the extended signals of this excitation if resonance estimation created one, else None.
    Used by utilities.calculate_Sij()."""
    folder = os.path.join(excitation_path, RESULT_FOLDER)
    return folder if os.path.isdir(folder) else None


# ------------------------------------------------------------------------------- extrapolation

def _allpole(A, x):
    """y = x / A(z), i.e. y[n] = x[n] - sum_k A[k] y[n-k] (A[0] = 1)."""
    na = len(A) - 1
    if na == 0:
        return np.array(x, dtype=float)
    y = np.zeros(len(x) + na)
    a = np.asarray(A[1:])[::-1]
    for n in range(len(x)):
        y[n + na] = x[n] - a @ y[n:n + na]
    return y[na:]


def _lags(x, n0, N, lags):
    return np.column_stack([x[n0 - k:N - k] for k in lags])


def _fit_numerators(a, Y, u):
    na = len(a)
    B = []
    for y in Y:
        N = len(y)
        rhs = y[na:] - (_lags(y, na, N, range(1, na + 1)) @ a if na else 0)
        B.append(np.linalg.lstsq(_lags(u, na, N, range(0, na + 1)), rhs, rcond=None)[0])
    return np.array(B)


def _fit_arx(Y, u, na):
    """Shared-denominator ARX model, refined by Steiglitz-McBride iterations. Unstable poles are reflected."""
    ns, nb = len(Y), na + 1
    rows = [len(y) - na for y in Y]
    off = np.r_[0, np.cumsum(rows)]
    A = np.array([1.0])
    a = np.zeros(na)
    for _ in range(SM_ITER + 1):
        uf = _allpole(A, u[:max(len(y) for y in Y)])
        M = np.zeros((off[-1], na + ns * nb))
        rhs = np.zeros(off[-1])
        for s, y in enumerate(Y):
            N = len(y)
            yf = _allpole(A, y)
            r = slice(off[s], off[s + 1])
            M[r, :na] = _lags(yf, na, N, range(1, na + 1))
            M[r, na + s * nb:na + (s + 1) * nb] = _lags(uf, na, N, range(0, na + 1))
            rhs[r] = yf[na:]
        p = np.linalg.lstsq(M, rhs, rcond=None)[0]
        A_new = np.r_[1.0, -p[:na]]
        if np.any(abs(np.roots(A_new)) >= 1):     # prefiltering with an unstable 1/A diverges
            if len(A) == 1:
                A, a = A_new, p[:na]
            break
        A, a = A_new, p[:na]
    poles = np.roots(A)
    if np.any(abs(poles) >= 1):
        poles = np.where(abs(poles) >= 1, 1 / np.conj(poles), poles)
        a = -np.real(np.poly(poles))[1:]
    return a, _fit_numerators(a, Y, u)


def _run_arx(a, b, y, u, n_from, n_to):
    na = len(a)
    x = np.zeros(n_to)
    x[:n_from] = y[:n_from]
    for n in range(n_from, n_to):
        x[n] = (x[n - na:n][::-1] @ a if na else 0) + b @ u[n - na:n + 1][::-1]
    return x


def _tail_length(poles, n_min, n_record):
    zmax = max(abs(poles).max(), 0.5) if len(poles) else 0.5
    return int(min(max(np.log(TAIL_REL) / np.log(zmax), n_min), MAX_TAIL_FACTOR * n_record))


def _prepare(sig, te, e):
    keys = list(sig)
    scale = np.array([max(abs(sig[k][1]).max(), 1e-300) for k in keys])
    Y = [sig[k][1] / s for k, s in zip(keys, scale)]
    t = sig[keys[0]][0]
    dt = t[1] - t[0]
    Ns = np.array([len(y) for y in Y])
    u = np.interp(t[0] + np.arange(Ns.max() + 50000) * dt, te, e, right=0.0)
    return keys, scale, Y, Ns, dt, u


def _extrapolate_arx(sig, te, e, info):
    keys, scale, Y, Ns, dt, u = _prepare(sig, te, e)
    best = None
    for na in ORDERS:
        if Ns.min() - HOLDOUT - na < 3 * na + 3:
            break
        a, B = _fit_arx([y[:-HOLDOUT] for y in Y], u, na)
        err = sum(np.sum((_run_arx(a, b, y, u, len(y) - HOLDOUT, len(y))[-HOLDOUT:] - y[-HOLDOUT:])**2)
                  for b, y in zip(B, Y)) / max(sum(np.sum(y[-HOLDOUT:]**2) for y in Y), 1e-300)
        if best is not None and best[1] < HOLDOUT_TOL and err > best[1] / ORDER_GAIN:
            break
        best = (na, err)
    if best is None:
        return None
    a, B = _fit_arx(Y, u, best[0])
    poles = np.roots(np.r_[1.0, -a])
    n_to = Ns.max() + _tail_length(poles, 10, Ns.max())
    X = [_run_arx(a, b, y, u, len(y), n_to) * s for b, y, s in zip(B, Y, scale)]
    info.update(method='known-input fit (ARX)', order=best[0], poles=poles, dt=dt)
    return _rebuild(sig, keys, X, dt)


def _extrapolate_mp(sig, te, e, info, sv_tol=1e-5):
    keys, scale, Y, Ns, dt, u = _prepare(sig, te, e)
    t = sig[keys[0]][0][0] + np.arange(Ns.max()) * dt
    t_free = te[np.where(abs(e) > abs(e).max() * 10**(FREE_DECAY_DB / 20))[0][-1]]
    n0 = int(np.searchsorted(t, t_free))
    K = Ns.min() - n0
    info['free_samples'] = max(K, 0)
    if K < MP_MIN_SAMPLES:
        return None
    L = K // 2
    H = np.vstack([np.array([y[n0 + r: n0 + r + L + 1] for r in range(K - L)]) for y in Y])
    _, sv, Vh = np.linalg.svd(H, full_matrices=False)
    M = min(max(1, int(np.sum(sv > sv_tol * sv[0]))), L)
    V = Vh[:M].conj().T
    z = np.linalg.eigvals(np.linalg.pinv(V[:-1]) @ V[1:])
    z = np.where(abs(z) >= 1, 1 / np.conj(z), z)
    n_to = Ns.max() + _tail_length(z, 10, Ns.max())
    X = []
    for y, s in zip(Y, scale):
        n = np.arange(len(y) - n0)
        r = np.linalg.lstsq(z[None, :] ** n[:, None], y[n0:], rcond=None)[0]
        X.append(np.real((z[None, :] ** (np.arange(n_to) - n0)[:, None]) @ r) * s)
    info.update(method='free-decay fit (matrix pencil)', order=M, poles=z, dt=dt)
    return _rebuild(sig, keys, X, dt)


def _rebuild(sig, keys, X, dt):
    out = {}
    for x, k in zip(X, keys):
        t, y = sig[k]
        out[k] = (t[0] + np.arange(len(x)) * dt, np.r_[y, x[len(y):]])
    return out


def free_decay_samples(sig, te, e):
    """Number of samples recorded after the excitation is over (below FREE_DECAY_DB)."""
    t = next(iter(sig.values()))[0]
    t_free = te[np.where(abs(e) > abs(e).max() * 10**(FREE_DECAY_DB / 20))[0][-1]]
    return max(min(len(x) for _, x in sig.values()) - int(np.searchsorted(t, t_free)), 0)


def choose_method(sig, te, e):
    """'MP' (free-decay fit) if enough free decay was recorded, else 'ARX' (known-input fit)."""
    return 'MP' if free_decay_samples(sig, te, e) >= MP_MIN_SAMPLES else 'ARX'


def extrapolate(sig, te, e, info=None, method=None):
    """Extend the port signals of one excitation with the given method ('MP' or 'ARX'), or with the one
    choose_method() picks. Extrapolations that are compared with each other must use the same method:
    near MP_MIN_SAMPLES, the two methods can give different results. Returns None if not possible."""
    info = {} if info is None else info
    info['free_samples'] = free_decay_samples(sig, te, e)
    if (method or choose_method(sig, te, e)) == 'MP':
        return _extrapolate_mp(sig, te, e, info)
    return _extrapolate_arx(sig, te, e, info)


def tail_check(sig, ext, te, e):
    """Plausibility of an extrapolation, independent of the fit method: the extended part (tail) must not
    grow, and it must not decay much more slowly than the record can tell. For a decaying exponential with
    amplitude A at the end of the record and time constant tau, the tail energy is A**2 * tau / 2; tau_eff is
    that relation applied to all port signals together (each normalized to its peak). A slow component with
    negligible amplitude adds little tail energy and passes; one that dominates the tail does not.
    Returns (ok, tau_eff, t_free_recorded, growth)."""
    t = next(iter(sig.values()))[0]
    dt = t[1] - t[0]
    t_free = te[np.where(abs(e) > abs(e).max() * 10**(FREE_DECAY_DB / 20))[0][-1]]
    end_energy, tail_energy, growth = 0.0, 0.0, 0.0
    for k, (_, y) in sig.items():
        peak = max(abs(y).max(), 1e-300)
        last = y[-LAG:] / peak
        tail = ext[k][1][len(y):] / peak
        end_energy += np.mean(last**2)
        tail_energy += np.sum(tail**2) * dt
        if len(tail):
            growth = max(growth, abs(tail).max() / max(abs(y[-2 * LAG:]).max() / peak, 1e-300))
    tau_eff = 2 * tail_energy / max(end_energy, 1e-300)
    t_rec = max(t[-1] - t_free, MIN_RECORD_SAMPLES * dt)
    ok = tau_eff <= TAU_FACTOR * t_rec and growth <= MAX_GROWTH
    return ok, tau_eff, t_rec, growth


def truncate(sig, n):
    """The first n samples of every signal (current probes may have one sample more than voltage probes)."""
    return {k: (t[:n], x[:n]) for k, (t, x) in sig.items()}


# ---------------------------------------------------------------- convergence and final result

def _dft(t, x, freqs):
    return 2 * (t[1] - t[0]) * (np.exp(-2j * np.pi * np.outer(freqs, t)) @ x)


def _column(sig, excited, z0, freqs, band):
    """b_i / a_excited for all ports: the S-parameter column for a single excited port."""
    U = {k: _dft(*v, freqs) for k, v in sig.items()}
    a = 0.5 * (U[(excited, 'u')] + z0[excited] * U[(excited, 'i')])
    ports = sorted({k[0] for k in sig})
    col = np.array([0.5 * (U[(i, 'u')] - z0[i] * U[(i, 'i')]) / a for i in ports])
    return col[:, band]


def _band(te, e, dt):
    """Frequency points for the convergence check: from 0 to the highest frequency of the excitation
    (the probes sample at 4x its Nyquist rate), where the excitation spectrum is not negligible."""
    freqs = np.linspace(0, 1 / (8 * dt), NUM_FREQ)
    ue = np.interp(np.arange(te[0], te[-1], dt), te, e)
    E = abs(_dft(np.arange(len(ue)) * dt, ue, freqs))
    return freqs, E > 0.01 * E.max()


def convergence_check(sig, n, te, e, excited, z0, freqs, band, cache=None):
    """The stop rule, applied to the first n samples of a growing record: extrapolations from n, n-LAG and
    n-2*LAG samples (one method, chosen from the shortest record) agree within TOLERANCE, and the newest
    one passes tail_check(). cache: optional dict, keeps extrapolations by (record length, method), so that
    checking every new sample needs only one new extrapolation per sample.
    Returns (converged, change, extrapolation from n samples)."""
    method = choose_method(truncate(sig, n - 2 * LAG), te, e)
    exts, cols = [], []
    for m in (n, n - LAG, n - 2 * LAG):
        if cache is not None and (m, method) in cache:
            ext, col = cache[(m, method)]
        else:
            ext = extrapolate(truncate(sig, m), te, e, method=method)
            if ext is None:
                return False, np.inf, None
            col = _column(ext, excited, z0, freqs, band)
            if cache is not None:
                cache[(m, method)] = (ext, col)
        exts.append(ext)
        cols.append(col)
    change = max(abs(cols[0] - cols[1]).max(), abs(cols[1] - cols[2]).max())
    converged = change < TOLERANCE and tail_check(truncate(sig, n), exts[0], te, e)[0]
    return converged, change, exts[0]


def final_extrapolation(sig, te, e, excited, z0, freqs, band, converged_ext=None):
    """The extrapolation used for the S-parameters after the run, or None for the original data. The
    extrapolation of the complete record must agree with the one from LAG samples less within SELF_CHECK and
    pass tail_check(). If it does not, and the monitor stopped openEMS early (converged_ext), the extrapolation
    that met the stop rule is used: the original data alone would be truncated. Returns (ext, log lines)."""
    n = min(len(x) for _, x in sig.values())
    t = next(iter(sig.values()))[0]
    method = choose_method(truncate(sig, n - LAG), te, e)       # same method for both extrapolations
    info = {}
    ext = extrapolate(truncate(sig, n), te, e, info, method=method)
    ext_lag = extrapolate(truncate(sig, n - LAG), te, e, method=method)
    if ext is None or ext_lag is None:
        raise RuntimeError('record too short to extrapolate')
    change = abs(_column(ext, excited, z0, freqs, band) - _column(ext_lag, excited, z0, freqs, band)).max()
    plausible, tau_eff, t_rec, growth = tail_check(truncate(sig, n), ext, te, e)
    tau = -info['dt'] / np.log(abs(info['poles']))
    log = [f'Recorded until {t[n - 1] * 1e12:.1f} ps, {info.get("free_samples", 0)} samples after the excitation',
           f'Method: {info["method"]}, {info["order"]} poles, slowest time constant {tau.max() * 1e12:.1f} ps',
           f'Change against the extrapolation {LAG} samples earlier: {change:.1e} (limit {SELF_CHECK:.0e})',
           f'Tail check: effective time constant {tau_eff * 1e12:.1f} ps vs. {t_rec * 1e12:.1f} ps of recorded '
           f'free decay (limit {TAU_FACTOR:g}x), growth {growth:.2f} (limit {MAX_GROWTH:g})']
    if change <= SELF_CHECK and plausible:
        return ext, log + ['Extended signals written to ' + RESULT_FOLDER + '/, used for the S-parameters']
    if converged_ext is not None:
        return converged_ext, log + ['Final extrapolation not trusted; the extrapolation that met the stop rule is '
                                     'written to ' + RESULT_FOLDER + '/ and used for the S-parameters']
    return None, log + ['Result not trusted: S-parameters are calculated from the original openEMS data']


class Monitor(threading.Thread):
    """Runs while openEMS solves one excitation: reads the growing probe files, extrapolates, and stops
    openEMS once the extrapolated S-parameters have converged (convergence_check())."""

    def __init__(self, FDTD, sim_path, excitation_path, excite_portnumbers):
        super().__init__(daemon=True)
        self.FDTD = FDTD
        self.sim_path = sim_path
        self.excitation_path = excitation_path
        self.excited = excite_portnumbers[0]
        self.done = threading.Event()
        self.stop_reason = None
        self.converged_ext = None    # extrapolation that met the stop rule, fallback for finalize()
        self.error = None

    def run(self):
        try:
            self.z0 = read_port_information(self.sim_path)
            self.ports = sorted(self.z0)
            exc = None
            last_n = 0
            cache = {}
            while not self.done.wait(CHECK_INTERVAL):
                if exc is None:
                    exc = read_excitation(self.excitation_path)
                    if exc is None:
                        continue
                    te, e = exc
                    t_free = te[np.where(abs(e) > abs(e).max() * 10**(FREE_DECAY_DB / 20))[0][-1]]
                    freqs = band = None
                sig = read_signals(self.excitation_path, self.ports)
                if sig is None:
                    continue
                n = min(len(t) for t, _ in sig.values())
                t = next(iter(sig.values()))[0]
                if t[n - 1] < t_free or n < 3 * LAG + 10:
                    continue
                if freqs is None:
                    freqs, band = _band(te, e, t[1] - t[0])
                # openEMS writes the probe files only every few seconds: check every sample that arrived since
                # the last check, the stop rule can be met at single samples only
                first = max(last_n + 1, int(np.searchsorted(t, t_free)) + 1, 3 * LAG + 10)
                last_n = n
                for k in range(first, n + 1):
                    if self.done.is_set():
                        return
                    converged, change, ext = convergence_check(sig, k, te, e, self.excited, self.z0, freqs, band,
                                                               cache)
                    for key in [key for key in cache if key[0] < k - 2 * LAG]:
                        del cache[key]
                    if converged:
                        self.converged_ext = ext
                        self.stop_reason = f'converged after {t[k - 1] * 1e12:.1f} ps (change {change:.1e})'
                        print(f'[resonance_estimation] Extrapolated S-parameters converged after '
                              f'{t[k - 1] * 1e12:.1f} ps, stopping openEMS', flush=True)
                        self._stop_openEMS()
                        return
        except Exception as ex:      # the monitor must never break the simulation itself
            self.error = repr(ex)
            print('[resonance_estimation] Monitor stopped after an error, openEMS continues to its '
                  'energy limit:', ex, flush=True)

    def _stop_openEMS(self):
        if hasattr(self.FDTD, 'SetAbort'):
            self.FDTD.SetAbort(True)
        else:                        # older openEMS: stops when it finds this file in its run folder
            open(os.path.join(self.excitation_path, 'ABORT'), 'w').close()

    def finish(self):
        self.done.set()
        self.join()


def finalize(sim_path, excitation_path, excite_portnumbers, monitor=None):
    """After openEMS has finished one excitation: extrapolate the complete record, check it
    (final_extrapolation()), and write the extended signals to <excitation folder>/resonance_estimation/.
    Writes a log in the excitation folder."""
    z0 = read_port_information(sim_path)
    ports = sorted(z0)
    excited = excite_portnumbers[0]
    log = [f'Resonance estimation for excitation {excite_portnumbers}']
    stopped_early = monitor is not None and monitor.stop_reason is not None
    if monitor is not None:
        log.append('openEMS stopped: ' + (monitor.stop_reason or 'at its energy limit (energy_limit)'))
        if stopped_early:
            log.append('(openEMS then reports that the max. number of timesteps was reached: that refers to '
                       'this stop, not to a timestep limit)')
        if monitor.error:
            log.append('Monitor error: ' + monitor.error)
    ok = False
    try:
        exc = read_excitation(excitation_path)
        sig = read_signals(excitation_path, ports)
        if exc is None or sig is None:
            raise RuntimeError('no openEMS probe data found')
        te, e = exc
        n = min(len(t) for t, _ in sig.values())
        t = next(iter(sig.values()))[0]
        if n <= 3 * LAG + 10:
            raise RuntimeError('record too short to extrapolate')
        freqs, band = _band(te, e, t[1] - t[0])
        ext, lines = final_extrapolation(sig, te, e, excited, z0, freqs, band,
                                         monitor.converged_ext if stopped_early else None)
        log += lines
        if ext is not None:
            _write_extended(excitation_path, ext, sig)
            ok = True
    except Exception as ex:
        log.append(f'Resonance estimation not applied ({ex}): S-parameters are calculated from the '
                   'original openEMS data')
    with open(os.path.join(excitation_path, LOG_FILE), 'w') as f:
        f.write('\n'.join(log) + '\n')
    print('[resonance_estimation] ' + '\n[resonance_estimation] '.join(log[1:]), flush=True)
    return ok


def _write_extended(excitation_path, ext, sig):
    folder = os.path.join(excitation_path, RESULT_FOLDER)
    os.makedirs(folder, exist_ok=True)
    for (i, q), (tt, xx) in ext.items():
        kind = 'voltage' if q == 'u' else 'current'
        with open(os.path.join(folder, f'port_{q}t_{i}'), 'w') as f:
            f.write(f'% {kind} probe, extended by gds2openEMS resonance estimation beyond '
                    f'{sig[(i, q)][0][-1]:.6e} s\n% t/s\t{kind}\n')
            np.savetxt(f, np.column_stack([tt, xx]), fmt='%.12e', delimiter='\t')
