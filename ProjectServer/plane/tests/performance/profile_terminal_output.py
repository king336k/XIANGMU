"""Explicit paired profile, not collected by the ordinary test_*.py suite.

Set TERMINAL_BATCH_BASELINE to terminal_stream.py extracted from the base commit
and TERMINAL_BATCH_REPORT to an artifact path; run this file explicitly in pytest.
The input, storage, permissions, resource budget and alternating order are shared.
"""

import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import statistics
import time

import pytest
from asgiref.sync import sync_to_async
from django_redis import get_redis_connection

from plane.quality.terminal_stream import fast_output, publish_fast_output

pytest_plugins = ['plane.tests.contract.app.test_terminal_stream']
pytestmark = [pytest.mark.contract, pytest.mark.slow, pytest.mark.django_db(transaction=True)]


def test_paired_terminal_batch_path(terminal):
    row, _ = terminal
    spec = importlib.util.spec_from_file_location(
        'plane.quality.stream_baseline', os.environ['TERMINAL_BATCH_BASELINE']
    )
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    client = get_redis_connection('default')
    key = 'remote:terminal-output:' + str(row.id)

    async def paired(count):
        payload = [{'session_id': str(row.id), 'kind': 'data', 'id': 'benchmark-' + str(index),
                    'data': base64.b64encode((str(index) + ': verified terminal bytes\r\n').encode()).decode()}
                   for index in range(count)]
        times = {'before': [], 'after': []}
        for index in range(70):
            order = [('before', baseline.publish_fast_output), ('after', publish_fast_output)]
            if index % 2:
                order.reverse()
            for label, publish in order:
                start = time.perf_counter_ns()
                await publish(row.workstation_id, payload)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                if index >= 10:
                    times[label].append(elapsed)
                values = await fast_output(row.id)
                assert len(values) == min(8, count)
                assert [value['source_id'] for value in values] == [value['id'] for value in payload[-8:]]
                assert all(right['fast_seq'] == left['fast_seq'] + 1 for left, right in zip(values, values[1:]))
                await sync_to_async(client.delete)(key, key + ':seq')
        return {name: {'n': len(samples), 'median_ms': statistics.median(samples),
                       'p95_ms': sorted(samples)[int(len(samples) * .95) - 1],
                       'samples_ms': samples} for name, samples in times.items()}

    result = {str(count): asyncio.run(paired(count)) for count in [1, 8, 100]}
    output = Path(os.environ['TERMINAL_BATCH_REPORT'])
    output.write_text(json.dumps({'same_postgres_redis': True, 'alternating_order': True,
                                 'batch_publish_path_only': True, 'batches': result}, indent=2))
