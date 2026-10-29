"""Deterministic rule engine and spatial geometry."""

import math
from types import SimpleNamespace

import pytest

from app.models.compliance_rule import RuleCategory
from app.services import rule_engine as re_
from app.services.spatial_service import ring_area_sqm, point_in_ring, self_intersects, spatial_service


def rule(conditions, code="T-1"):
    return SimpleNamespace(rule_code=code, version=1, title="Test", category=RuleCategory.ACADEMIC, conditions=conditions,
                           handbook_reference=None, description="d")


def test_expression_evaluation_is_exact_and_traced():
    trace = []
    v = re_.evaluate_expr("ceil(app.requested_intake * computed.program_years / 20)", {"app.requested_intake": 300, "computed.program_years": 4}, trace)
    assert v == 60 and "300 * 4 / 20" in trace[0]
    assert re_.evaluate_expr("0.1 + 0.2", {}, []) == re_.to_decimal("0.3")  # no float drift


@pytest.mark.parametrize("expr", ["__import__('os')", "open('x')", "a.b()", "[1,2]", "'text'", "x if 1 else 2"])
def test_unsafe_expressions_rejected(expr):
    with pytest.raises(Exception):
        re_.validate_expr(expr)


def test_rag_outcomes():
    facts = {"docs.faculty_list.present": True, "docs.faculty_list.total_faculty": 9, "app.requested_intake": 300,
             "computed.program_years": 4, "docs.noc.present": True, "docs.noc.valid_until_iso": re_.parse_date("2025-05-31")}
    fac = re_.evaluate_rule(rule({"requires_doc": "faculty_list", "check": {"fact": "docs.faculty_list.total_faculty", "op": ">=",
                                  "value": {"expr": "ceil(app.requested_intake * computed.program_years / 20)"}}}), facts)
    assert fac["rag"] == "red" and "shortfall 51" in fac["message"]
    noc = re_.evaluate_rule(rule({"requires_doc": "noc", "check": {"fact": "docs.noc.valid_until_iso", "op": "valid_on"}}), facts)
    assert noc["rag"] == "amber" and noc["kind"] == "expired"
    missing = re_.evaluate_rule(rule({"requires_doc": "land_document"}), facts)
    assert missing["rag"] == "amber" and missing["actionable_by"] == "institution"
    ok = re_.evaluate_rule(rule({"check": {"fact": "docs.faculty_list.total_faculty", "op": "between", "value": [5, 10]}}), facts)
    assert ok["rag"] == "green"
    soft = re_.evaluate_rule(rule({"check": {"fact": "docs.faculty_list.total_faculty", "op": ">=", "value": 20}, "fail_rag": "amber"}), facts)
    assert soft["rag"] == "amber"


def test_area_units_normalised():
    facts = {"docs.land_document.present": True, "docs.land_document.land_area_acres": 2.0}
    r = re_.evaluate_rule(rule({"requires_doc": "land_document",
                                "check": {"fact": "docs.land_document.land_area_acres", "op": ">=", "value": 8000, "unit": "sqm"}}), facts)
    assert r["rag"] == "green" and "8093.71" in r["message"]  # 2 acres = 8093.71 m²


def test_geodesic_area_and_topology():
    lat = 28.5
    dlat, dlon = 100 / 111320, 100 / (111320 * math.cos(math.radians(lat)))
    sq = [[77.5, lat], [77.5 + dlon, lat], [77.5 + dlon, lat + dlat], [77.5, lat + dlat], [77.5, lat]]
    assert abs(ring_area_sqm(sq) - 10000) < 50
    assert point_in_ring((77.5 + dlon / 2, lat + dlat / 2), sq) and not point_in_ring((77.6, lat), sq)
    assert self_intersects([[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]) and not self_intersects(sq)


def test_blueprint_dimension_check():
    issues = spatial_service.blueprint_issues({"room_dimensions": [
        {"room": "C-1", "stated_sqm": 72, "length_m": 8, "width_m": 9}, {"room": "C-2", "stated_sqm": 70, "length_m": 7, "width_m": 9}]})
    assert len(issues) == 1 and "63" in issues[0]["message"]
