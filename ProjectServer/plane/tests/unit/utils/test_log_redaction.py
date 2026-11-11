"""Bounded diagnostic context must survive without credential values."""
import logging
import pytest
from plane.utils.logging import safe_log_value, safe_query, SafeLogFilter


def test_recursive_and_text_credentials_are_redacted_but_context_remains():
 value={'page':2,'nested':[{'api_key':'raw-secret-one','Password':'raw-secret-two','note':'Bearer raw-secret-three'}],'url':'https://example.invalid/a?token=raw-secret-four&mode=read'}
 actual=str(safe_log_value(value));assert all(s not in actual for s in ['raw-secret-one','raw-secret-two','raw-secret-three','raw-secret-four']);assert 'page' in actual and 'read' in actual

def test_query_hides_repeated_and_encoded_keys_preserves_filters():
 actual=safe_query('page=2&access_token=hide1&access_token=hide2&%70assword=hide3&filter=open')
 assert 'hide' not in actual and 'page=2' in actual and 'filter=open' in actual

def test_filter_redacts_message_extra_and_formatted_exception_trace():
 try:raise ValueError('client_secret=hide-exception')
 except ValueError:
  record=logging.LogRecord('plane.exception',logging.ERROR,__file__,10,'failed url=%s',('http://internal/a?token=hide-msg',),__import__('sys').exc_info())
 record.payload={'authorization':'hide-extra','status':'failed'};SafeLogFilter().filter(record);text=logging.Formatter('%(message)s %(payload)s').format(record)
 assert 'hide-' not in text and 'ValueError' in text and 'test_filter_redacts' in text and 'failed' in text


def test_multibyte_utf8_rotation_and_process_filename(tmp_path,monkeypatch):
 from plane.utils.logging import ProcessRotatingFileHandler
 handler=ProcessRotatingFileHandler(str(tmp_path/'error.log'),maxBytes=10,backupCount=3)
 record=logging.LogRecord('plane.exception',logging.ERROR,__file__,1,'中文中文',(),None)
 assert handler.shouldRollover(record)
 first=handler.baseFilename;original=__import__('os').getpid();monkeypatch.setattr('os.getpid',lambda:original+1);handler.emit(record);assert handler.baseFilename!=first and str(original+1) in handler.baseFilename;handler.close()

def test_production_console_safe_filter_and_daily_file_retention():
 import ast
 from pathlib import Path
 tree=ast.parse((Path(__file__).resolve().parents[3]/'settings/production.py').read_text())
 assignment=next(x for x in tree.body if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='LOGGING' for t in x.targets))
 # Evaluate only the logging dictionary with known local values, never import runtime production settings.
 config=eval(compile(ast.Expression(assignment.value),'<logging-config>','eval'),{'DEBUG':False,'BASE_DIR':'/fixture','os':__import__('os')})
 assert config['handlers']['console']['filters']==['safe'] and config['handlers']['file']['filters']==['safe']
 assert config['handlers']['file']['class'].endswith('ProcessRotatingFileHandler') and config['handlers']['file']['backupCount']>=5
 assert all('console' in config['loggers'][name]['handlers'] for name in ['plane.api.request','plane.worker','plane.api'])


def test_encoded_url_query_and_connection_userinfo_are_redacted():
    from plane.utils.logging import safe_log_text
    text=safe_log_text('failed https://host/path?%70assword=url-private&page=2 amqp://user:broker-private@broker:5672//')
    assert 'url-private' not in text and 'broker-private' not in text and 'page=2' in text and 'broker:5672' in text


def test_same_day_multiple_size_rotations_preserve_distinct_backups(tmp_path):
    from plane.utils.logging import ProcessRotatingFileHandler
    handler=ProcessRotatingFileHandler(str(tmp_path/'error.log'),maxBytes=30,backupCount=5,encoding='utf-8')
    for index in range(5):
        handler.emit(logging.LogRecord('plane.exception',logging.ERROR,__file__,1,'event-%d-'+'x'*15,(index,),None))
    handler.close()
    content=''.join(x.read_text() for x in tmp_path.iterdir())
    assert all('event-'+str(i) in content for i in range(5))


def test_free_text_cookie_chain_and_private_key_block_are_hidden():
    from plane.utils.logging import safe_log_text
    text=safe_log_text('HTTP 403\nCookie: session=first-private; other=second-private\nTrace: function42\n-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----')
    assert all(x not in text for x in ['first-private','second-private','private-material'])
    assert 'HTTP 403' in text and 'function42' in text


def test_json_string_inside_message_is_scrubbed_recursively():
    import json
    from plane.utils.logging import safe_log_text
    raw=json.dumps({'message':json.dumps({'password':'nested-private','status':'failed'})})
    text=safe_log_text(raw)
    assert 'nested-private' not in text and 'failed' in text


def test_oversized_context_cannot_leak_across_json_or_url_boundary():
    import json
    from plane.utils.logging import safe_log_text
    secret = 'oversized-test-canary'
    cases = [
        json.dumps({'message': json.dumps({'password': secret, 'context': 'x' * 9000})}),
        json.dumps({'password': secret, 'context': 'x' * 9000}).replace('"', '\\"'),
        'amqp://user:' + secret + 'x' * 9000 + '@broker:5672//',
        'password=' + secret + 'x' * 9000,
    ]
    for raw in cases:
        actual = safe_log_text(raw)
        assert secret not in actual
        assert len(actual) <= 8192


def test_escaped_assignments_and_unicode_keys_in_prefixed_context_are_safe():
    import json
    from plane.utils.logging import safe_log_text
    secret = 'escaped-test-canary'
    cases = [
        r'provider returned \"password\": \"' + secret + r'\"',
        'provider returned ' + json.dumps({'password': secret}).replace('password', r'\u0070assword'),
    ]
    for raw in cases:
        assert secret not in safe_log_text(raw)


def test_json_formatter_never_receives_unprocessed_extras_after_budget():
    from pythonjsonlogger.json import JsonFormatter
    record = logging.LogRecord('plane.api', logging.ERROR, __file__, 1, 'failed operation', (), None)
    for index in range(100):
        setattr(record, 'context_' + str(index), {'status': 'failed'})
    record.api_key = 'late-extra-test-canary'
    record.late_payload = {'password': 'late-nested-test-canary'}
    SafeLogFilter().filter(record)
    actual = JsonFormatter().format(record)
    assert 'late-extra-test-canary' not in actual
    assert 'late-nested-test-canary' not in actual
    assert 'failed operation' in actual


def test_oversized_exception_keeps_type_and_frame_without_secret_message():
    import sys
    try:
        raise ValueError('oversized-exception-test-canary' + 'x' * 20000)
    except ValueError:
        record = logging.LogRecord('plane.exception', logging.ERROR, __file__, 1, 'failed operation', (), sys.exc_info())
    SafeLogFilter().filter(record)
    actual = logging.Formatter('%(message)s').format(record)
    assert 'oversized-exception-test-canary' not in actual
    assert 'ValueError' in actual
    assert 'test_oversized_exception_keeps_type_and_frame_without_secret_message' in actual


def test_nested_json_encoding_depth_budget_never_returns_raw_secret():
    import json
    from plane.utils.logging import safe_log_text
    raw = json.dumps({'password': 'depth-budget-test-canary'})
    for _ in range(9):
        raw = json.dumps({'message': raw})
        assert 'depth-budget-test-canary' not in safe_log_text(raw)


def test_sensitive_extra_keys_are_hidden_for_every_value_type():
    from pythonjsonlogger.json import JsonFormatter
    for raw in [987654321, True, None, b'numeric-extra-test-canary']:
        record = logging.LogRecord('plane.api', logging.ERROR, __file__, 1, 'failed operation', (), None)
        record.password = raw
        SafeLogFilter().filter(record)
        assert __import__('json').loads(JsonFormatter().format(record))['password'] == '[REDACTED]'


@pytest.mark.parametrize('signal_setup', ['setup_loggers', 'setup_task_loggers'])
@pytest.mark.parametrize('existing_handler', [False, True])
def test_celery_signal_filters_both_new_and_existing_handlers(signal_setup, existing_handler):
    import io
    from plane import celery as celery_module
    logger = logging.Logger('celery-logging-fixture')
    if existing_handler:
        logger.addHandler(logging.StreamHandler(io.StringIO()))
    getattr(celery_module, signal_setup)(logger)
    streams = []
    for handler in logger.handlers:
        stream = io.StringIO()
        handler.setStream(stream)
        streams.append(stream)
    logger.error('password=celery-signal-test-canary failed operation')
    for stream in streams:
        actual = stream.getvalue()
        assert 'celery-signal-test-canary' not in actual
        assert 'failed operation' in actual
    assert all(any(isinstance(item, SafeLogFilter) for item in handler.filters) for handler in logger.handlers)


def test_non_sensitive_extra_key_with_bytes_cannot_bypass_redaction():
    record = logging.LogRecord('plane.api', logging.ERROR, __file__, 1, 'failed operation', (), None)
    record.payload = b'password=bytes-extra-test-canary status=failed'
    SafeLogFilter().filter(record)
    actual = logging.Formatter('%(message)s %(payload)s').format(record)
    assert 'bytes-extra-test-canary' not in actual
    assert 'failed operation' in actual and 'status=failed' in actual


def test_non_sensitive_extra_key_with_custom_object_cannot_bypass_redaction():
    class ProviderContext:
        def __str__(self):
            return 'password=object-extra-test-canary status=failed'
    record = logging.LogRecord('plane.api', logging.ERROR, __file__, 1, 'failed operation', (), None)
    record.payload = ProviderContext()
    SafeLogFilter().filter(record)
    actual = logging.Formatter('%(message)s %(payload)s').format(record)
    assert 'object-extra-test-canary' not in actual
    assert 'failed operation' in actual and 'status=failed' in actual
