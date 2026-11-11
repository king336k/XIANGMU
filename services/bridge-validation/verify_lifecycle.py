"""Continue isolated HTTP acceptance through repair, rejection, retest and knowledge invalidation."""
import runpy
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import sys
import time
import zipfile
import io

ctx = runpy.run_path(str(Path(__file__).with_name('verify_flow.py')))
globals().update({key: ctx[key] for key in ['ROOT', 'state', 'base', 'call', 'bridge', 'sql', 'events', 'native_ids', 'TASK', 'PROJECT', 'ids']})
report = ROOT / 'lifecycle-evidence.json'


def checkpoint(phase, **details):
    report.write_text(json.dumps({'phase': phase, 'state': state, 'events': events, **details,
        'scope': 'isolated HTTP accounts and simulated faults; no physical robot'}, ensure_ascii=False, indent=2))
    print(json.dumps({'phase': phase, 'checks': len(events)}, ensure_ascii=False), flush=True)


try:
    # Keep original failed/thin reports intact and append independently reproducible evidence.
    raw_path = ROOT / 'complete-diagnostic.zip'
    if not raw_path.exists():
        original = Path('/home/engram/Documents/tmp/artifacts/automatic-diagnostics-2026-11-09/real-daq/blind-run/real-daq-diagnostics.zip')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            with zipfile.ZipFile(original) as previous:
                for entry in previous.infolist():
                    if not entry.is_dir():
                        bundle.writestr(entry.filename, previous.read(entry))
            reproduction = json.loads((ROOT / 'connection-reproduction.json').read_text())
            bundle.writestr('connection-reproduction.json', json.dumps({**reproduction,
                'scope': 'local isolated reproduction', 'robot_connected': False,
                'target': '127.0.0.1', 'port': 65123, 'expected': 'service accepts TCP connection',
                'observed': 'ConnectionRefusedError', 'listener': 'none',
                'startup': 'target service intentionally not started',
                'network': 'loopback within isolated DAQ runtime, no robot network',
                'regression': 'start controlled listener, then repeat connection and inspect DAQ logs',
            }, ensure_ascii=False))
        raw_path.write_bytes(stream.getvalue())
    raw = raw_path.read_bytes()
    package = bridge('POST', base + 'packages/', {
        'name': 'DAQ完整异常栈与连接配置', 'defect_id': state['defect_id'], 'source_system': 'ENGRAM_DAQ',
        'external_id': 'complete-' + state['request_key'],
        'files': [{'path': 'complete-diagnostic.zip', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}],
    }, expected=[200, 201])
    uploaded = bridge('POST', base + f"packages/{package['id']}/files/", files={
        'file': ('complete-diagnostic.zip', raw, 'application/zip')}, expected=[200, 201])
    # Verify delivered bytes through the actual collector bridge.
    checkpoint('complete_materials_uploaded', zip_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    deadline = time.monotonic() + 210
    while time.monotonic() < deadline:
        detail = bridge('GET', base + f"daq/issues/{state['defect_id']}/")
        if detail['diagnostics'] and detail['diagnostics'][0]['status'] not in {'queued', 'running'}:
            break
        time.sleep(2)
    latest = detail['diagnostics'][0]
    assert latest['status'] == 'completed', latest['status']
    assert latest['result']['model_status'] == 'completed', latest['result'].get('model_error_code')
    state['diagnostic_material_report'] = {key: latest['result'].get(key) for key in ['model_status', 'engine', 'duration_ms', 'answer']}

    def defect(role='Manager'):
        return call(role, 'GET', base + f"defects/{state['defect_id']}/")

    def patch_defect(role, **values):
        row = defect(role)
        return call(role, 'PATCH', base + f"defects/{state['defect_id']}/", {'expected_version': row['edit_version'], **values})

    patch_defect('Manager', assignee_id=native_ids['TeamLeader'])
    patch_defect('TeamLeader', status='in_progress', resolution='核对隔离监听服务与DAQ连接配置')
    call('Collector', 'PATCH', base + f"defects/{state['defect_id']}/", {'status': 'closed'}, expected=403)
    solution = call('TeamLeader', 'POST', base + 'solutions/', {
        'defect_id': state['defect_id'], 'title': '恢复连接服务并核对配置',
        'root_cause': '隔离测试目标端口未监听；现有日志不支持认定机器人硬件故障。',
        'steps': '启动本机受控监听服务并核对DAQ目标地址与端口。',
        'verification': '使用新Session验证连接成功并由数据平台回读新包就绪状态。',
        'risk': '仅隔离模拟环境', 'rollback': '停止测试监听服务',
    }, expected=201)

    def submit_solution(row):
        return call('TeamLeader', 'POST', base + f"solutions/{row['id']}/submit/", {
            'expected_version': row['edit_version'], 'reviewer_ids': [native_ids['Manager']], 'required_count': 1})

    solution = submit_solution(solution)
    solution = call('Manager', 'POST', base + f"solutions/{solution['id']}/review/", {
        'revision_id': solution['revisions'][-1]['id'], 'decision': 'reject', 'comment': '补充启动命令与回归成功判据。'})
    assert solution['status'] == 'rejected'
    solution = call('TeamLeader', 'PATCH', base + f"solutions/{solution['id']}/", {
        'expected_version': solution['edit_version'], 'steps': '在隔离环境启动65123端口监听；核对目标、监听及连接日志；重新采集。'})
    solution = submit_solution(solution)
    revision = max(solution['revisions'], key=lambda row: row['version'])
    solution = call('Manager', 'POST', base + f"solutions/{solution['id']}/review/", {
        'revision_id': revision['id'], 'decision': 'approve', 'comment': '按冻结方案执行并保留失败回归证据。'})
    assert solution['status'] == 'approved'
    patch_defect('TeamLeader', status='resolved', fixed_build='isolated-fix-v1', resolution='第一轮修复后送测')
    checkpoint('repair_review_rejection_and_approval')

    def new_regression():
        row = call('TeamLeader', 'POST', base + f"defects/{state['defect_id']}/data-regressions/", {
            'solution_id': solution['id'], 'environment': '本机隔离验收'}, expected=201)
        plan = row['plan']
        plan = call('Manager', 'POST', base + f"plans/{plan['id']}/workflow/", {
            'action': 'assign', 'expected_version': plan['workflow_version'], 'assignee_id': native_ids['Annotator']})
        return call('Annotator', 'POST', base + f"plans/{plan['id']}/workflow/", {
            'action': 'claim', 'expected_version': plan['workflow_version']})

    first = new_regression()
    call('Annotator', 'POST', base + f"items/{first['items'][0]['id']}/executions/", {
        'request_id': str(uuid4()), 'result': 'failed', 'actual_result': '连接仍被拒绝', 'evidence': '第一轮日志错误仍在'}, expected=201)
    failed = call('Annotator', 'POST', base + f"plans/{first['id']}/workflow/", {
        'action': 'submit', 'expected_version': first['workflow_version']})
    assert failed['status'] == 'failed'
    assert defect()['status'] == 'open'
    patch_defect('TeamLeader', status='in_progress', resolution='第一轮失败后继续修复')
    patch_defect('TeamLeader', status='resolved', fixed_build='isolated-fix-v2', resolution='修正监听服务，第二轮送测')
    second = new_regression()
    call('Annotator', 'POST', base + f"items/{second['items'][0]['id']}/executions/", {
        'request_id': str(uuid4()), 'result': 'passed', 'actual_result': '尚未回读新Session'}, expected=400)
    session_id = str(uuid4())
    package_id = 'retest140-' + uuid4().hex
    # Source records use whole-second timestamps; create after the plan boundary.
    time.sleep(1.05)
    sql(f"SET time_zone='+08:00'; INSERT INTO data_packages(id,task_id,user_id,name,source_session_id,status,recorded_at,uploaded_at,created_at,updated_at) VALUES('{package_id}',{TASK},{ids['Collector']},'本轮隔离回归包','{session_id}','Transferring',NOW(),NOW(),NOW(),NOW());")
    evidence_url = base + f"plans/{second['id']}/data-evidence/"
    call('Annotator', 'POST', evidence_url, {'source_session_id': state['session']}, expected=400)
    call('Annotator', 'POST', evidence_url, {'source_session_id': session_id}, expected=400)
    sql(f"UPDATE data_packages SET status='PendingAnnotation' WHERE id='{package_id}';")
    linked = call('Annotator', 'POST', evidence_url, {'source_session_id': session_id}, expected=201)
    assert linked['package_id'] == package_id
    call('Annotator', 'POST', base + f"items/{second['items'][0]['id']}/executions/", {
        'request_id': str(uuid4()), 'result': 'passed', 'actual_result': '本轮新数据与连接检查通过',
        'evidence': '本机受控回归；权威数据平台回读Session、数据包和就绪状态'}, expected=201)
    second = call('Annotator', 'POST', base + f"plans/{second['id']}/workflow/", {
        'action': 'submit', 'expected_version': second['workflow_version']})
    call('Annotator', 'POST', base + f"plans/{second['id']}/workflow/", {
        'action': 'approve', 'expected_version': second['workflow_version']}, expected=403)
    # Revoking upstream readiness must invalidate even already attached evidence.
    sql(f"UPDATE data_packages SET status='ConvertFailed' WHERE id='{package_id}';")
    call('Manager', 'POST', base + f"plans/{second['id']}/workflow/", {
        'action': 'approve', 'expected_version': second['workflow_version']}, expected=400)
    sql(f"UPDATE data_packages SET status='PendingAnnotation' WHERE id='{package_id}';")
    accepted = call('Manager', 'POST', base + f"plans/{second['id']}/workflow/", {
        'action': 'approve', 'expected_version': second['workflow_version']})
    assert accepted['status'] == 'completed' and defect()['status'] == 'closed'
    state.update(failed_plan_id=first['id'], completed_plan_id=second['id'], regression_session=session_id, regression_package=package_id)
    checkpoint('failed_retest_repair_new_session_readback_and_close')
    knowledge = base.replace('/quality/', '/knowledge/')
    rows = call('Manager', 'GET', knowledge + 'articles/?status=draft')['results']
    article = next(row for row in rows if row.get('source_defect_id') == state['defect_id'])
    assert '根因' in article['content'] and '修复步骤' in article['content']
    workflow = knowledge + f"articles/{article['id']}/workflow/"
    scanned = call('Manager', 'POST', workflow, {'action': 'scan', 'expected_version': article['edit_version']})
    published = call('Manager', 'POST', workflow, {'action': 'publish', 'expected_version': scanned['edit_version']})
    assert published['status'] == 'published'
    patch_defect('Manager', status='open', resolution='联调验证来源重开后的知识失效')
    invalidated = call('Manager', 'GET', knowledge + f"articles/{article['id']}/")
    assert invalidated['status'] == 'offline' and invalidated['publication_active'] is False
    state['knowledge_id'] = article['id']
    checkpoint('closed_knowledge_publish_reopen_invalidated')
except Exception as error:
    checkpoint('failed', error_type=type(error).__name__, error=str(error)[:600])
    raise
