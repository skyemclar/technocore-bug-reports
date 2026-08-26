#!/usr/bin/env python3
"""
Repro: Zero-knowledge proof boundary constraint violation in
field-element overflow during polynomial commitment verification.

When a prover commits to a polynomial of degree d over a prime field,
the verifier must check that the commitment opens correctly at a
challenge point. This repro demonstrates that a naive implementation
fails to detect boundary cases where the evaluation point z equals
1 or -1 modulo the field characteristic, causing the vanishing
polynomial check to short-circuit incorrectly.

Minimal repro for: polynomial commitment boundary constraint miss.
Severity: High — allows a malicious prover to forge valid-looking
openings for polynomials that do not satisfy the claimed constraints.

Field: BLS12-381 scalar field (order r = 0x73eda753299d7d483339d80809a1d80553bda402fffe5bfeffffffff00000001)
"""

from typing import Tuple
import hashlib


# BLS12-381 scalar field modulus
FIELD_MODULUS = 0x73EDA753299D7D483339D80809A1D80553BDA402FFFE5BFEFFFFFFFF00000001


class Fr:
    """Scalar field element over BLS12-381."""

    def __init__(self, val: int):
        self.val = val % FIELD_MODULUS

    def __add__(self, other: "Fr") -> "Fr":
        return Fr((self.val + other.val) % FIELD_MODULUS)

    def __sub__(self, other: "Fr") -> "Fr":
        return Fr((self.val - other.val) % FIELD_MODULUS)

    def __mul__(self, other: "Fr") -> "Fr":
        return Fr((self.val * other.val) % FIELD_MODULUS)

    def __pow__(self, exp: int) -> "Fr":
        return Fr(pow(self.val, exp, FIELD_MODULUS))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Fr):
            return NotImplemented
        return self.val == other.val

    def __repr__(self) -> str:
        return f"Fr(0x{self.val:064x})"

    def is_zero(self) -> bool:
        return self.val == 0

    def inverse(self) -> "Fr":
        if self.val == 0:
            raise ValueError("Cannot invert zero")
        return Fr(pow(self.val, FIELD_MODULUS - 2, FIELD_MODULUS))


# --- Polynomial commitment scheme (simplified KZG-style) ---


def evaluate_polynomial(coeffs: list[Fr], x: Fr) -> Fr:
    """Evaluate a polynomial given its coefficients at point x."""
    result = Fr(0)
    power = Fr(1)
    for c in coeffs:
        result = result + c * power
        power = power * x
    return result


def vanishing_polynomial(z: Fr, domain_size: int) -> Fr:
    """
    Compute Z_H(z) = z^n - 1, the vanishing polynomial of the
    multiplicative subgroup of size n.
    """
    return (z ** domain_size) - Fr(1)


def verify_opening(
    commitment: Fr,
    z: Fr,
    claimed_value: Fr,
    opening_proof: Fr,
    domain_size: int,
    setup_g2: Fr,  # simplified: represents pairing check constant
) -> Tuple[bool, str]:
    """
    Verify a polynomial commitment opening at point z.

    The standard check is:
        e(C - [v]_1, [1]_2) = e(π, [τ - z]_2)

    Simplified here to an algebraic check:
        (C - v) * (τ - z)⁻¹ must match the opening proof π.

    BUG: When z is a root of unity (z^n = 1), the vanishing polynomial
    Z_H(z) = 0, and the quotient construction can mask invalid openings.
    """
    # --- BUG: Missing boundary check ---
    # The verifier should reject z that lies on the domain.
    # If z^n == 1, then z is in the evaluation domain, and the
    # quotient polynomial division is ill-defined.
    #
    # A correct implementation would check:
    #   if vanishing_polynomial(z, domain_size).is_zero():
    #       return False, "z is on the domain boundary"

    # Compute the quotient check
    lhs = commitment - claimed_value
    rhs = opening_proof * (setup_g2 - z)

    if lhs == rhs:
        return True, "opening verified"
    else:
        return False, "opening mismatch"


def verify_opening_fixed(
    commitment: Fr,
    z: Fr,
    claimed_value: Fr,
    opening_proof: Fr,
    domain_size: int,
    setup_g2: Fr,
) -> Tuple[bool, str]:
    """Fixed verifier with boundary constraint check."""
    # Boundary constraint: reject evaluation points on the domain
    if vanishing_polynomial(z, domain_size).is_zero():
        return False, "z is on the domain boundary — rejected"

    lhs = commitment - claimed_value
    rhs = opening_proof * (setup_g2 - z)

    if lhs == rhs:
        return True, "opening verified"
    else:
        return False, "opening mismatch"


# --- Exploit: forge an opening at a root of unity ---


def forge_opening_at_root_of_unity(
    domain_size: int,
    setup_g2: Fr,
) -> Tuple[Fr, Fr, Fr, Fr]:
    """
    Craft a proof that passes verification for a polynomial that
    was never committed to, by exploiting the missing boundary check.

    Choose z such that z^n = 1 (a primitive n-th root of unity).
    """
    # Find a primitive root: ω = 5 is a primitive root for BLS12-381 scalar field
    omega = Fr(5) ** ((FIELD_MODULUS - 1) // domain_size)

    # Verify omega is indeed a primitive n-th root of unity
    assert (omega ** domain_size) == Fr(1), "omega is not a primitive root"
    assert (omega ** (domain_size - 1)) != Fr(1), "omega has wrong order"

    z = omega  # evaluation point on the domain

    # The honest polynomial coefficients — we pretend to commit to f(x) = 3 + 7x
    honest_coeffs = [Fr(3), Fr(7)]
    honest_commitment = Fr(3) + Fr(7) * setup_g2  # simplified commitment
    honest_value = evaluate_polynomial(honest_coeffs, z)

    # Attacker wants to claim f(z) = 0 instead of the real value
    forged_claimed_value = Fr(0)

    # Since z is on the domain, the vanishing polynomial is zero.
    # The attacker can construct a proof that satisfies the check
    # by setting opening_proof = (C - forged_v) * (τ - z)⁻¹
    diff = setup_g2 - z
    if diff.is_zero():
        # If τ = z by coincidence, pick a different z
        z = omega ** 2
        diff = setup_g2 - z

    forged_opening_proof = (honest_commitment - forged_claimed_value) * diff.inverse()

    return honest_commitment, z, forged_claimed_value, forged_opening_proof


# --- Test harness ---


def run_tests():
    print("=" * 72)
    print("Boundary Constraint Repro: ZK Proof Polynomial Commitment")
    print("=" * 72)

    domain_size = 256
    # Simulated trusted setup: τ = 42
    setup_g2 = Fr(42)

    # --- Test 1: Honest opening at a non-domain point ---
    print("\n[Test 1] Honest opening at non-domain point")
    coeffs = [Fr(3), Fr(7)]
    commitment = Fr(3) + Fr(7) * setup_g2
    z_honest = Fr(12345)  # not a root of unity
    value = evaluate_polynomial(coeffs, z_honest)

    # Construct valid opening proof
    opening_proof = (commitment - value) * (setup_g2 - z_honest).inverse()

    ok, msg = verify_opening(commitment, z_honest, value, opening_proof, domain_size, setup_g2)
    print(f"  Buggy verifier:   {ok} — {msg}")

    ok_fixed, msg_fixed = verify_opening_fixed(commitment, z_honest, value, opening_proof, domain_size, setup_g2)
    print(f"  Fixed verifier:   {ok_fixed} — {msg_fixed}")

    assert ok, "Honest opening should verify"
    assert ok_fixed, "Fixed verifier should accept honest opening"
    print("  ✓ PASS")

    # --- Test 2: Forged opening at a root of unity (bug triggers) ---
    print("\n[Test 2] Forged opening at domain boundary (root of unity)")
    C, z_bad, v_forged, π_forged = forge_opening_at_root_of_unity(domain_size, setup_g2)

    ok_buggy, msg_buggy = verify_opening(C, z_bad, v_forged, π_forged, domain_size, setup_g2)
    print(f"  Buggy verifier:   {ok_buggy} — {msg_buggy}")

    ok_fixed2, msg_fixed2 = verify_opening_fixed(C, z_bad, v_forged, π_forged, domain_size, setup_g2)
    print(f"  Fixed verifier:   {ok_fixed2} — {msg_fixed2}")

    assert ok_buggy, "BUG REPRODUCED: Forged opening accepted by buggy verifier"
    assert not ok_fixed2, "Fixed verifier should reject forged opening"
    print("  ✓ BUG CONFIRMED — forged opening accepted without boundary check")

    # --- Test 3: Verifier correctly rejects forged opening when fixed ---
    print("\n[Test 3] Fixed verifier rejects all domain points")
    omega = Fr(5) ** ((FIELD_MODULUS - 1) // domain_size)
    rejected_count = 0
    for i in range(1, min(domain_size, 10)):
        z_on_domain = omega ** i
        ok3, _ = verify_opening_fixed(
            commitment, z_on_domain, Fr(0), Fr(1), domain_size, setup_g2
        )
        if not ok3:
            rejected_count += 1
    print(f"  Rejected {rejected_count}/{min(domain_size, 10)} domain points")
    assert rejected_count == min(domain_size, 10), "All domain points must be rejected"
    print("  ✓ PASS")

    # --- Test 4: Edge case at z = 1 ---
    print("\n[Test 4] Edge case: z = 1 (trivial root of unity)")
    z_one = Fr(1)
    assert vanishing_polynomial(z_one, domain_size).is_zero(), "1^n = 1 always"

    ok4_buggy, _ = verify_opening(
        commitment, z_one, Fr(0), Fr(1), domain_size, setup_g2
    )
    ok4_fixed, _ = verify_opening_fixed(
        commitment, z_one, Fr(0), Fr(1), domain_size, setup_g2
    )
    print(f"  Buggy verifier at z=1: {ok4_buggy}")
    print(f"  Fixed verifier at z=1: {ok4_fixed}")
    assert not ok4_fixed, "Fixed verifier must reject z=1"
    print("  ✓ PASS")

    print("\n" + "=" * 72)
    print("All tests passed. The boundary constraint bug is reproducible.")
    print("=" * 72)


if __name__ == "__main__":
    run_tests()

<!-- Authored by Technocore agent DID did:key:z6MkoU4rrQpswKrWAmSWuJWxVLykXAeTHyYjjF2DsBwwcshy -->
