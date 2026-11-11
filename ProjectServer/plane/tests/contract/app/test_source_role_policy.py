"""First-login role policy accepts the four reporter defaults without administrator escalation."""
import pytest
from plane.quality.connection_settings import ConnectionInput

pytestmark = [pytest.mark.contract]


def parse(mapping):
    return ConnectionInput(data={
        "source_instance": "data-platform", "kind": "data_platform", "base_url": "https://data.example.invalid",
        "login_enabled": True, "login_auto_provision": True, "login_role_map": mapping,
    })


@pytest.mark.parametrize("source_role", ["TeamLeader", "Annotator", "Auditor", "Collector"])
def test_four_source_roles_can_default_to_reporter(source_role):
    policy = parse({source_role: "REPORTER"})
    assert policy.is_valid(), policy.errors
    assert policy.validated_data["login_role_map"][source_role] == "REPORTER"


def test_exact_requested_default_policy_is_accepted():
    mapping = {"Admin": "PLATFORM_ADMIN", "Manager": "PROJECT_MANAGER", **{name: "REPORTER" for name in ["TeamLeader", "Annotator", "Auditor", "Collector"]}}
    policy = parse(mapping)
    assert policy.is_valid(), policy.errors
    assert policy.validated_data["login_role_map"] == mapping


@pytest.mark.parametrize("role", ["PLATFORM_ADMIN", "PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER", "REPORTER"])
def test_pending_cannot_receive_any_business_duty(role):
    policy = parse({"Pending": role})
    assert not policy.is_valid()
    assert "login_role_map" in policy.errors


@pytest.mark.parametrize("source_role", ["Manager", "TeamLeader", "Annotator", "Auditor", "Collector"])
def test_non_admin_source_role_cannot_map_to_administrator(source_role):
    policy = parse({source_role: "PLATFORM_ADMIN"})
    assert not policy.is_valid()
    assert "login_role_map" in policy.errors


@pytest.mark.parametrize("source_role", ["TeamLeader", "Annotator", "Auditor", "Collector"])
@pytest.mark.parametrize("duty", ["TECHNICIAN", "REGRESSION_TESTER"])
def test_administrator_may_keep_explicit_technical_or_test_first_login_policy(source_role, duty):
    policy = parse({source_role: duty})
    assert policy.is_valid(), policy.errors


def test_pending_blank_mapping_stays_unassigned():
    policy = parse({"Pending": ""})
    assert policy.is_valid(), policy.errors
