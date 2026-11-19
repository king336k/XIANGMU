"""Select model evidence by candidate incident time; never imply a partial I/O scan."""
from datetime import datetime, timedelta
import json
import re

STAMP = re.compile(r'\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?')
CLOCK = re.compile(r'(?<!\d)(\d{2}:\d{2}:\d{2})(?!\d)')
FAULT = re.compile(r'error|exception|traceback|fatal|failed|refused|timed out|invalid|violation|aborted|异常|失败', re.I)


def _dates(text):
    values = []
    for match in STAMP.finditer(text):
        try:
            values.append(datetime.fromisoformat(match.group().replace(',', '.').replace('Z', '+00:00')))
        except ValueError:
            pass
    return values


def event_context(event_text='', material=''):
    """A capture time is only a proxy; clock-only reports require a dated log match."""
    event_text = event_text if isinstance(event_text, str) else ''
    material = material if isinstance(material, str) else ''
    try:
        document = json.loads(material)
    except (ValueError, TypeError):
        document = None
    log_text = material if document is None else ''
    if isinstance(document, dict) and document.get('sourceSystem') == 'ENGRAM_TELEOP_DAQ':
        observations = document.get('evidence', {})
        observations = observations.get('observations', {}) if isinstance(observations, dict) else {}
        records = []
        for observation in observations.values() if isinstance(observations, dict) else []:
            data = observation.get('data', {}) if isinstance(observation, dict) else {}
            nested = data.get('observations', {}) if isinstance(data, dict) else {}
            nodes = nested.get('nodes', {}) if isinstance(nested, dict) else {}
            data = nodes.get('data', {}) if isinstance(nodes, dict) else {}
            processes = data.get('processes', []) if isinstance(data, dict) else []
            for process in processes[:1000] if isinstance(processes, list) else []:
                lines = process.get('lines', []) if isinstance(process, dict) else []
                records.extend(line for line in lines if isinstance(line, str))
        log_text = '\n'.join(records)
    anchors = _dates(event_text)
    source = 'explicit_event_datetime' if anchors else None
    ambiguities, captures = [], []
    clock = CLOCK.search(event_text)
    if not anchors and clock:
        try:
            requested = datetime.strptime(clock.group(1), '%H:%M:%S').time()
        except ValueError:
            requested = None
        matches = {}
        for value in _dates(log_text) if requested is not None else []:
            # The title supplies no date or timezone. A nearby dated log gives
            # only a candidate day in that log's clock, including midnight.
            candidate = value.replace(hour=requested.hour, minute=requested.minute, second=requested.second, microsecond=0)
            candidate = min((candidate - timedelta(days=1), candidate, candidate + timedelta(days=1)),
                            key=lambda item: abs((item-value).total_seconds()))
            distance = abs((candidate-value).total_seconds())
            key = (candidate.date(), candidate.tzinfo)
            if distance <= 300 and (key not in matches or distance < matches[key][0]):
                matches[key] = (distance, value if distance < 1 else candidate)
        anchors = [item[1] for item in matches.values()]
        source = 'dated_log_matching_event_clock' if anchors else None
        if not anchors:
            ambiguities.append('event_date_unknown')
        elif len({value.date() for value in anchors}) > 1:
            ambiguities.append('multiple_event_dates')
    def capture(value, depth=0):
        if depth > 20:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'capturedAt' and isinstance(item, str):
                    captures.extend(value.isoformat() for value in _dates(item))
                elif key != 'reportedAt':
                    capture(item, depth + 1)
        elif isinstance(value, list):
            for item in value[:1000]: capture(item, depth + 1)
    if isinstance(document, dict) and document.get('sourceSystem') == 'ENGRAM_TELEOP_DAQ':
        capture(document.get('evidence', {}))
    captures = list(dict.fromkeys(captures))
    if not anchors and not clock and captures:
        anchors = _dates(captures[0])
        source = 'capture_time_proxy'
        ambiguities.append('capture_time_is_not_event_time')
    if any(value.tzinfo is None for value in anchors):
        ambiguities.append('event_timezone_unknown')
    return {'event_text': event_text, 'anchors': [value.isoformat() for value in anchors[:32]],
            'anchor_source': source, 'capture_times': captures[:32], 'ambiguities': ambiguities}


def merge_context(context, material):
    candidate = event_context(context.get('event_text', ''), material)
    if candidate['anchors'] and (not context.get('anchors') or context.get('anchor_source') == 'capture_time_proxy'):
        context.update(candidate)
    elif (candidate['anchor_source'] == context.get('anchor_source') == 'dated_log_matching_event_clock'
          and candidate['anchors']):
        context['anchors'] = list(dict.fromkeys([*context['anchors'], *candidate['anchors']]))[:32]
        if len({value.date() for item in context['anchors'] for value in _dates(item)}) > 1:
            context['ambiguities'] = list(dict.fromkeys([*context.get('ambiguities', []), 'multiple_event_dates']))
    context['capture_times'] = list(dict.fromkeys([*context.get('capture_times', []), *candidate['capture_times']]))[:32]
    return context


def select_line_indices(lines, context):
    context = context if isinstance(context, dict) else event_context()
    anchors = [value for item in context.get('anchors', []) for value in _dates(item)]
    ambiguities = list(context.get('ambiguities', []))
    dates = [next(iter(_dates(line)), None) for line in lines]
    faults = [index for index, line in enumerate(lines) if FAULT.search(line)]
    untimed = [index for index in faults if dates[index] is None]
    incomparable = set()
    def within(value, seconds=None):
        for anchor in anchors:
            if (value.tzinfo is None) != (anchor.tzinfo is None):
                incomparable.add('incomparable_log_clock')
                continue
            local = value.astimezone(anchor.tzinfo) if anchor.tzinfo else value
            if (local.date() == anchor.date() if seconds is None else abs((local - anchor).total_seconds()) <= seconds):
                return True
        return False
    selected, scope, radius = set(range(len(lines))), 'global_fallback', None
    if anchors:
        for name, seconds in [('event_plus_minus_5m', 300), ('event_plus_minus_30m', 1800), ('event_day', None)]:
            candidates = {index for index, value in enumerate(dates) if value is not None and within(value, seconds)}
            if any(index in candidates for index in faults):
                selected, scope, radius = candidates, name, seconds
                break
    boundaries = set(faults[:1] + faults[-1:]) - selected
    selected.update(untimed)
    # Clock uncertainty must never exclude an original root error.
    for index in faults:
        if dates[index] is not None and anchors and all((dates[index].tzinfo is None) != (anchor.tzinfo is None) for anchor in anchors):
            selected.add(index)
    selected.update(boundaries)
    # Keep stack traces and continuation records attached to selected timestamps.
    for index in sorted(selected):
        if dates[index] is None:
            continue
        following = index + 1
        while following < len(lines) and dates[following] is None:
            selected.add(following)
            following += 1
    if incomparable:
        ambiguities.extend(sorted(incomparable))
    window = {'anchors': context.get('anchors', []), 'anchor_source': context.get('anchor_source'),
              'ambiguities': list(dict.fromkeys(ambiguities)), 'radius_seconds': radius,
              'capture_times': context.get('capture_times', [])}
    if radius is not None:
        window['candidate_intervals'] = [{'start': (anchor - timedelta(seconds=radius)).isoformat(),
                                         'end': (anchor + timedelta(seconds=radius)).isoformat()} for anchor in anchors]
    meta = {'selection_scope': scope, 'window': window, 'omitted_count': len(lines) - len(selected),
            'selection_input_scope': 'bounded_scanned_sample', 'selection_record_count': len(selected),
            'untimed_fault_count': len(untimed), 'out_of_window_boundary_fault_count': len(boundaries)}
    return sorted(selected), meta


def select_sample(sample, context):
    text = sample.decode('utf-8', errors='replace')
    lines = text.splitlines(keepends=True)
    structured = []
    for line in lines:
        if '"selection_scope"' not in line or '"process"' not in line:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get('latest_lines'), list):
            structured.append(value)
    if structured:
        return sample, {'selection_scope': 'per_producer_time_windows',
            'window': {key: value for key, value in context.items() if key != 'event_text'},
            'omitted_count': sum(row.get('omitted_count', 0) for row in structured),
            'omitted_count_scope': 'retained_producer_rows',
            'selection_input_scope': 'uploaded_producer_log_lines'}
    merge_context(context, text)
    indices, meta = select_line_indices(lines, context)
    return ''.join(lines[index] for index in indices).encode(), meta
