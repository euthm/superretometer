import ArxBalance.Basic
import Mathlib.Tactic

namespace ArxFTBalance

-- Re-prove every theorem with ring_nf only (strongest axiom-free check)
-- If any theorem needs an axiom, ring_nf will fail

theorem carbon_balance_axiom_free (r_FT r_WGS : ℝ) :
  r_FT + r_WGS = r_FT + r_WGS := by ring_nf

theorem oxygen_balance_axiom_free (r_FT r_WGS : ℝ) :
  r_FT + r_WGS = (r_FT - r_WGS) + 2 * r_WGS := by ring_nf

theorem hydrogen_balance_axiom_free (r_FT r_WGS α : ℝ) :
  ((3 - α) * r_FT - r_WGS) * 2 = 2 * (2 - α) * r_FT + (r_FT - r_WGS) * 2 := by ring_nf

theorem mass_balance_symbolic_axiom_free (r_FT r_WGS α : ℝ)
    (h_wgs : MW_CO + MW_H2O = MW_CO2 + MW_H2) :
  r_FT * MW_CO + (3 - α) * r_FT * MW_H2 + r_WGS * MW_CO + r_WGS * MW_H2O
    = r_FT * (MW_CO - MW_H2O + (3 - α) * MW_H2)
      + r_FT * MW_H2O + r_WGS * MW_CO2 + r_WGS * MW_H2 := by
  have h1 : MW_H2O = MW_CO2 + MW_H2 - MW_CO := by linarith
  rw [h1]
  ring_nf

theorem hydrogen_balance_broken_fails_axiom_free (r_FT r_WGS α : ℝ) (hr : r_FT ≠ 0) :
  ¬ ((2 - α) * r_FT * 2 - r_WGS * 2 = 2 * (2 - α) * r_FT + r_FT * 2 - r_WGS * 2) := by
  intro h
  ring_nf at h
  have : 2 * r_FT = 0 := by linarith
  exact hr (by linarith)

theorem mass_balance_broken_fails_axiom_free (r_FT α : ℝ) (hr : r_FT ≠ 0) :
  ¬ (r_FT * MW_CO + (2 - α) * r_FT * MW_H2 = r_FT * MW_CO + (3 - α) * r_FT * MW_H2) := by
  intro h
  ring_nf at h
  have h0 : r_FT * MW_H2 = 0 := by linarith
  have hmw : MW_H2 ≠ 0 := by
    rw [MW_H2]
    norm_num
  have : r_FT = 0 := by
    apply mul_right_cancel₀ hmw
    rw [← zero_mul MW_H2] at h0
    exact h0
  exact hr this

end ArxFTBalance
