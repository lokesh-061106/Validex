"""Deterministic compliance rule engine (no generative AI).

Every result is computed from extracted facts with exact decimal arithmetic and fixed thresholds,
and carries a human-readable calculation trace, so the same inputs always give the same outcome.

Rule `conditions` (data, editable by admins, versioned):
    {
      "requires_doc": "faculty_list",                    # completeness (missing -> AMBER)
      "check": {
        "fact": "docs.faculty_list.total_faculty",       # value under test (may also be an "expr")
        "op": ">=",                                      # >= > <= < == != between in exists valid_on
        "value": {"expr": "ceil(computed.total_students / 20)"} | 2.5 | [min, max] | "paid",
        "unit": "acres" | "sqm" | "sqft" | "count" | "ratio",   # optional normalisation
        "label": "Regular faculty"
      },
      "on_missing_fact": "amber" | "red" | "skip",       # unreadable value (default amber)
      "fix_hint": "...", "clause": "handbook text shown to officers"
    }

Outcomes (RAG):
    GREEN  requirement met (auto-pass)
    AMBER  document missing, expired or unreadable -> clarification from the institution
    RED    deterministic bound violated -> officer must confirm or override
"""

import ast
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ml.dates import parse_date, today
from app.models.application import Application
from app.models.compliance_rule import ComplianceRule
from app.models.document import Document, DocumentType

GREEN, AMBER, RED, NA = "green", "amber", "red", "not_applicable"
OPS = {">=", ">", "<=", "<", "==", "!=", "between", "in", "exists", "valid_on", "not_expired", "is_true"}
OP_TEXT = {">=": "≥", ">": ">", "<=": "≤", "<": "<", "==": "=", "!=": "≠"}

# Unit normalisation to a base unit per dimension
AREA_TO_SQM = {"sqm": Decimal(1), "sqft": Decimal("0.09290304"), "acres": Decimal("4046.8564224"), "hectares": Decimal(10000)}
DEFAULT_PROGRAM_YEARS = 4  # UG engineering; configurable per rule via computed.program_years


class RuleError(ValueError):
    pass


# ------------------------------------------------------------------ facts

def build_facts(app: Application, docs: list[Document], records: dict[str, Any] | None,
                records_status: str = "unavailable", program_years: int = DEFAULT_PROGRAM_YEARS) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "app.category": app.category.value,
        "app.requested_intake": app.requested_intake,
        "app.academic_year": app.academic_year,
        "computed.today": today(),
        "computed.program_years": program_years,
        "records.status": records_status,
    }
    if app.requested_intake:
        facts["computed.total_students"] = app.requested_intake * program_years
    for dt in DocumentType:
        facts[f"docs.{dt.value}.present"] = False

    infra: dict[str, int] = {}
    for doc in docs:
        prefix = f"docs.{doc.doc_type.value}"
        facts[f"{prefix}.present"] = True
        facts[f"{prefix}.filename"] = doc.original_filename
        data = doc.extracted_data or {}
        for key, value in data.items():
            if isinstance(value, (str, int, float, bool)) and len(str(value)) < 300:
                facts[f"{prefix}.{key}"] = parse_date(value) if key.endswith("_iso") else value
        cv = data.get("infrastructure") or {}
        for obj, count in (cv.get("equipment_counts") or {}).items():
            infra[obj] = max(infra.get(obj, 0), int(count))
        for key, value in (data.get("spatial") or {}).items():
            if isinstance(value, (int, float, str)):
                facts[f"spatial.{key}"] = value
    for obj, count in infra.items():
        facts[f"infra.{obj}"] = count

    observed = facts.get("spatial.observed_footprint_sqm")
    coverage = facts.get("docs.building_plan.ground_coverage_sqm")
    built_up, floors = facts.get("docs.building_plan.built_up_area_sqm"), facts.get("docs.building_plan.floors")
    plan_footprint = coverage or (built_up / floors if built_up and floors else None)
    if observed is not None and plan_footprint:
        facts["computed.plan_footprint_sqm"] = round(float(plan_footprint), 1)
        facts["spatial.footprint_vs_plan_deviation_pct"] = round(abs(float(observed) - float(plan_footprint)) / float(plan_footprint) * 100, 2)

    fac = facts.get("docs.faculty_list.total_faculty")
    if fac and facts.get("computed.total_students"):
        facts["computed.student_faculty_ratio"] = round(facts["computed.total_students"] / fac, 2)

    if records:
        facts.update({
            "records.name": records.get("name"),
            "records.trust": records.get("trust"),
            "records.approved_intake": records.get("approved_intake"),
            "records.faculty_on_record": records.get("faculty_on_record"),
            "records.land_area_acres": records.get("land_area_acres"),
            "records.ter_payment_current": (records.get("ter_payment") or {}).get(app.academic_year, "not_found"),
            "records.open_deficiency_count": len(records.get("open_deficiencies") or []),
            "records.previous_eoa_status": ((records.get("previous_eoa") or [{}])[-1]).get("status"),
        })
    return facts


def rule_applies(rule: ComplianceRule, app: Application) -> bool:
    applies = rule.applies_to or []
    return not applies or app.category.value in applies


# ------------------------------------------------------------ expressions

_FUNCS = {"ceil": lambda x: Decimal(math.ceil(x)), "floor": lambda x: Decimal(math.floor(x)),
          "min": min, "max": max, "round": lambda x, n=0: round(x, int(n)), "abs": abs}


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    raise RuleError("Unsupported name in expression")


def evaluate_expr(expr: str, facts: dict[str, Any], trace: list[str]) -> Decimal:
    """Evaluate a whitelisted arithmetic expression over facts with exact decimals."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise RuleError(f"Invalid expression: {e.msg}") from e

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = _dotted(node)
            if name not in facts or facts[name] is None:
                raise KeyError(name)
            return to_decimal(facts[name])
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if b == 0:
                raise RuleError("Division by zero")
            return a / b
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return Decimal(_FUNCS[node.func.id](*[ev(a) for a in node.args]))
        raise RuleError("Expression may only use numbers, facts, + - * / and ceil/floor/min/max/round/abs")

    result = ev(tree)
    substituted = expr
    for name in sorted({_dotted(n) for n in ast.walk(tree) if isinstance(n, (ast.Name, ast.Attribute))
                        and not (isinstance(n, ast.Name) and n.id in _FUNCS)}, key=len, reverse=True):
        if name in facts:
            substituted = substituted.replace(name, _fmt(facts[name]))
    trace.append(f"{expr} = {substituted} = {_fmt(result)}")
    return result


def validate_expr(expr: str) -> None:
    """Static check used when admins save a rule."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        allowed = (ast.Expression, ast.Constant, ast.Name, ast.Attribute, ast.BinOp, ast.UnaryOp, ast.Call, ast.Load,
                   ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub)
        if not isinstance(node, allowed):
            raise RuleError(f"Disallowed syntax: {type(node).__name__}")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in _FUNCS):
            raise RuleError("Only ceil/floor/min/max/round/abs may be called")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise RuleError("Only numeric constants are allowed")


# ---------------------------------------------------------------- values

def to_decimal(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise RuleError("Boolean is not numeric")
    try:
        return Decimal(str(v).replace(",", "").strip())
    except (InvalidOperation, ValueError) as e:
        raise RuleError(f"'{v}' is not a number") from e


def normalise(value: Decimal, unit: str | None, fact: str) -> tuple[Decimal, str]:
    """Convert area facts to the rule's unit; facts carry their unit in the name (e.g. *_acres, *_sqm)."""
    if unit not in AREA_TO_SQM:
        return value, unit or ""
    src = next((u for u in AREA_TO_SQM if fact.endswith(f"_{u}")), unit)
    return value * AREA_TO_SQM[src] / AREA_TO_SQM[unit], unit


def _fmt(v: Any) -> str:
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, Decimal):
        q = v.quantize(Decimal("0.01")).normalize()
        return f"{q:f}"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


@dataclass
class Resolved:
    value: Any
    shown: str


def resolve(spec: Any, facts: dict[str, Any], trace: list[str]) -> Resolved:
    if isinstance(spec, dict) and "expr" in spec:
        r = evaluate_expr(spec["expr"], facts, trace)
        return Resolved(r, _fmt(r))
    if isinstance(spec, dict) and "fact" in spec:
        if facts.get(spec["fact"]) is None:
            raise KeyError(spec["fact"])
        return Resolved(facts[spec["fact"]], _fmt(facts[spec["fact"]]))
    return Resolved(spec, _fmt(spec) if not isinstance(spec, list) else " – ".join(_fmt(x) for x in spec))


# ------------------------------------------------------------- evaluation

def evaluate_rule(rule: ComplianceRule, facts: dict[str, Any], as_of: date | None = None) -> dict[str, Any]:
    cond = rule.conditions or {}
    as_of = as_of or today()
    out: dict[str, Any] = {
        "rule_code": rule.rule_code, "rule_version": rule.version, "title": rule.title,
        "category": rule.category.value, "fix_hint": cond.get("fix_hint"), "doc_type": cond.get("requires_doc"),
        "handbook_reference": rule.handbook_reference, "clause": cond.get("clause") or rule.description,
        "trace": [],
    }
    trace: list[str] = out["trace"]
    req = cond.get("requires_doc")
    if req and not facts.get(f"docs.{req}.present"):
        trace.append(f"Required document '{req}' not found among current uploads")
        return {**out, "rag": AMBER, "kind": "missing_document", "actionable_by": "institution",
                "message": f"Required document not submitted: {req.replace('_', ' ')}"}

    check = cond.get("check")
    if not check:
        return {**out, "rag": GREEN, "kind": "presence", "message": "Required document submitted",
                "evidence": facts.get(f"docs.{req}.filename") if req else None}

    op = check.get("op")
    if op not in OPS:
        return {**out, "rag": RED, "kind": "invalid_rule", "actionable_by": "officer", "message": f"Rule has unknown operator '{op}'"}
    label = check.get("label") or check.get("fact") or check.get("expr", "value")
    fact_name = check.get("fact")
    out.update({"fact": fact_name, "op": op,
                "evidence": facts.get(f"docs.{req}.filename") if req else (fact_name or "").split(".")[0]})
    missing_mode = cond.get("on_missing_fact", "amber")
    try:
        actual = resolve({"expr": check["expr"]} if "expr" in check else {"fact": fact_name}, facts, trace)
        expected = resolve(check.get("value"), facts, trace) if op not in ("exists", "is_true", "valid_on", "not_expired") else None
    except KeyError as missing:
        if missing_mode == "skip":
            return {**out, "rag": NA, "kind": "missing_fact", "message": f"{label}: not applicable ({missing} unavailable)"}
        trace.append(f"Value '{missing}' could not be read from the submission")
        return {**out, "rag": RED if missing_mode == "red" else AMBER, "kind": "missing_fact",
                "actionable_by": "institution", "message": f"{label}: could not be read from the submitted documents"}
    except RuleError as e:
        return {**out, "rag": AMBER, "kind": "type_error", "actionable_by": "institution", "message": f"{label}: {e}"}

    out["actual"] = actual.shown
    out["expected"] = expected.shown if expected else None
    try:
        rag, message = _compare(op, actual.value, expected.value if expected else None, check, fact_name or "", label, as_of, trace)
    except RuleError as e:
        return {**out, "rag": AMBER, "kind": "type_error", "actionable_by": "institution", "message": f"{label}: {e}"}
    kind = "expired" if op in ("valid_on", "not_expired") and rag != GREEN else ("pass" if rag == GREEN else "bound_violation")
    actionable = None if rag == GREEN else ("institution" if kind == "expired" else "officer")
    if rag == RED and cond.get("fail_rag") == AMBER:
        # Failures the institution itself must remedy (e.g. unpaid fee) are clarification items, not anomalies
        rag, actionable = AMBER, "institution"
    return {**out, "rag": rag, "kind": kind, "message": message, "actionable_by": actionable}


def _compare(op, actual, expected, check, fact, label, as_of, trace) -> tuple[str, str]:
    if op in ("valid_on", "not_expired"):
        d = actual if isinstance(actual, date) else parse_date(str(actual))
        if d is None:
            raise RuleError(f"'{actual}' is not a date")
        ok = d >= as_of
        trace.append(f"valid until {_fmt(d)} {'≥' if ok else '<'} assessment date {_fmt(as_of)}")
        return (GREEN, f"{label}: valid until {_fmt(d)}") if ok else (AMBER, f"{label}: expired on {_fmt(d)} (assessed {_fmt(as_of)})")
    if op == "exists":
        ok = actual not in (None, "", [])
        trace.append(f"{label} {'present' if ok else 'absent'}")
        return (GREEN, f"{label}: present") if ok else (AMBER, f"{label}: not found")
    if op == "is_true":
        return (GREEN, f"{label}: yes") if bool(actual) else (RED, f"{label}: no")
    if op == "in":
        ok = actual in (expected or [])
        trace.append(f"{_fmt(actual)} {'∈' if ok else '∉'} {expected}")
        return (GREEN if ok else RED), f"{label}: {_fmt(actual)}"
    if op in ("==", "!=") and not _is_number(actual):
        ok = (str(actual) == str(expected)) == (op == "==")
        trace.append(f"'{actual}' {OP_TEXT[op]} '{expected}' → {'true' if ok else 'false'}")
        return (GREEN if ok else RED), f"{label}: {_fmt(actual)} (required {OP_TEXT[op]} {_fmt(expected)})"

    unit = check.get("unit")
    a, unit_shown = normalise(to_decimal(actual), unit, fact)
    unit_shown = {"sqm": "m²", "sqft": "sq ft", "acres": "acres", "hectares": "ha"}.get(unit_shown, "")
    if op == "between":
        lo, hi = (to_decimal(x) for x in expected)
        ok = lo <= a <= hi
        trace.append(f"{_fmt(lo)} ≤ {_fmt(a)} ≤ {_fmt(hi)} → {'true' if ok else 'false'}")
        msg = f"{label}: {_fmt(a)} {unit_shown} (required {_fmt(lo)}–{_fmt(hi)})".replace("  ", " ")
        return (GREEN if ok else RED), msg
    b = to_decimal(expected)
    ok = {">=": a >= b, ">": a > b, "<=": a <= b, "<": a < b, "==": a == b, "!=": a != b}[op]
    trace.append(f"{_fmt(a)} {OP_TEXT[op]} {_fmt(b)} → {'true' if ok else 'false'}")
    gap = ""
    if not ok and op in (">=", ">"):
        gap = f"; shortfall {_fmt(b - a)}"
    elif not ok and op in ("<=", "<"):
        gap = f"; excess {_fmt(a - b)}"
    msg = f"{label}: {_fmt(a)}{(' ' + unit_shown) if unit_shown else ''} (required {OP_TEXT[op]} {_fmt(b)}{gap})"
    return (GREEN if ok else RED), msg


def _is_number(v: Any) -> bool:
    try:
        to_decimal(v)
        return True
    except RuleError:
        return False


def infra_norms(rules: list[ComplianceRule], app: Application | None = None) -> list[dict[str, Any]]:
    """Equipment minimums for the CV module, taken from active rules on infra.* facts."""
    norms = []
    for r in rules:
        if not r.is_active or (app is not None and not rule_applies(r, app)):
            continue
        check = (r.conditions or {}).get("check") or {}
        fact = check.get("fact") or ""
        if fact.startswith("infra.") and check.get("op") in (">=", ">") and isinstance(check.get("value"), (int, float)):
            minimum = check["value"] + (1 if check["op"] == ">" else 0)
            norms.append({"object": fact.split(".", 1)[1], "min": minimum, "rule_code": r.rule_code,
                          "label": check.get("label") or r.title})
    return norms
