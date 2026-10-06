import numpy as np

# Standard closed-form microstrip equations (Hammerstad synthesis + Pozar/Hammerstad-Jensen
# analysis), as given in every microwave engineering textbook (e.g. Pozar, "Microwave
# Engineering," Ch. 3 "Microstrip Line"). Self-consistency check: synthesize W/h for a target
# Z0, then re-derive Z0 and eps_eff from that W/h with the independent analysis formulas and
# confirm they reproduce the target.

c0 = 2.99792458e8

def synthesize_W_over_h(Z0, eps_r):
    """Hammerstad synthesis equations (Pozar eq. 3.196/3.197-equivalent): given target Z0 and
    eps_r, return W/h. Two branches depending on whether the result has W/h <2 or >2."""
    A = (Z0/60.0)*np.sqrt((eps_r+1)/2) + (eps_r-1)/(eps_r+1)*(0.23+0.11/eps_r)
    Wh_A = 8*np.exp(A)/(np.exp(2*A)-2)
    if Wh_A < 2:
        return Wh_A
    B = 377*np.pi/(2*Z0*np.sqrt(eps_r))
    Wh_B = (2/np.pi)*(B - 1 - np.log(2*B-1) + (eps_r-1)/(2*eps_r)*(np.log(B-1)+0.39-0.61/eps_r))
    return Wh_B

def eps_eff_of_Wh(Wh, eps_r):
    """Effective permittivity, standard formula (Pozar eq. 3.195), valid for W/h > ~0.5 or so."""
    return (eps_r+1)/2 + (eps_r-1)/2 * 1.0/np.sqrt(1+12/Wh)

def Z0_of_Wh(Wh, eps_r):
    """Analysis (forward) Z0 formula (Hammerstad), Pozar eq. 3.197 companion - the inverse of
    the synthesis formula above, used here only as a self-consistency check."""
    eps_eff = eps_eff_of_Wh(Wh, eps_r)
    if Wh <= 1:
        Z0 = 60/np.sqrt(eps_eff) * np.log(8/Wh + Wh/4)
    else:
        Z0 = 120*np.pi/(np.sqrt(eps_eff)*(Wh + 1.393 + 0.667*np.log(Wh+1.444)))
    return Z0, eps_eff

def alpha_d_Np_per_m(f, eps_r, eps_eff, tand):
    """Dielectric attenuation constant, Np/m (Pozar eq. 3.198-equivalent, the standard
    textbook formula, independently confirmed via literature search):
    alpha_d = k0 * eps_r * (eps_eff - 1) * tand / (2*sqrt(eps_eff)*(eps_r-1))
    where k0 = 2*pi*f/c0.
    """
    k0 = 2*np.pi*f/c0
    return k0 * eps_r * (eps_eff - 1) * tand / (2*np.sqrt(eps_eff)*(eps_r - 1))


# ---- design case: 50 ohm microstrip on a textbook-standard FR4-like substrate ----
Z0_target = 50.0
eps_r = 4.3     # Pozar Table 3.1-style "typical FR4 (G10)" permittivity
h_mm = 1.6      # standard FR4 PCB thickness
tand = 0.02     # Pozar Table 3.1-style "typical FR4" loss tangent
f = 2.4e9       # a round, common design frequency

Wh = synthesize_W_over_h(Z0_target, eps_r)
W_mm = Wh*h_mm
Z0_check, eps_eff = Z0_of_Wh(Wh, eps_r)

print(f"eps_r={eps_r}  h={h_mm} mm  target Z0={Z0_target} ohm")
print(f"synthesized W/h = {Wh:.4f}  ->  W = {W_mm:.4f} mm")
print(f"self-consistency check: forward Z0({Wh:.4f}) = {Z0_check:.3f} ohm (should be ~{Z0_target})")
print(f"eps_eff = {eps_eff:.4f}")

alpha_d = alpha_d_Np_per_m(f, eps_r, eps_eff, tand)
alpha_d_dB_per_m = alpha_d * 8.686
alpha_d_dB_per_cm = alpha_d_dB_per_m/100
print(f"\nat f={f/1e9} GHz:")
print(f"  alpha_d = {alpha_d:.6f} Np/m = {alpha_d_dB_per_m:.6f} dB/m = {alpha_d_dB_per_cm:.6f} dB/cm")

# also compute for the band 1-4 GHz to pick a good simulation span
for ff in [1e9, 2.4e9, 3e9, 4e9]:
    ad = alpha_d_Np_per_m(ff, eps_r, eps_eff, tand)*8.686/100
    print(f"  f={ff/1e9:.2f} GHz: alpha_d = {ad:.5f} dB/cm")
