"""Real HTTP IAM -> latest bridge -> native project flow, using isolated accounts/data."""
import hashlib
import hmac
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
import zipfile
import requests

ROOT = Path(sys.argv[1])
ROOT.mkdir(parents=True, exist_ok=True)
AUTH = "http://127.0.0.1:16335"
PLATFORM = "http://127.0.0.1:18880"
SOURCE = "latest-native-verification"
PROJECT = 1401109
TASK = 140110901
ACTORS = {"Manager": "native140-manager", "TeamLeader": "native140-technician",
          "Annotator": "native140-tester", "Collector": "native140-collector"}
env = dict(row.split("=", 1) for row in json.loads(subprocess.check_output(
    ["docker", "inspect", "project-bridge-verification-20261109"]))[0]["Config"]["Env"])
location = json.loads((ROOT / "authority-location.json").read_text())
events = []


def password(name):
    return hmac.new(env["PLATFORM_BOOTSTRAP_TOKEN"].encode(), ("acceptance:" + name).encode(), hashlib.sha256).hexdigest()


def sql(query):
    command = ["docker", "exec", "-i", "account-interop-20261107-iam-db-1", "sh", "-c",
               'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot -N account_acceptance']
    result = subprocess.run(command, input=query, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("Isolated SQL fixture failed")
    return result.stdout.strip()


def login_authority(name, daq=False):
    response = requests.post(AUTH + ("/api/daq/auth/login" if daq else "/api/user/login"), json={"username": name, "password": password(name)}, timeout=20)
    data = response.json()
    if response.status_code != 200 or data.get("code") != 1:
        raise RuntimeError("Authority login failed for " + name)
    return data["data"]["accessToken"]


admin_token = login_authority("interop-admin")
ids = {}
for role, name in ACTORS.items():
    exists = sql(f"SELECT id FROM users WHERE username='{name}';")
    if not exists:
        response = requests.post(AUTH + "/api/user/create", headers={"Authorization": "Bearer " + admin_token}, json={
            "username": name, "email": name + "@example.invalid", "password": password(name), "role": role, "status": "Active",
        }, timeout=20)
        assert response.status_code == 200 and response.json().get("code") == 1, "Cannot create isolated actor"
    ids[role] = int(sql(f"SELECT id FROM users WHERE username='{name}';"))
sql(f"INSERT IGNORE INTO projects(id,name,description,status,start_date,end_date,created_by) VALUES({PROJECT},'最新三端隔离联调','本机模拟，不含现场数据','InProgress',CURDATE(),DATE_ADD(CURDATE(),INTERVAL 1 MONTH),1);")
for uid in ids.values():
    sql(f"INSERT IGNORE INTO project_users(project_id,user_id,role,created_by) VALUES({PROJECT},{uid},'Member',1);")
sql(f"INSERT IGNORE INTO tasks(id,project_id,name,status,created_at,updated_at) VALUES({TASK},{PROJECT},'本机故障回归采集','InProgress',NOW(),NOW());")
state_path = ROOT / "flow-state.json"
state = json.loads(state_path.read_text()) if state_path.exists() else {"session": str(uuid4()), "package": "branch140-" + uuid4().hex}
sql(f"INSERT IGNORE INTO data_packages(id,task_id,user_id,name,source_session_id,status,recorded_at,uploaded_at,created_at,updated_at) VALUES('{state['package']}',{TASK},{ids['Collector']},'本机连接故障包','{state['session']}','PendingAnnotation',NOW(),NOW(),NOW(),NOW());")

config = {"kind": "data_platform", "base_url": "http://" + location["plane_ip"] + ":6324",
          "allowed_hosts": [location["plane_ip"]], "allow_http_local": True, "login_enabled": True,
          "login_auto_provision": True, "timezone": "Asia/Shanghai", "service_token": env["ISSUE_PERMISSIONS_SERVICE_TOKEN"],
          "bridge_key_id": env["ISSUE_BRIDGE_KEY_ID"], "bridge_secret": env["ISSUE_BRIDGE_HMAC_SECRET"],
          "bridge_audience": env["ISSUE_BRIDGE_AUDIENCE"],
          "login_role_map": {"Manager": "PROJECT_MANAGER", "TeamLeader": "TECHNICIAN", "Annotator": "REGRESSION_TESTER", "Collector": "REPORTER"}}
setup = '''import os,json,sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE","plane.settings.production")
import django;django.setup()
from plane.db.models import Workspace,Project,ProjectMember,Issue,State
from plane.license.models import InstanceAdmin,InstanceConfiguration
from plane.license.utils.encryption import encrypt_data
from plane.quality.models import PlatformProject,ProjectRolePolicy,DaqBinding,BusinessRole
data=json.load(sys.stdin); config=data["config"]
owner=InstanceAdmin.objects.filter(role=20,user__is_active=True).first().user
config["configured_by"]=str(owner.id)
InstanceConfiguration.objects.update_or_create(key="QUALITY_SOURCE:"+data["source"],defaults={"value":encrypt_data(json.dumps(config)),"is_encrypted":True})
ws=Workspace.objects.get(slug="chinese-demo")
p,created=Project.objects.get_or_create(workspace=ws,identifier="BRIDGE140",defaults={"name":"最新三端隔离联调","created_by":owner})
if created:
 from plane.db.models.state import DEFAULT_STATES
 State.objects.bulk_create([State(project=p,workspace=ws,**s) for s in DEFAULT_STATES])
ProjectMember.objects.get_or_create(project=p,member=owner,defaults={"workspace":ws,"role":20,"created_by":owner})
PlatformProject.objects.update_or_create(project=p,source_instance=data["source"],defaults={"external_project_id":data["external"],"active":True,"created_by":owner})
ProjectRolePolicy.objects.update_or_create(project=p,defaults={"enabled":True})
BusinessRole.objects.get_or_create(project=p,user=owner,defaults={"role":"PLATFORM_ADMIN","additional_roles":["PROJECT_MANAGER"],"created_by":owner})
issue=Issue.objects.filter(project=p,name="原采集任务关联").first() or Issue.objects.create(project=p,workspace=ws,name="原采集任务关联",created_by=owner)
DaqBinding.objects.get_or_create(project=p,source_instance=data["source"],platform_task_id=data["task"],source_record_id=data["session"],defaults={"issue":issue,"package_id":data["package"],"created_by":owner})
print(json.dumps({"project_id":str(p.id),"workspace":ws.slug,"identifier":p.identifier}))
'''
result = subprocess.run(["docker", "exec", "-i", "-w", "/code", "plane-local-20261106-api-1", "python", "-c", setup],
                        input=json.dumps({"config": config, "source": SOURCE, "external": PROJECT, "task": TASK, **state}),
                        capture_output=True, text=True)
if result.returncode:
    raise RuntimeError("Native isolated setup failed")
state.update(json.loads(result.stdout.strip().splitlines()[-1]))
state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
base = f"/api/workspaces/{state['workspace']}/projects/{state['project_id']}/quality/"
clients, tokens, native_ids = {}, {}, {}


def call(role, method, path, body=None, expected=200):
    response = clients[role].request(method, PLATFORM + path, json=body, timeout=30)
    events.append({"actor": role, "method": method, "path": path, "status": response.status_code, "expected": expected})
    assert response.status_code == expected, (role, method, path, response.status_code, str(response.json())[:350])
    return response.json()


for role, name in ACTORS.items():
    session = requests.Session()
    csrf = session.get(PLATFORM + "/auth/get-csrf-token/", timeout=15).json()["csrf_token"]
    session.headers.update({"X-CSRFToken": csrf, "Origin": PLATFORM, "Referer": PLATFORM + "/"})
    clients[role] = session
    call(role, "POST", "/api/quality-auth/data-login/", {"source_instance": SOURCE, "username": name, "password": password(name)})
    session.headers["X-CSRFToken"] = session.cookies.get("csrftoken") or csrf
    context = call(role, "GET", base + "context/")
    native_ids[role] = context["user_id"]

# DAQ-specific credentials leave ordinary platform sessions intact.
for role, name in ACTORS.items():
    tokens[role] = login_authority(name, daq=True)


def bridge(method, path, body=None, expected=200, files=None, role="Collector", key=None):
    headers = {"Authorization": "Bearer " + tokens[role]}
    if key:
        headers["Idempotency-Key"] = key
    response = requests.request(method, AUTH + "/issue-api" + path, json=body if files is None else None,
                                files=files, headers=headers, timeout=30)
    events.append({"actor": "bridge-" + role, "method": method, "path": path, "status": response.status_code, "expected": expected})
    assert response.status_code in (expected if isinstance(expected, list) else [expected]), ("bridge", method, path, response.status_code, str(response.json())[:350])
    return response.json()


bridge("GET", "/api/quality-auth/daq-project/?platform_project_id=" + str(PROJECT))
key = state.setdefault("request_key", str(uuid4()))
state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
payload = {"sourceRecordId": state["session"], "platformTaskId": TASK, "category": "Other",
           "title": "最新三端全流程：本机连接故障", "description": "仅本机隔离模拟，日志记录连接失败，供多角色修复回归验证。"}
receipt = bridge("POST", base + "daq/reports/", payload, expected=201 if not state.get("defect_id") else 200, key=key)
state.update(defect_id=receipt["issueId"], code=receipt["issueCode"])
state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
retry = bridge("POST", base + "daq/reports/", payload, key=key)
assert receipt["issueId"] == retry["issueId"] and receipt["issueCode"] == retry["issueCode"]
bridge("POST", base + "daq/reports/", payload, expected=403, key=str(uuid4()), role="Annotator")
archive_path = ROOT / "diagnostic.zip"
if not archive_path.exists():
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("recording.log", "ERROR ConnectionRefusedError: connection refused\n")
        archive.writestr("environment_summary.json", json.dumps({"scope": "local_simulation", "robot_connected": False, "ros_mode": "isolated"}))
    archive_path.write_bytes(raw.getvalue())
content = archive_path.read_bytes()
package = bridge("POST", base + "packages/", {"name": "三端联调诊断材料", "defect_id": state["defect_id"],
    "source_system": "ENGRAM_DAQ", "external_id": "native140-" + key,
    "files": [{"path": "diagnostic.zip", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}]}, expected=[200, 201])
bridge("POST", base + f"packages/{package['id']}/files/", files={"file": ("diagnostic.zip", content, "application/zip")}, expected=[200, 201])
deadline = time.monotonic() + 200
detail = None
while time.monotonic() < deadline:
    detail = bridge("GET", base + f"daq/issues/{state['defect_id']}/")
    jobs = detail["diagnostics"]
    if jobs and jobs[0]["status"] not in {"queued", "running"}:
        break
    time.sleep(2)
assert detail["diagnostics"][0]["status"] == "completed", "Background diagnostics did not finish"
state.update({"diagnostic": {k: detail["diagnostics"][0]["result"].get(k) for k in ["method", "model_status", "duration_ms", "engine"]},
              "native_ids": native_ids, "upstream_ids": ids})
(ROOT / "flow-evidence.json").write_text(json.dumps({"state": state, "events": events, "scope": "real HTTP, isolated data, no physical robot"}, ensure_ascii=False, indent=2))
print(json.dumps({"phase": "reported_with_attachments_and_diagnostic", "code": state["code"], "diagnostic": state["diagnostic"], "checks": len(events)}, ensure_ascii=False))
