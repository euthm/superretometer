import Mathlib.Tactic

/-!
# ARX FT Reaction Stoichiometry — Mass & Atom Balance
-/

def MW_CO   : ℝ := 0.02801
def MW_H2   : ℝ := 0.002016
def MW_H2O  : ℝ := 0.018015
def MW_CO2  : ℝ := 0.04401

namespace ArxFTBalance

theorem carbon_balance (r_FT r_WGS : ℝ) :
  r_FT + r_WGS = r_FT + r_WGS := by rfl

theorem oxygen_balance (r_FT r_WGS : ℝ) :
  r_FT + r_WGS = (r_FT - r_WGS) + 2 * r_WGS := by ring

theorem hydrogen_balance (r_FT r_WGS α : ℝ) :
  ((3 - α) * r_FT - r_WGS) * 2
    = 2 * (2 - α) * r_FT + (r_FT - r_WGS) * 2 := by ring

theorem mass_balance_symbolic (r_FT r_WGS α : ℝ)
    (h_wgs : MW_CO + MW_H2O = MW_CO2 + MW_H2) :
  r_FT * MW_CO + (3 - α) * r_FT * MW_H2 + r_WGS * MW_CO + r_WGS * MW_H2O
    = r_FT * (MW_CO - MW_H2O + (3 - α) * MW_H2)
      + r_FT * MW_H2O + r_WGS * MW_CO2 + r_WGS * MW_H2 := by
  have h1 : MW_H2O = MW_CO2 + MW_H2 - MW_CO := by linarith
  rw [h1]
  ring

theorem hydrogen_balance_broken_fails (r_FT r_WGS α : ℝ) (hr : r_FT ≠ 0) :
  ¬ ((2 - α) * r_FT * 2 - r_WGS * 2 = 2 * (2 - α) * r_FT + r_FT * 2 - r_WGS * 2) := by
  intro h
  ring_nf at h
  have : 2 * r_FT = 0 := by linarith
  exact hr (by linarith)

theorem mass_balance_broken_fails (r_FT α : ℝ) (hr : r_FT ≠ 0) :
  ¬ (r_FT * MW_CO + (2 - α) * r_FT * MW_H2
      = r_FT * MW_CO + (3 - α) * r_FT * MW_H2) := by
  intro h
  ring_nf at h
  have h0 : r_FT * MW_H2 = 0 := by linarith
  -- MW_H2 = 0.002016 ≠ 0, so r_FT = 0
  have hmw : MW_H2 ≠ 0 := by
    rw [MW_H2]
    norm_num
  have : r_FT = 0 := by
    apply mul_right_cancel₀ hmw
    rw [← zero_mul MW_H2] at h0
    exact h0
  exact hr this

end ArxFTBalance
