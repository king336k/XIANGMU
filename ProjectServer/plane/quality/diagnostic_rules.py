# SPDX-License-Identifier: AGPL-3.0-only
"""Deterministic evaluation of versioned rules; client facts remain unverified claims."""

from functools import lru_cache
import math
from pathlib import Path
import yaml


@lru_cache(maxsize=1)
def rules():
    result = []
    for file in sorted(Path(__file__).with_suffix("").glob("*.yaml")):
        result.extend(yaml.safe_load(file.read_text())["rules"])
    return [row for row in result if row.get("enabled", True)]


def rule_score(result):
    """Retain declared rule parameters, never coerce unknown values to a probability."""
    value = result.get("confidence")
    if type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value):
        return {"confidence": float(value), "confidence_source": "rule"}
    return {}


def evaluate(facts):
    facts = dict(facts or {})
    declared, actual = facts.get("declaredSteps"), facts.get("actualSteps")
    if isinstance(declared, (int, float)) and isinstance(actual, (int, float)) and declared > 0:
        facts["stepDiffRatio"] = abs(declared - actual) / declared

    def match(condition):
        value = facts.get(condition["field"])
        op, expected = condition["op"], condition.get("value")
        if op == "NOT_NULL":
            return value not in [None, ""]
        if op == "IS_NULL":
            return condition["field"] in facts and value in [None, ""]
        if op == "EQ":
            return value is not None and str(value) == str(expected)
        if op in {"GT", "RATIO_GT"}:
            try:
                return float(value) > float(expected)
            except (TypeError, ValueError):
                return False
        return False

    matched = [
        row
        for row in rules()
        if (not row.get("packageTypes") or facts.get("packageType") in row["packageTypes"])
        and all(match(condition) for condition in row.get("conditions", []))
    ]
    if facts.get("stepDiffRatio", 0) > 0.2:
        matched = [row for row in matched if row["id"] != "DATA_COMPLETENESS_STEP_MISMATCH_MILD"]
    return [
        {
            "kind": row["id"],
            "title": row["result"]["causeTitle"],
            "samples": [row["result"]["causeDescription"]],
            "recommendations": row["result"].get("recommendations", []),
            "risk": row["result"].get("riskLevel", "INFO"),
            "basis": "来源摘要，需结合现场日志核实",
            **rule_score(row["result"]),
        }
        for row in matched
    ]
