"""HTTP guard contracts. Numerical semantics are checked separately against real ONNX weights."""
import importlib.util
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
spec = importlib.util.spec_from_file_location("embedding_service", Path(__file__).with_name("app.py"))
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)

class Encoder:
    model = "bge-small-zh-v1.5"
    def encode(self, texts):
        if any(len(text) > 510 for text in texts):
            raise service.InputLimitError("input exceeds 512 tokens")
        return [[1.0] + [0.0] * 511 for _ in texts], [len(t) + 2 for t in texts]

@pytest.fixture
def client():
    return TestClient(service.create_app(Encoder(), "test-only-key"))

def test_embeddings_return_openai_float_shape_with_usage_and_no_echo(client):
    r = client.post('/v1/embeddings',headers={'Authorization':'Bearer test-only-key'},json={'model':'bge-small-zh-v1.5','input':['启动网络失败','机器人连接中断'],'encoding_format':'float'})
    assert r.status_code == 200
    assert r.json()['object']=='list' and len(r.json()['data'])==2
    assert len(r.json()['data'][0]['embedding'])==512
    assert r.json()['usage']['prompt_tokens']>0
    assert '启动网络失败' not in r.text

def test_health_has_no_key_and_model_routes_require_bearer(client):
    assert client.get('/health').status_code==200
    assert 'test-only-key' not in client.get('/health').text
    assert client.get('/v1/models').status_code==401
    assert client.get('/v1/models',headers={'Authorization':'Bearer bad'}).status_code==401
    assert client.get('/v1/models',headers={'Authorization':'Bearer test-only-key'}).json()['data'][0]['id']=='bge-small-zh-v1.5'

@pytest.mark.parametrize('patch',[{'input':[]},{'input':['']},{'input':['a']*17},{'input':'a'*1025},{'input':[123]},{'model':'other'},{'dimensions':768},{'encoding_format':'base64'}])
def test_invalid_inputs_reject_without_silent_truncation(client,patch):
    r=client.post('/v1/embeddings',headers={'Authorization':'Bearer test-only-key'},json={'model':'bge-small-zh-v1.5','input':'正常文本',**patch})
    assert r.status_code==400

def test_token_overflow_is_explicit_and_body_is_bounded(client):
    r=client.post('/v1/embeddings',headers={'Authorization':'Bearer test-only-key'},json={'model':'bge-small-zh-v1.5','input':'字'*511})
    assert r.status_code==400 and r.json()['error']['code']=='input_too_long'
    r=client.post('/v1/embeddings',headers={'Authorization':'Bearer test-only-key'},content=b' '*70000)
    assert r.status_code==413


def test_non_ascii_bearer_is_rejected_without_authentication_exception(client):
    r = client.get('/v1/models', headers={b'Authorization': b'Bearer \xff'})
    assert r.status_code == 401


def test_operational_request_logs_keep_status_without_material_or_credentials(client,capsys):
    secret='test-only-key'
    response=client.post('/v1/embeddings',headers={'Authorization':'Bearer '+secret},json={'model':service.MODEL,'input':'private-material-marker'})
    assert response.status_code==200
    events=[__import__('json').loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events and events[-1]['component']=='embedding' and events[-1]['status']==200
    assert secret not in str(events) and 'private-material-marker' not in str(events)
