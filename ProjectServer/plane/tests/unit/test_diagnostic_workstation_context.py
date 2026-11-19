"""Stable signed workstation identity is distinct from a changing execution target."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from plane.quality.diagnostic_context import field_workstation_context
from plane.quality.remote_diagnostics import identity_key

DEVICE = '45f00000-0000-4000-8000-000000000199'
OTHER = '45f00000-0000-4000-8000-000000000200'


def fixture():
    station = SimpleNamespace(pk=UUID(DEVICE), boot_id='boot1', hostname='collector199', username='operator',
        capabilities={'network': {'ip_address': '10.10.10.199'},
                      'robot': {'connected': True, 'username': 'robot', 'host': '10.0.0.1', 'target_revision': 'a'*64}})
    snapshot = {'collector': {'username': 'operator', 'host': '10.10.10.199'},
                'robot': deepcopy(station.capabilities['robot'])}
    run = SimpleNamespace(workstation=station, workstation_id=station.pk, identity_key=identity_key(station),
                          result={'target_snapshot': deepcopy(snapshot)})
    link = SimpleNamespace(device=DEVICE, source_instance='signed-daq-source')
    record = {'payload': {'device': DEVICE}, 'sourceInstance': 'signed-daq-source'}
    return station, run, link, record, snapshot


@pytest.mark.parametrize('change', ['robot_disconnected', 'robot_peer', 'boot', 'operator'])
def test_same_signed_computer_remains_same_when_execution_identity_changes(change):
    station, run, link, record, snapshot = fixture()
    if change == 'robot_disconnected': station.capabilities['robot'] = {'connected': False}
    elif change == 'robot_peer': station.capabilities['robot']['host'] = '10.0.0.2'
    elif change == 'boot': station.boot_id = 'boot2'
    else: station.username = 'another-operator'
    result = field_workstation_context(run, source_link=link, signed_source=record)
    assert result['source_workstation_id'] == DEVICE
    assert result['execution_workstation_id'] == DEVICE
    assert result['same_workstation_identity'] is True
    assert result['execution_target_matches'] is False
    assert result['recorded_target_snapshot'] == snapshot
    assert result['current_robot_status'] == station.capabilities['robot']
    assert result['source_device_binding']['kind'] == 'signed_daq_device'


def test_dhcp_metadata_alone_never_changes_workstation_or_execution_identity():
    station, run, link, record, _ = fixture()
    station.capabilities['network']['ip_address'] = '10.10.10.205'
    result = field_workstation_context(run, source_link=link, signed_source=record)
    assert result['same_workstation_identity'] is True
    assert result['execution_target_matches'] is True
    assert result['current_collector_identity']['ip_address'] == '10.10.10.205'
    assert result['recorded_target_snapshot']['collector']['host'] == '10.10.10.199'


def test_cross_device_is_false_even_if_hostname_user_and_ip_match():
    station, run, link, record, _ = fixture()
    link.device = OTHER; record['payload']['device'] = OTHER
    result = field_workstation_context(run, source_link=link, signed_source=record)
    assert result['same_workstation_identity'] is False
    assert result['source_workstation_id'] == OTHER
    assert result['execution_workstation_id'] == DEVICE


@pytest.mark.parametrize('invalid', ['no_signature', 'mismatch', 'not_uuid', 'missing_device'])
def test_missing_or_inconsistent_signed_source_device_remains_unknown(invalid):
    _, run, link, record, _ = fixture()
    if invalid == 'no_signature': record = None
    elif invalid == 'mismatch': record['payload']['device'] = OTHER
    elif invalid == 'not_uuid': link.device = record['payload']['device'] = 'collector199'
    else: record['payload'].pop('device')
    result = field_workstation_context(run, source_link=link, signed_source=record)
    assert result['same_workstation_identity'] is None
    assert result['source_workstation_id'] is None
    assert result['source_device_binding']['state'] == 'unknown'


def test_manual_binding_identifies_execution_scope_without_inventing_report_source():
    _, run, _, _, _ = fixture()
    result = field_workstation_context(run, manual_binding=True)
    assert result['source_workstation_id'] is None and result['same_workstation_identity'] is None
    assert result['source_device_binding'] == {'kind': 'manual_execution_binding', 'state': 'explicit',
                                              'workstation_id': DEVICE}
    assert result['execution_target_matches'] is True


def test_missing_execution_identity_and_historical_snapshot_are_unknown():
    _, run, link, record, _ = fixture()
    run.identity_key = ''; run.result = {}
    result = field_workstation_context(run, source_link=link, signed_source=record)
    assert result['same_workstation_identity'] is True
    assert result['execution_target_matches'] is None
    assert result['recorded_target_snapshot'] is None
