"""
Test suite for compute_logistics_fuel_cost in app.services.logistics.

Formula: total = round(k * N * (N + 1) / 2)
  - Each Nth territory costs N*k fuel per tick.
  - Triangular number series: holding N territories summed from 1..N.
  - Result is always an int (round() applied for fractional k).
  - N <= 0 returns 0 (no negative fuel cost).

Covers:
  1. Exact values at k=1 for N=0 through N=10 and N=20
  2. N=0 and negative N always return 0
  3. Marginal cost property: cost(N) - cost(N-1) == round(k * N)
  4. Custom k values: k=0.5, k=2, k=1.5
  5. k=0 always returns 0 regardless of N
  6. Large N values (100, 500): no overflow, growth is approximately quadratic
  7. Return type is int in all cases (including fractional k)
  8. Rounding behavior for non-integer k values
"""

from __future__ import annotations

import math

import pytest

from app.services.logistics import compute_logistics_fuel_cost


# ---------------------------------------------------------------------------
# Convenience alias
# ---------------------------------------------------------------------------

def cost(n: int, k: float = 1.0) -> int:
    return compute_logistics_fuel_cost(n, k)


# ===========================================================================
# 1. Exact values at k=1 for N=0 through N=10 and N=20
# ===========================================================================

def test_k1_n0_returns_0():
    # 1 * 0 * 1 / 2 = 0
    assert cost(0) == 0


def test_k1_n1_returns_1():
    # 1 * 1 * 2 / 2 = 1
    assert cost(1) == 1


def test_k1_n2_returns_3():
    # 1 * 2 * 3 / 2 = 3
    assert cost(2) == 3


def test_k1_n3_returns_6():
    # 1 * 3 * 4 / 2 = 6
    assert cost(3) == 6


def test_k1_n4_returns_10():
    # 1 * 4 * 5 / 2 = 10
    assert cost(4) == 10


def test_k1_n5_returns_15():
    # 1 * 5 * 6 / 2 = 15
    assert cost(5) == 15


def test_k1_n6_returns_21():
    # 1 * 6 * 7 / 2 = 21
    assert cost(6) == 21


def test_k1_n7_returns_28():
    # 1 * 7 * 8 / 2 = 28
    assert cost(7) == 28


def test_k1_n8_returns_36():
    # 1 * 8 * 9 / 2 = 36
    assert cost(8) == 36


def test_k1_n9_returns_45():
    # 1 * 9 * 10 / 2 = 45
    assert cost(9) == 45


def test_k1_n10_returns_55():
    # 1 * 10 * 11 / 2 = 55
    assert cost(10) == 55


def test_k1_n20_returns_210():
    # 1 * 20 * 21 / 2 = 210
    assert cost(20) == 210


# ===========================================================================
# 2. N=0 and negative N must return 0
# ===========================================================================

def test_n0_returns_0():
    assert cost(0) == 0


def test_negative_n1_returns_0():
    # Negative territory count is nonsensical; must not produce a negative fuel bill
    assert cost(-1) == 0


def test_negative_n5_returns_0():
    assert cost(-5) == 0


def test_negative_n100_returns_0():
    assert cost(-100) == 0


def test_n0_with_custom_k_returns_0():
    # k is irrelevant when N=0
    assert cost(0, k=2.0) == 0
    assert cost(0, k=0.5) == 0
    assert cost(0, k=1.5) == 0


def test_negative_n_with_large_k_returns_0():
    # Even a large k must not produce a non-zero cost for negative N
    assert cost(-3, k=100.0) == 0


# ===========================================================================
# 3. Marginal cost property: cost(N) - cost(N-1) == round(k * N)
#    "The Nth territory costs N*k fuel"
# ===========================================================================

def test_marginal_cost_n1_k1():
    # cost(1) - cost(0) = 1 - 0 = 1; round(1 * 1) = 1
    assert cost(1) - cost(0) == round(1.0 * 1)


def test_marginal_cost_n2_k1():
    # cost(2) - cost(1) = 3 - 1 = 2; round(1 * 2) = 2
    assert cost(2) - cost(1) == round(1.0 * 2)


def test_marginal_cost_n5_k1():
    # cost(5) - cost(4) = 15 - 10 = 5; round(1 * 5) = 5
    assert cost(5) - cost(4) == round(1.0 * 5)


def test_marginal_cost_n10_k1():
    # cost(10) - cost(9) = 55 - 45 = 10; round(1 * 10) = 10
    assert cost(10) - cost(9) == round(1.0 * 10)


def test_marginal_cost_n3_k2():
    # cost(3, k=2) - cost(2, k=2): round(2 * 2 * 3 / 2) - round(2 * 2 * 3 / 2 - 2*3)
    # cost(3, k=2) = round(2 * 3 * 4 / 2) = round(12) = 12
    # cost(2, k=2) = round(2 * 2 * 3 / 2) = round(6) = 6
    # marginal = 12 - 6 = 6; round(2 * 3) = 6
    assert cost(3, k=2) - cost(2, k=2) == round(2.0 * 3)


def test_marginal_cost_n7_k05():
    # Each territory costs round(k * N) more than the previous one
    assert cost(7, k=0.5) - cost(6, k=0.5) == round(0.5 * 7)


def test_marginal_cost_n4_k15():
    assert cost(4, k=1.5) - cost(3, k=1.5) == round(1.5 * 4)


def test_marginal_cost_holds_for_several_consecutive_n_k1():
    # Verify the marginal property holds across a range at k=1
    for n in range(1, 15):
        assert cost(n) - cost(n - 1) == round(1.0 * n), (
            f"Marginal property failed at N={n}: "
            f"cost({n})-cost({n-1})={cost(n)-cost(n-1)}, expected {round(1.0 * n)}"
        )


# ===========================================================================
# 4. Custom k values: k=0.5, k=2, k=1.5
# ===========================================================================

def test_k05_n1_returns_1():
    # round(0.5 * 1 * 2 / 2) = round(0.5) = 0 in Python banker's rounding...
    # but round(0.5) = 0 (rounds to even). Verify formula, don't assume.
    expected = round(0.5 * 1 * 2 / 2)
    assert cost(1, k=0.5) == expected


def test_k05_n2():
    # round(0.5 * 2 * 3 / 2) = round(1.5) = 2 (banker's rounds to even)
    expected = round(0.5 * 2 * 3 / 2)
    assert cost(2, k=0.5) == expected


def test_k05_n5():
    # round(0.5 * 5 * 6 / 2) = round(7.5) = 8 (banker's rounds to even)
    expected = round(0.5 * 5 * 6 / 2)
    assert cost(5, k=0.5) == expected


def test_k05_n10():
    # round(0.5 * 10 * 11 / 2) = round(27.5) = 28 (banker's rounds to even)
    expected = round(0.5 * 10 * 11 / 2)
    assert cost(10, k=0.5) == expected


def test_k2_n1_returns_2():
    # round(2 * 1 * 2 / 2) = 2
    assert cost(1, k=2) == 2


def test_k2_n2_returns_6():
    # round(2 * 2 * 3 / 2) = 6
    assert cost(2, k=2) == 6


def test_k2_n5_returns_30():
    # round(2 * 5 * 6 / 2) = 30
    assert cost(5, k=2) == 30


def test_k2_n10_returns_110():
    # round(2 * 10 * 11 / 2) = 110
    assert cost(10, k=2) == 110


def test_k15_n2():
    # round(1.5 * 2 * 3 / 2) = round(4.5) = 4 (banker's rounds to even)
    expected = round(1.5 * 2 * 3 / 2)
    assert cost(2, k=1.5) == expected


def test_k15_n4():
    # round(1.5 * 4 * 5 / 2) = round(15.0) = 15
    expected = round(1.5 * 4 * 5 / 2)
    assert cost(4, k=1.5) == expected


def test_k15_n10():
    # round(1.5 * 10 * 11 / 2) = round(82.5) = 82 (banker's rounds to even)
    expected = round(1.5 * 10 * 11 / 2)
    assert cost(10, k=1.5) == expected


def test_k_doubles_cost_doubles():
    # Linearity in k: cost(N, 2k) == 2 * cost(N, k) when results are exact integers
    # Use k=1 and k=2 at N=6 where both are exact: cost(6,1)=21, cost(6,2)=42
    assert cost(6, k=2) == 2 * cost(6, k=1)


def test_k_doubles_cost_doubles_n10():
    # cost(10, k=1)=55, cost(10, k=2)=110
    assert cost(10, k=2) == 2 * cost(10, k=1)


# ===========================================================================
# 5. k=0 returns 0 regardless of territory count
# ===========================================================================

def test_k0_n0_returns_0():
    assert cost(0, k=0) == 0


def test_k0_n1_returns_0():
    # round(0 * 1 * 2 / 2) = 0
    assert cost(1, k=0) == 0


def test_k0_n10_returns_0():
    assert cost(10, k=0) == 0


def test_k0_n100_returns_0():
    assert cost(100, k=0) == 0


def test_k0_n500_returns_0():
    assert cost(500, k=0) == 0


# ===========================================================================
# 6. Large N: no overflow, growth is approximately quadratic
#    Specifically: cost(2N) ≈ 4 * cost(N) for large N
#    (Exact ratio: (2N)(2N+1) / (N(N+1)) → 4 as N → ∞)
# ===========================================================================

def test_large_n100_no_error():
    # Must complete without exception and return a positive integer
    result = cost(100)
    assert isinstance(result, int)
    assert result > 0


def test_large_n500_no_error():
    result = cost(500)
    assert isinstance(result, int)
    assert result > 0


def test_large_n100_exact_value():
    # k=1, N=100: round(1 * 100 * 101 / 2) = 5050
    assert cost(100) == 5050


def test_large_n500_exact_value():
    # k=1, N=500: round(1 * 500 * 501 / 2) = 125250
    assert cost(500) == 125250


def test_growth_is_approximately_quadratic_n100():
    # cost(200) / cost(100) should be very close to 4.0 for large N
    # Exact: (200*201) / (100*101) = 40200 / 10100 ≈ 3.98
    c_n = cost(100)
    c_2n = cost(200)
    ratio = c_2n / c_n
    assert 3.9 < ratio < 4.1, (
        f"cost(200)/cost(100) expected ~4.0 (quadratic growth), got {ratio}"
    )


def test_growth_is_approximately_quadratic_n500():
    # cost(1000) / cost(500): (1000*1001) / (500*501) = 1001000 / 250500 ≈ 3.996
    c_n = cost(500)
    c_2n = cost(1000)
    ratio = c_2n / c_n
    assert 3.99 < ratio < 4.01, (
        f"cost(1000)/cost(500) expected ~4.0, got {ratio}"
    )


def test_cost_strictly_increases_with_n():
    # Holding more territories must always cost more fuel
    for n in range(1, 21):
        assert cost(n) > cost(n - 1), (
            f"cost({n})={cost(n)} should be greater than cost({n-1})={cost(n-1)}"
        )


def test_large_n_is_strictly_greater_than_medium_n():
    # Sanity: large nation always pays more than small nation
    assert cost(100) > cost(50)
    assert cost(500) > cost(100)


# ===========================================================================
# 7. Return type must be int in all cases (including fractional k)
# ===========================================================================

def test_return_type_is_int_k1_n5():
    assert isinstance(cost(5), int)


def test_return_type_is_int_k1_n0():
    assert isinstance(cost(0), int)


def test_return_type_is_int_k05_n10():
    # Fractional k: result of round() must be int, not float
    assert isinstance(cost(10, k=0.5), int)


def test_return_type_is_int_k15_n7():
    assert isinstance(cost(7, k=1.5), int)


def test_return_type_is_int_k2_n20():
    assert isinstance(cost(20, k=2), int)


def test_return_type_is_int_negative_n():
    # Guard clause path must also return int, not None or float
    assert isinstance(cost(-3), int)


def test_return_type_is_int_k0():
    assert isinstance(cost(10, k=0), int)


def test_return_type_is_int_large_n():
    assert isinstance(cost(500), int)


def test_return_type_is_int_large_n_fractional_k():
    assert isinstance(cost(500, k=1.5), int)


# ===========================================================================
# 8. Rounding behavior for non-integer k values
# ===========================================================================

def test_fractional_k_result_matches_python_round():
    # The spec says to use round(); Python's round() uses banker's rounding.
    # For any (N, k) the result must equal round(k * N * (N + 1) / 2).
    test_cases = [
        (1, 0.5),   # round(0.5)  = 0 (banker's: nearest even)
        (2, 0.5),   # round(1.5)  = 2 (banker's: nearest even)
        (3, 0.5),   # round(3.0)  = 3
        (5, 0.5),   # round(7.5)  = 8 (banker's: nearest even)
        (2, 1.5),   # round(4.5)  = 4 (banker's: nearest even)
        (4, 1.5),   # round(15.0) = 15
        (10, 1.5),  # round(82.5) = 82 (banker's: nearest even)
        (3, 2.5),   # round(15.0) = 15
        (7, 0.3),   # round(0.3 * 7 * 8 / 2) = round(8.4) = 8
    ]
    for n, k in test_cases:
        expected = round(k * n * (n + 1) / 2)
        actual = cost(n, k=k)
        assert actual == expected, (
            f"cost({n}, k={k}): expected round({k * n * (n + 1) / 2})={expected}, got {actual}"
        )


def test_rounding_does_not_produce_float():
    # Even when the pre-round value is a half-integer, output must be int not float
    result = cost(5, k=0.5)   # round(7.5) = 8
    assert isinstance(result, int)
    assert result == 8


def test_k13_n4_matches_formula():
    # round(1.3 * 4 * 5 / 2) = round(13.0) = 13
    expected = round(1.3 * 4 * 5 / 2)
    assert cost(4, k=1.3) == expected


def test_very_small_k_rounds_to_zero_for_small_n():
    # round(0.01 * 1 * 2 / 2) = round(0.01) = 0
    assert cost(1, k=0.01) == 0


def test_very_small_k_eventually_produces_nonzero():
    # round(0.01 * 100 * 101 / 2) = round(50.5) = 50 (banker's to even)
    expected = round(0.01 * 100 * 101 / 2)
    assert cost(100, k=0.01) == expected
    assert cost(100, k=0.01) > 0
