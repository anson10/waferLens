"""Tests for analysis/spc.py — each Western Electric rule, pass and no-flag cases."""

import numpy as np
import pytest

from analysis.spc import rule1, rule2, rule3, rule4, check_series


MEAN = 100.0
STD = 5.0


# --- Rule 1: 1 point beyond 3σ ---

def test_rule1_flags_outlier():
    values = np.array([MEAN] * 9 + [MEAN + 4 * STD])
    flags = rule1(values, MEAN, STD)
    assert flags[-1] is np.bool_(True)
    assert flags[:-1].sum() == 0


def test_rule1_no_flag_within_bounds():
    values = np.array([MEAN + 2 * STD] * 10)
    flags = rule1(values, MEAN, STD)
    assert flags.sum() == 0


# --- Rule 2: 8 consecutive on same side ---

def test_rule2_flags_8_above():
    values = np.array([MEAN + 1] * 8 + [MEAN - 1, MEAN - 1])
    flags = rule2(values, MEAN)
    assert flags[:8].all()


def test_rule2_no_flag_alternating():
    values = np.array([MEAN + 1, MEAN - 1] * 5)
    flags = rule2(values, MEAN)
    assert flags.sum() == 0


def test_rule2_exactly_8_flags():
    values = np.array([MEAN - 1] * 8)
    flags = rule2(values, MEAN)
    assert flags.sum() == 8


# --- Rule 3: 6 points continuously increasing or decreasing ---

def test_rule3_flags_increasing():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 3.0, 3.0])
    flags = rule3(values)
    assert flags[:6].all()
    assert not flags[6]


def test_rule3_flags_decreasing():
    values = np.array([6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
    flags = rule3(values)
    assert flags.all()


def test_rule3_no_flag_flat():
    values = np.array([MEAN] * 8)
    flags = rule3(values)
    assert flags.sum() == 0


def test_rule3_no_flag_short_trend():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 4.0])
    flags = rule3(values)
    assert flags.sum() == 0


# --- Rule 4: 2 of 3 beyond 2σ same side ---

def test_rule4_flags_2of3_above():
    values = np.array([MEAN + 3 * STD, MEAN + 3 * STD, MEAN, MEAN, MEAN])
    flags = rule4(values, MEAN, STD)
    assert flags[0] and flags[1]


def test_rule4_no_flag_opposite_sides():
    # zeros between each extreme ensure no window has 2 on the same side
    values = np.array([MEAN + 3 * STD, MEAN, MEAN - 3 * STD, MEAN, MEAN + 3 * STD, MEAN, MEAN - 3 * STD])
    flags = rule4(values, MEAN, STD)
    assert flags.sum() == 0


def test_rule4_no_flag_within_2sigma():
    values = np.array([MEAN + 1.5 * STD] * 5)
    flags = rule4(values, MEAN, STD)
    assert flags.sum() == 0


# --- check_series integration ---

def test_check_series_returns_violations():
    # 9 identical points above mean triggers rule2; verifies check_series returns violations
    ids = list(range(10))
    values = [MEAN + STD] * 9 + [MEAN - STD]
    violations = check_series(ids, values)
    assert len(violations) > 0


def test_check_series_zero_std_returns_empty():
    ids = list(range(5))
    values = [MEAN] * 5
    assert check_series(ids, values) == []
