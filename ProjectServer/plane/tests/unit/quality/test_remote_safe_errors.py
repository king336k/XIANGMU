"""Missing credential files are operational errors, never credential contents."""
from plane.quality.remote_event_display import safe_output


def test_missing_local_api_credential_has_a_safe_actionable_explanation():
    value = safe_output("[Errno 2] No such file or directory: '/home/operator/OTA/old/out/runtime/teleop/remote-diagnostics/local-api-token'")
    assert '本机诊断接口未就绪' in value
    assert '重新启动 DAQ' in value
    assert '/home/operator' not in value


def test_real_credentials_and_other_errors_remain_redacted_or_readable():
    assert 'sensitive-value' not in safe_output('sshpass -p sensitive-value ssh robot')
    assert 'sensitive-value' not in safe_output('token=sensitive-value')
    assert 'Connection refused' in safe_output('Connection refused')
    assert '本机诊断接口未就绪' not in safe_output("token='No such file or directory local-api-token' sensitive-value")
