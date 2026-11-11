from plane.quality.diagnostic_rules import evaluate, rules


def test_twelve_reference_rules_are_loaded():
    assert len(rules()) == 12


def test_material_facts_need_evidence_and_severe_mismatch_does_not_also_claim_mild():
    result = evaluate({"declaredSteps": 100, "actualSteps": 40, "schemaVersion": "v3"})
    ids = [row["kind"] for row in result]
    assert "DATA_COMPLETENESS_STEP_MISMATCH_SEVERE" in ids
    assert "DATA_COMPLETENESS_STEP_MISMATCH_MILD" not in ids
    assert all("核实" in row["basis"] for row in result)


def test_malformed_or_missing_numbers_do_not_claim_transfer_size_or_step_loss():
    ids = [row["kind"] for row in evaluate({"declaredSteps": 0, "actualSteps": "bad", "pkgSizeBytes": "unknown"})]
    assert "LARGE_PACKAGE_RISK" not in ids
    assert not any("STEP_MISMATCH" in value for value in ids)


def test_unobserved_schema_is_not_a_confirmed_missing_package_field():
    assert "SCHEMA_FINGERPRINT_MISSING" not in {row["kind"] for row in evaluate({})}
    assert "SCHEMA_FINGERPRINT_MISSING" in {row["kind"] for row in evaluate({"schemaVersion": None})}
