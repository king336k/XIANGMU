"""Bounded, independent DAQ reports through real authority login and HTTP bridge.

Only the dedicated local acceptance databases and LOAD149 project are seeded.
Credentials are derived in memory and never included in evidence or exceptions.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import hmac
import io
import json
import re
from pathlib import Path
import subprocess
import threading
import time
from uuid import uuid4
import zipfile

import bcrypt
import requests

AUTH = "http://127.0.0.1:16335"
PLATFORM = "http://127.0.0.1:18880"
SOURCE = "latest-native-verification"
EXTERNAL = 1491109
CONTAINERS = ["plane-local-20261106-diagnostic-worker-1", "plane-local-20261106-worker-1", "plane-local-20261106-api-1"]


def command(args, body=None):
    result = subprocess.run(args, input=body, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("Acceptance command failed (details suppressed)")
    return result.stdout.strip()


def sql(query):
    return command(["docker", "exec", "-i", "account-interop-20261107-iam-db-1", "sh", "-c",
                    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot -N account_acceptance'], query)


def checked(response, expected):
    if response.status_code not in expected:
        # Do not propagate requests' headers or upstream response bodies.
        raise RuntimeError(f"HTTP status {response.status_code}, expected {expected}")
    return response.json()


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * p
    lower = int(position)
    return round(values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower), 3)


def seconds(later, earlier):
    return round((datetime.fromisoformat(later.replace("Z", "+00:00")) -
                  datetime.fromisoformat(earlier.replace("Z", "+00:00"))).total_seconds(), 3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, choices=[2, 4, 10], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline", type=int, default=900)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run = uuid4().hex[:8]
    env = dict(row.split("=", 1) for row in json.loads(command(
        ["docker", "inspect", "project-bridge-verification-20261109"]))[0]["Config"]["Env"])

    def password(name):
        return hmac.new(env["PLATFORM_BOOTSTRAP_TOKEN"].encode(), ("acceptance:" + name).encode(), hashlib.sha256).hexdigest()

    actors = []
    sql(f"INSERT IGNORE INTO projects(id,name,description,status,start_date,end_date,created_by) VALUES({EXTERNAL},'独立诊断排队压力验收','本机隔离模拟，不含现场数据','InProgress',CURDATE(),DATE_ADD(CURDATE(),INTERVAL 1 MONTH),1);")
    for index in range(args.count):
        name = f"load149-{run}-{index:02d}"
        digest = bcrypt.hashpw(password(name).encode(), bcrypt.gensalt()).decode()
        sql(f"INSERT INTO users(username,email,password,role,status) VALUES('{name}','{name}@example.invalid','{digest}','Collector','Active');")
        uid = int(sql(f"SELECT id FROM users WHERE username='{name}';"))
        task = 149000000 + uid
        session, package = str(uuid4()), "load149-" + uuid4().hex
        sql(f"INSERT INTO project_users(project_id,user_id,role,created_by) VALUES({EXTERNAL},{uid},'Member',1);")
        sql(f"INSERT INTO tasks(id,project_id,name,status,created_at,updated_at) VALUES({task},{EXTERNAL},'独立诊断{index}','InProgress',NOW(),NOW());")
        sql(f"INSERT INTO data_packages(id,task_id,user_id,name,source_session_id,status,recorded_at,uploaded_at,created_at,updated_at) VALUES('{package}',{task},{uid},'隔离压力材料','{session}','PendingAnnotation',NOW(),NOW(),NOW(),NOW());")
        actors.append(dict(username=name, upstream_user_id=uid, task=task, session=session, package=package))
    setup = '''import os,json,sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE","plane.settings.production")
import django;django.setup()
from plane.db.models import Workspace,Project,ProjectMember,Issue,State
from plane.license.models import InstanceAdmin
from plane.quality.models import PlatformProject,ProjectRolePolicy,DaqBinding,BusinessRole
data=json.load(sys.stdin)
owner=InstanceAdmin.objects.filter(role=20,user__is_active=True).first().user
ws=Workspace.objects.get(slug="chinese-demo")
p,created=Project.objects.get_or_create(workspace=ws,identifier="LOAD149",defaults={"name":"独立诊断排队压力验收","created_by":owner})
if created:
 from plane.db.models.state import DEFAULT_STATES
 State.objects.bulk_create([State(project=p,workspace=ws,**s) for s in DEFAULT_STATES])
ProjectMember.objects.get_or_create(project=p,member=owner,defaults={"workspace":ws,"role":20,"created_by":owner})
PlatformProject.objects.get_or_create(project=p,source_instance=data["source"],external_project_id=data["external"],defaults={"active":True,"created_by":owner})
ProjectRolePolicy.objects.get_or_create(project=p,defaults={"enabled":True})
BusinessRole.objects.get_or_create(project=p,user=owner,defaults={"role":"PLATFORM_ADMIN","additional_roles":["PROJECT_MANAGER"],"created_by":owner})
for actor in data["actors"]:
 issue=Issue.objects.create(project=p,workspace=ws,name="独立采集任务 "+str(actor["task"]),created_by=owner)
 DaqBinding.objects.create(project=p,source_instance=data["source"],external_project_id=data["external"],platform_task_id=actor["task"],source_record_id=actor["session"],issue=issue,package_id=actor["package"],created_by=owner)
print(json.dumps({"project_id":str(p.id),"workspace":ws.slug,"identifier":p.identifier}))
'''
    native = json.loads(command(["docker", "exec", "-i", "-w", "/code", "plane-local-20261106-api-1", "python", "-c", setup],
                                json.dumps(dict(source=SOURCE, external=EXTERNAL, actors=actors))).splitlines()[-1])
    base = f"/api/workspaces/{native['workspace']}/projects/{native['project_id']}/quality/"
    for actor in actors:
        client = requests.Session()
        csrf = checked(client.get(PLATFORM + "/auth/get-csrf-token/", timeout=20), [200])["csrf_token"]
        client.headers.update({"X-CSRFToken": csrf, "Origin": PLATFORM, "Referer": PLATFORM + "/"})
        checked(client.post(PLATFORM + "/api/quality-auth/data-login/", json={"source_instance": SOURCE,
            "username": actor["username"], "password": password(actor["username"])}, timeout=30), [200])
        data = checked(requests.post(AUTH + "/api/daq/auth/login", json={"username": actor["username"],
            "password": password(actor["username"])}, timeout=20), [200])
        if data.get("code") != 1:
            raise RuntimeError("Dedicated DAQ login failed")
        actor["token"] = data["data"]["accessToken"]
    barrier = threading.Barrier(args.count)
    stopped = threading.Event()
    samples = []

    def sample():
        while not stopped.is_set():
            try:
                raw = command(["docker", "stats", "--no-stream", "--format", "{{json .}}", *CONTAINERS])
                samples.append({"at": time.time(), "containers": [json.loads(line) for line in raw.splitlines()]})
            except RuntimeError:
                samples.append({"at": time.time(), "error": "RESOURCE_SAMPLE_FAILED"})
            stopped.wait(2)

    def execute(actor):
        client = requests.Session()
        client.headers["Authorization"] = "Bearer " + actor["token"]
        events = []

        def bridge(method, path, body=None, files=None, key=None):
            start = time.monotonic()
            headers = {"Idempotency-Key": key} if key else None
            response = client.request(method, AUTH + "/issue-api" + path, headers=headers,
                json=body if files is None else None, files=files, timeout=30)
            events.append({"method": method, "path": path, "status": response.status_code,
                           "elapsed_s": round(time.monotonic() - start, 3)})
            return checked(response, [200, 201])

        start = time.monotonic()
        try:
            key = str(uuid4())
            receipt = bridge("POST", base + "daq/reports/", {"sourceRecordId": actor["session"],
                "platformTaskId": actor["task"], "category": "Other", "title": f"独立诊断压力 {run} {actor['task']}",
                "description": "受控本机模拟：日志连接被拒绝，根因需核对监听服务；并非现场机器人故障确认。"}, key=key)
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("recording.log", f"INFO collector={actor['username']} task={actor['task']}\nERROR ConnectionRefusedError target=127.0.0.1:65123 errno=111 connection refused\n")
                bundle.writestr("environment_summary.json", json.dumps({"scope": "controlled_local_simulation", "physical_robot": False,
                    "platform_task_id": actor["task"], "session": actor["session"]}))
            raw = archive.getvalue()
            package = bridge("POST", base + "packages/", {"name": "隔离压力材料", "defect_id": receipt["issueId"],
                "source_system": "ENGRAM_DAQ", "external_id": "load149-" + key,
                "files": [{"path": "diagnostics.zip", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}]})
            barrier.wait(timeout=60)
            uploaded = time.monotonic()
            bridge("POST", base + f"packages/{package['id']}/files/", files={"file": ("diagnostics.zip", raw, "application/zip")})
            deadline = time.monotonic() + args.deadline
            states = []
            job = None
            while time.monotonic() < deadline:
                detail = bridge("GET", base + f"daq/issues/{receipt['issueId']}/")
                jobs = [row for row in detail["diagnostics"] if row["result"].get("trigger") == "materials_verified"]
                if jobs:
                    job = jobs[0]
                    if not states or states[-1]["status"] != job["status"]:
                        states.append({"elapsed_s": round(time.monotonic() - uploaded, 3), "status": job["status"]})
                    if job["status"] not in {"queued", "running"}:
                        break
                time.sleep(2)
            evidence = {key: actor[key] for key in ["username", "upstream_user_id", "task", "session", "package"]}
            evidence.update(issue_id=receipt["issueId"], issue_code=receipt["issueCode"], states=states,
                full_elapsed_s=round(time.monotonic() - start, 3), upload_to_observed_terminal_s=round(time.monotonic() - uploaded, 3),
                diagnostic=job, http=events)
            if job:
                evidence["queue_wait_s"] = seconds(job["started_at"], job["created_at"]) if job.get("started_at") else None
                evidence["processing_s"] = seconds(job["completed_at"], job["started_at"]) if job.get("completed_at") and job.get("started_at") else None
                evidence["job_total_s"] = seconds(job["completed_at"], job["created_at"]) if job.get("completed_at") else None
            return evidence
        except Exception as error:
            barrier.abort()
            return {"username": actor["username"], "task": actor["task"], "error_class": type(error).__name__,
                    "error": str(error) if isinstance(error, RuntimeError) else "DETAILS_SUPPRESSED", "http": events}

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        with ThreadPoolExecutor(max_workers=args.count) as executor:
            results = list(executor.map(execute, actors))
    finally:
        stopped.set()
        sampler.join(timeout=10)
    successful = [row for row in results if row.get("diagnostic", {}).get("result", {}).get("model_status") == "completed"]
    summary = {"run": run, "requested_independent_reports": args.count, "distinct_users": len({row["username"] for row in results}),
        "distinct_tasks": len({row["task"] for row in results}), "distinct_defects": len({row.get("issue_id") for row in results if row.get("issue_id")}),
        "model_completed": len(successful), "model_statuses": {}, "latency_seconds": {},
        "external_cost": {"measured_amount": None, "reason": "Provider billing not exposed; token usage absent in baseline result",
            "maximum_logical_agent_requests": args.count * 6,
            "per_request_requested_max_output_tokens": 2500,
            "sdk_http_retries_included_in_this_bound": False},
        "scope": "Real local IAM login, dedicated accounts/tasks/Sessions, real bridge HTTP and configured external model; controlled connection evidence; no accuracy benchmark"}
    for row in results:
        status = row.get("diagnostic", {}).get("result", {}).get("model_status", row.get("error_class", "missing"))
        summary["model_statuses"][status] = summary["model_statuses"].get(status, 0) + 1
    usage = [row.get("diagnostic", {}).get("result", {}).get("model_usage") for row in results]
    if all(isinstance(row, dict) for row in usage):
        summary["external_cost"].update(
            measured_usage={key: sum(row.get(key, 0) for row in usage)
                            for key in ["requests", "input_tokens", "output_tokens"]},
            reason="Provider reported token usage; actual monetary billing/pricing unavailable",
        )
    memory = {}
    for sample_row in samples:
        for row in sample_row.get("containers", []):
            # Docker normally returns 400MiB without a separating space.
            match = re.fullmatch(r"([0-9.]+)([KMGT]?i?B)", row["MemUsage"].split(" / ")[0].replace(" ", ""))
            if match:
                factors = {"B": 1 / 1048576, "kB": 1 / 1024, "KB": 1 / 1024, "KiB": 1 / 1024,
                           "MB": 1, "MiB": 1, "GB": 1024, "GiB": 1024}
                mib = float(match[1]) * factors.get(match[2], 1)
                memory[row["Name"]] = max(memory.get(row["Name"], 0), round(mib, 2))
    summary["sampled_peak_memory_mib"] = memory
    for metric in ["queue_wait_s", "processing_s", "job_total_s", "upload_to_observed_terminal_s"]:
        values = [row[metric] for row in results if row.get(metric) is not None]
        summary["latency_seconds"][metric] = {"p50": percentile(values, .5), "p95": percentile(values, .95), "max": max(values) if values else None}
    (args.output / "evidence.json").write_text(json.dumps({"summary": summary, "project": native, "results": results, "resource_samples": samples}, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if len(successful) == args.count else 1


if __name__ == "__main__":
    raise SystemExit(main())
