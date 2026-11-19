"""History queries stay private, searchable and bounded at collector scale."""

import json
import time
from uuid import uuid4

import pytest
from django.core import signing
from django.db import connection
from django.test.utils import CaptureQueriesContext

from plane.quality.daq_incidents import SALT, SYSTEM, TYPE, fingerprint
from plane.quality.models import BusinessNumber, Defect, DefectEvent, SourceLink
from plane.tests.contract.app import test_daq_reporting
from plane.tests.contract.app.test_daq_reporting import call, revoke_grants

reporting = test_daq_reporting.reporting

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
BASE = "/api/quality-auth/daq-reports/"


def create_reports(reporting, count=4):
    project, user, payload, state = reporting
    statuses = ["open", "in_progress", "resolved", "closed"]
    defects, links, events, numbers = [], [], [], []
    for number in range(1, count + 1):
        data = {
            **payload,
            "eventId": str(uuid4()),
            "title": f"本条相机异常 {number}",
            "description": f"检查日志描述 {number}",
            "sourceReference": f"session-{number}",
        }
        defect = Defect(
            project=project,
            created_by=user,
            status=statuses[(number - 1) % 4],
            title=data["title"],
            description=data["description"],
        )
        link = SourceLink(
            project=project,
            created_by=user,
            defect=defect,
            source_system=SYSTEM,
            source_instance="daq-device",
            record_type=TYPE,
            record_id=f"16:{data['eventId']}",
            task_id="",
            package_id="",
        )
        record = {
            "linkId": str(link.id),
            "defectId": str(defect.id),
            "projectId": str(project.id),
            "sourceInstance": "daq-device",
            "actorId": str(user.id),
            "externalActor": 16,
            "recordId": link.record_id,
            "requestHash": fingerprint(data),
            "payload": data,
            "authorityMode": "report_only",
        }
        events.append(
            DefectEvent(
                project=project,
                created_by=user,
                defect=defect,
                status="open",
                note=json.dumps({"incidentSignature": signing.dumps(record, salt=SALT, compress=True)}),
            )
        )
        numbers.append(
            BusinessNumber(
                project=project,
                workspace=project.workspace,
                resource="quality.defect",
                object_id=defect.id,
                number=number,
                code=f"{project.identifier}-D-{number}",
            )
        )
        defects.append(defect)
        links.append(link)
    Defect.objects.bulk_create(defects)
    SourceLink.objects.bulk_create(links)
    DefectEvent.objects.bulk_create(events)
    BusinessNumber.objects.bulk_create(numbers)
    return project, defects, links, state


def test_history_status_filter_counts_across_all_states_and_paginates(reporting):
    project, defects, links, state = create_reports(reporting, 12)
    result = call(BASE + "?status=resolved&per_page=2&page=2")
    assert result.status_code == 200, result.content
    assert result.data["count"] == 3
    assert len(result.data["results"]) == 1
    assert all(row["status"] == "resolved" for row in result.data["results"])
    assert result.data["status_counts"] == {"all": 12, "open": 3, "in_progress": 3, "pending_tech": 0, "needs_tech": 0, "resolved": 3, "closed": 3}


@pytest.mark.parametrize(
    "term,expected", [("session-3", 1), ("检查日志描述 2", 1), ("ANYDEST-D-4", 1), ("相机异常", 4), ("不存在", 0)]
)
def test_history_search_matches_code_title_description_or_source_reference(reporting, term, expected):
    from urllib.parse import urlencode

    create_reports(reporting)
    result = call(BASE + "?" + urlencode({"search": term}))
    assert result.status_code == 200, result.content
    assert result.data["count"] == expected
    assert result.data["status_counts"]["all"] == expected


def test_search_counts_remain_global_when_selected_status_has_no_matches(reporting):
    create_reports(reporting)
    result = call(BASE + "?search=session-3&status=closed")
    assert result.status_code == 200, result.content
    assert result.data["count"] == 0
    assert result.data["status_counts"]["resolved"] == 1
    assert result.data["status_counts"]["closed"] == 0


@pytest.mark.parametrize("query", ["status=other", "search=" + "x" * 201])
def test_history_rejects_invalid_filter_inputs(reporting, query):
    result = call(BASE + "?" + query)
    assert result.status_code == 400


def test_history_bad_signature_other_actor_and_revoked_source_not_counted(reporting):
    project, defects, links, state = create_reports(reporting)
    DefectEvent.objects.filter(defect=defects[0]).update(note="invalid signature")
    SourceLink.objects.filter(pk=links[1].id).update(record_id="17:changed")
    result = call(BASE)
    assert result.status_code == 200, result.content
    assert result.data["count"] == 2
    assert result.data["status_counts"]["all"] == 2
    revoke_grants(state)
    result = call(BASE)
    assert result.status_code == 200, result.content
    assert result.data["count"] == 0
    assert result.data["status_counts"]["all"] == 0


@pytest.mark.parametrize("total", [1000, 4000])
def test_thousand_reports_use_request_local_authority_cache_and_page_only_receipts(reporting, total):
    project, defects, links, state = create_reports(reporting, total)

    started = time.monotonic()
    with CaptureQueriesContext(connection) as queries:
        result = call(BASE + "?per_page=20&page=12" + ("&status=in_progress" if total == 4000 else ""))
    elapsed = time.monotonic() - started
    assert result.status_code == 200, result.content
    assert result.data["count"] == (total // 4 if total == 4000 else total)
    assert len(result.data["results"]) == 20
    if total == 4000:
        assert all(row["status"] == "in_progress" for row in result.data["results"])
    assert result.data["status_counts"] == {
        "all": total,
        "open": total // 4,
        "in_progress": total // 4,
        "pending_tech": 0,
        "needs_tech": 0,
        "resolved": total // 4,
        "closed": total // 4,
    }

    assert len(queries) <= 160, len(queries)
    print(f"history{total}: {elapsed:.3f}s, SQL={len(queries)}, sourceHTTP=0, pageRows=20")
    revoke_grants(state)
    revoked = call(BASE + "?per_page=20&page=1")
    assert revoked.status_code == 200 and revoked.data["count"] == 0
