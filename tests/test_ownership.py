"""Unit tests for the ownership / control algorithms (run: python -m pytest -q)."""
import pandas as pd
import pytest

from tbg.config import load_config
from tbg.ownership import compute, make_graph, propagate


def H(rows):
    return pd.DataFrame(rows, columns=["owner", "owned", "pct"]).assign(
        source="t", as_of="", basis="direct", relationship="")


def test_pyramid_example():
    # A holds B 60%, B holds C 40%, A holds C 10% directly
    g = make_graph(H([("A", "B", 60), ("B", "C", 40), ("A", "C", 10)]))
    cf, cr = propagate(g, "A")
    assert cf["C"] == pytest.approx(0.34)
    assert cr["C"] == pytest.approx(0.50)


def test_claessens_example():
    # family F: 11% of A directly, 20% of B, B holds 30% of A -> CF 17%, CR 31%
    g = make_graph(H([("F", "A", 11), ("F", "B", 20), ("B", "A", 30)]))
    cf, cr = propagate(g, "F")
    assert cf["A"] == pytest.approx(0.17)
    assert cr["A"] == pytest.approx(0.31)


def test_no_double_counting_of_one_block():
    # a -> X 50%, a -> Y 50%, Y -> X 50%, X -> C 40%: control of C is 40%, not 80%
    g = make_graph(H([("a", "X", 50), ("a", "Y", 50), ("Y", "X", 50), ("X", "C", 40)]))
    cf, cr = propagate(g, "a")
    assert cr["X"] == pytest.approx(1.0)
    assert cr["C"] == pytest.approx(0.40)


def test_cycle_converges():
    # a -> X 60%, X -> Y 50%, Y -> X 10%
    g = make_graph(H([("a", "X", 60), ("X", "Y", 50), ("Y", "X", 10)]))
    cf, cr = propagate(g, "a")
    assert cf["X"] == pytest.approx(0.6 / (1 - 0.05))
    assert cr["X"] == pytest.approx(0.70)
    assert cr["Y"] == pytest.approx(0.50)


def test_two_stage_widely_held():
    cfg = load_config(None)
    ents = pd.DataFrame({"id": ["P:1", "P:2", "L:W", "C:S1", "C:S2"],
                         "etype": ["person", "person", "listed", "company", "company"],
                         "name": ["MR A ONE", "MR B TWO", "W", "S1", "S2"], "fi_type": ""})
    hold = H([("P:1", "L:W", 8), ("P:2", "L:W", 6), ("L:W", "C:S1", 100), ("C:S1", "C:S2", 51)])
    out = compute(ents, hold, cfg, person_family=None, family_mode="none")
    u = out["uo"][out["uo"].threshold == 0.20].set_index("firm")
    assert u.loc["L:W", "uo_type"] == "widely_held"
    assert u.loc["C:S2", "uo_id"] == "L:W"
    assert u.loc["C:S2", "uo_type"] == "widely_held_corporation"
    assert u.loc["C:S2", "depth"] == 2
