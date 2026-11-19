"""Time-window selection must state its clock uncertainty and preserve fault fallbacks."""
import io
import json

from plane.quality.diagnostic_time_window import event_context, select_sample


def selected(text, title='2026-11-19T20:44:14+08:00 reset failed', context=None):
    return select_sample(text.encode(), context or event_context(title))


def test_prefers_five_minutes_and_explicitly_counts_omitted_sample_records():
    text = '2026-11-19T12:00:00Z INFO old\n2026-11-19T12:44:14Z ERROR actual_fault\n2026-11-19T13:00:00Z INFO later\n'
    sample, meta = selected(text)
    assert b'actual_fault' in sample and b'INFO old' not in sample and b'INFO later' not in sample
    assert meta['selection_scope'] == 'event_plus_minus_5m'
    assert meta['omitted_count'] == 2
    assert meta['selection_input_scope'] == 'bounded_scanned_sample'
    assert meta['window']['anchor_source'] == 'explicit_event_datetime'


def test_midnight_window_spans_adjacent_dates():
    sample, meta = selected('2026-11-18T23:58:00Z ERROR previous_day\n2026-11-19T00:03:00Z INFO next_day\n',
                            title='2026-11-19T00:01:00Z failure')
    assert b'previous_day' in sample and b'next_day' in sample
    assert meta['selection_scope'] == 'event_plus_minus_5m'


def test_clock_only_title_never_gets_date_or_timezone_from_reported_at():
    context = event_context('[20:44:14] reset failed', json.dumps({'reportedAt': '2026-11-19T12:45:30Z'}))
    assert context['anchors'] == []
    assert 'event_date_unknown' in context['ambiguities']
    sample, meta = selected('2026-11-19T12:45:30Z INFO report\nERROR undated root cause\n', context=context)
    assert b'undated root cause' in sample and meta['selection_scope'] == 'global_fallback'


def test_dated_node_log_can_supply_candidate_date_but_never_invent_timezone():
    document = {'sourceSystem': 'ENGRAM_TELEOP_DAQ', 'reportedAt': '2026-11-20T04:00:00Z', 'evidence': {'observations': {
        'teleop': {'capturedAt': '2026-11-19T12:45:30Z', 'data': {'observations': {'nodes': {'data': {'processes': [
            {'name': 'any_node', 'lines': ['[2026-11-19 20:44:14.597] ERROR root cause']}]}}}}}}}}
    context = event_context('[20:44:14] reset failure', json.dumps(document))
    assert context['anchors'] == ['2026-11-19T20:44:14.597000']
    assert context['anchor_source'] == 'dated_log_matching_event_clock'
    assert 'event_timezone_unknown' in context['ambiguities']
    assert context['capture_times'] == ['2026-11-19T12:45:30+00:00']


def test_multiple_matching_dates_remain_explicitly_ambiguous():
    text = '2026-11-18 20:44:14 ERROR old\n2026-11-19 20:44:14 ERROR new\n'
    context = event_context('[20:44:14] failure', text)
    assert len(context['anchors']) == 2
    assert 'multiple_event_dates' in context['ambiguities']


def test_missing_nearby_fault_expands_to_thirty_minutes():
    sample, meta = selected('2026-11-19T12:44:14Z INFO nearby\n2026-11-19T12:20:00Z ERROR earlier_root\n')
    assert b'earlier_root' in sample and meta['selection_scope'] == 'event_plus_minus_30m'


def test_missing_thirty_minute_fault_expands_to_event_day():
    sample, meta = selected('2026-11-19T12:44:14Z INFO nearby\n2026-11-19T02:20:00Z ERROR early_root\n')
    assert b'early_root' in sample and meta['selection_scope'] == 'event_day'


def test_missing_fault_on_event_day_expands_globally():
    sample, meta = selected('2026-11-19T12:44:14Z INFO nearby\n2026-11-17T02:20:00Z ERROR prior_root\n')
    assert b'prior_root' in sample and meta['selection_scope'] == 'global_fallback'


def test_undated_faults_survive_even_when_five_minute_window_has_an_error():
    sample, meta = selected('ERROR unknown_time_root\n2026-11-19T12:44:14Z ERROR nearby_error\n')
    assert b'unknown_time_root' in sample and b'nearby_error' in sample
    assert meta['untimed_fault_count'] == 1


def test_first_and_last_causes_survive_out_of_window_retry_noise():
    raw = '2026-11-18T00:00:00Z ERROR first_cause\n2026-11-19T12:44:14Z ERROR retry\n2026-11-20T00:00:00Z ERROR last_cause\n'
    sample, meta = selected(raw)
    assert all(value in sample for value in (b'first_cause', b'retry', b'last_cause'))
    assert meta['out_of_window_boundary_fault_count'] == 2


def test_incompatible_naive_and_aware_clocks_preserve_fault_without_assuming_local_zone():
    sample, meta = selected('2026-11-19 20:44:14 ERROR local_clock_fault\n2026-11-19T12:44:14Z ERROR utc_fault\n')
    assert b'local_clock_fault' in sample
    assert 'incomparable_log_clock' in meta['window']['ambiguities']


def test_collect_keeps_full_integrity_scan_distinct_from_model_time_selection():
    from plane.quality.log_evidence import collect
    context = event_context('2026-11-19T12:44:14Z failure')
    raw = (b'2026-11-19T01:00:00Z INFO old\n' * 15000 +
           b'2026-11-19T12:44:14Z ERROR actual_window_fault\n' +
           b'2026-11-19T23:00:00Z INFO later\n' * 15000)
    sample, scanned, incomplete = collect(io.BytesIO(raw), len(raw), window=context)
    sample, meta = select_sample(sample, context)
    assert scanned == len(raw) and not incomplete
    assert b'actual_window_fault' in sample
    assert meta['selection_input_scope'] == 'bounded_scanned_sample'


def test_reported_at_matching_clock_still_cannot_supply_incident_date():
    context = event_context('[20:44:14] failure', json.dumps({'reportedAt': '2026-11-19T20:44:14Z'}))
    assert context['anchors'] == []
    assert context['anchor_source'] is None


def test_capture_time_proxy_is_not_presented_as_actual_failure_time_and_expands():
    document = {'sourceSystem': 'ENGRAM_TELEOP_DAQ', 'evidence': {'observations': {
        'teleop': {'capturedAt': '2026-11-19T12:45:00Z'}}}}
    context = event_context('reset failed', json.dumps(document))
    sample, meta = select_sample(b'2026-11-19T08:00:00Z ERROR earlier_failure\n', context)
    assert context['anchor_source'] == 'capture_time_proxy'
    assert 'capture_time_is_not_event_time' in meta['window']['ambiguities']
    assert meta['selection_scope'] == 'event_day'
    assert b'earlier_failure' in sample


def test_clock_candidate_date_inference_crosses_midnight_without_inventing_zone():
    context = event_context('[00:01:00] failure', '2026-11-18 23:59:00 ERROR before_midnight\n')
    assert context['anchors'] == ['2026-11-19T00:01:00']
    assert 'event_timezone_unknown' in context['ambiguities']


def test_full_feedback_process_selection_preserves_atomic_lines_and_original_indices():
    from plane.quality.log_evidence import collect
    lines = ['2026-11-19T11:00:00Z INFO old', '2026-11-19T12:44:14Z ERROR root',
             '2026-11-19T12:44:15Z INFO followup', '2026-11-19T15:00:00Z INFO later']
    document = {'sourceSystem': 'ENGRAM_TELEOP_DAQ', 'evidence': {'observations': {'teleop': {
        'capturedAt': '2026-11-19T13:00:00Z', 'data': {'observations': {'nodes': {'data': {'processes': [
            {'name': 'arbitrary_node', 'lines': lines}]}}}}}}}}
    raw = json.dumps(document).encode()
    context = event_context('2026-11-19T12:44:14Z failure')
    sample, scanned, incomplete = collect(io.BytesIO(raw), len(raw), window=context)
    sample, meta = select_sample(sample, context)
    rows = [json.loads(row) for row in sample.decode().splitlines()]
    node = next(row for row in rows if row.get('process') == 'arbitrary_node')
    assert node['selection_scope'] == 'event_plus_minus_5m'
    assert node['fault_line_numbers'] == [2]
    assert node['omitted_count'] == 2
    assert node['latest_lines'] == lines[1:3]
    assert meta['selection_input_scope'] == 'uploaded_producer_log_lines'
    assert meta['omitted_count'] == 2
    assert scanned == len(raw) and not incomplete
    assert 'event_text' not in meta['window']


def test_inspect_sources_separate_window_omission_from_full_scan_and_verify_hash(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from plane.quality import diagnostic_materials
    raw = (b'2026-11-19T12:00:00Z INFO older\n2026-11-19T12:44:14Z ERROR root\n'
           b'2026-11-19T13:00:00Z INFO later\n')
    (tmp_path/'fixture.bin').write_bytes(raw)
    row = SimpleNamespace(id='one', name='window.log', storage_key='fixture.bin', size=len(raw),
                          sha256=hashlib.sha256(raw).hexdigest())
    class Query:
        def filter(self, **kwargs): return self
        def order_by(self, *args): return self
        def __getitem__(self, key): return [row]
    monkeypatch.setattr(diagnostic_materials, 'PackageFile', SimpleNamespace(objects=Query()))
    monkeypatch.setattr(diagnostic_materials, 'directory', lambda: tmp_path)
    job = SimpleNamespace(result={'input': {}}, project=None,
                          defect=SimpleNamespace(title='2026-11-19T12:44:14Z failure', description=''))
    materials = {}
    _, sources, _ = diagnostic_materials.inspect(job, materials)
    source = sources[0]
    assert source['selection_scope'] == 'event_plus_minus_5m'
    assert source['omitted_count'] == 2 and source['scan_incomplete'] is False
    assert source['scanned_bytes'] == len(raw) and source['integrity_scan_scope'] == 'full_sequential'
    assert source['model_selected_bytes'] < source['integrity_scanned_bytes']
    assert 'root' in materials['FILE-one']['content'] and 'older' not in materials['FILE-one']['content']
    row.sha256 = '0' * 64
    maps = {}
    _, invalid, _ = diagnostic_materials.inspect(job, maps)
    assert invalid[0]['scan_incomplete'] and not maps
