"""Real HTTP startup incident -> actual Session -> reviewed repair -> fresh-data closure."""
import json
from pathlib import Path
from uuid import uuid4
import hashlib
import time

# Reuse only the isolated IAM/project bootstrap and HTTP clients, not its report flow.
bootstrap = Path(__file__).with_name("verify_flow.py").read_text().split('bridge("GET", "/api/quality-auth/daq-project/?platform_project_id="')[0]
exec(compile(bootstrap, str(Path(__file__).with_name("verify_flow.py")), "exec"))
proof = ROOT / "incident-evidence.json"


def checkpoint(phase, **extra):
    proof.write_text(json.dumps({"phase": phase, "state": state, "events": events,
        "scope": "real HTTP and authoritative isolated data platform; simulated fault, no physical robot", **extra}, ensure_ascii=False, indent=2))
    print(json.dumps({"phase": phase, "checks": len(events)}, ensure_ascii=False), flush=True)


def current(role="Manager"):
    return call(role, "GET", base + f"defects/{state['incident_id']}/")


def patch_defect(role, **values):
    row = current(role)
    return call(role, "PATCH", base + f"defects/{row['id']}/", {"expected_version": row["edit_version"], **values})


def verify_database():
    code = """import os,json,sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE','plane.settings.production')
import django;django.setup()
from plane.quality.models import Defect,DaqReport,DaqBinding
value=json.load(sys.stdin);d=Defect.objects.get(pk=value['defect'])
print(json.dumps({'report_count':DaqReport.objects.filter(defect=d).count(),'baseline_binding_count':DaqBinding.objects.filter(source_record_id=value['baseline']).count()}))
"""
    response = subprocess.run(["docker", "exec", "-i", "-w", "/code", "plane-local-20261106-api-1", "python", "-c", code], input=json.dumps({"defect":state["incident_id"],"baseline":state["incident_baseline"]}), capture_output=True, text=True)
    assert response.returncode == 0, "Cannot verify isolated incident records"
    return json.loads(response.stdout.strip().splitlines()[-1])


if "--resume-knowledge" in sys.argv:
    previous = json.loads(proof.read_text())
    state.update(previous["state"])
    events[:] = previous["events"] + events
    assert current()["status"] == "closed" and verify_database()["report_count"] == 0
    knowledge = base.replace("/quality/", "/knowledge/")
    articles = call("Manager", "GET", knowledge + "articles/?status=draft")["results"]
    article = next(row for row in articles if row.get("source_defect_id") == state["incident_id"])
    assert "先启动65123监听服务" in article["content"] and article["status"] == "draft"
    state["incident_knowledge_id"] = article["id"]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    checkpoint("closed_from_fresh_ready_data_and_knowledge_draft", harness_correction="Expected the actual frozen repair steps, not a paraphrase substring")
    raise SystemExit(0)


try:
    context_path = base + "daq/incidents/?platformProjectId=" + str(PROJECT)
    assert bridge("GET", context_path)["can_report"] is True
    bridge("GET", context_path, role="Annotator", expected=403)
    bridge("GET", context_path + "&platformTaskId=999999999", expected=[401, 403])
    stamp = state.setdefault("incident_occurred_at", __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())
    event_id = state.setdefault("incident_event_id", str(uuid4()))
    state.setdefault("incident_baseline", str(uuid4()))
    state.setdefault("incident_baseline_package", "incident-baseline-" + uuid4().hex)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    payload = {"eventId":event_id,"kind":"startup_failure","occurredAt":stamp,"platformProjectId":PROJECT,
        "title":"启动失败：尚未创建Session","description":"本机隔离连接目标端口未监听，启动失败，没有Session或数据包。","device":"isolated-daq"}
    receipt = bridge("POST", base + "daq/incidents/", payload, expected=200 if state.get("incident_id") else 201)
    state["incident_id"],state["incident_code"] = receipt["issueId"],receipt["issueCode"]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    assert receipt["sourceSessionId"] is None and receipt["dataPackageId"] is None
    assert receipt["diagnosticStatus"] == "waiting_materials"
    assert bridge("POST", base + "daq/incidents/", payload)["issueId"] == state["incident_id"]
    bridge("POST", base + "daq/incidents/", {**payload,"title":"相同事件不同内容"}, expected=409)
    detail_path = base + f"daq/incidents/{state['incident_id']}/"
    detail = bridge("GET", detail_path)
    assert detail["diagnostics"] == detail["packages"] == detail["regressions"] == []
    db = verify_database()
    assert db["report_count"] == db["baseline_binding_count"] == 0
    checkpoint("startup_without_fabricated_session")
    bridge("POST", detail_path + "session/", {"sourceSessionId":state["incident_baseline"]}, expected=409)
    sql(f"SET time_zone='+08:00'; INSERT INTO data_packages(id,task_id,user_id,name,source_session_id,status,recorded_at,uploaded_at,created_at,updated_at) VALUES('{state['incident_baseline_package']}',{TASK},{ids['Collector']},'启动恢复后的实际基线Session','{state['incident_baseline']}','PendingAnnotation',NOW(),NOW(),NOW(),NOW());")
    linked = bridge("POST", detail_path + "session/", {"sourceSessionId":state["incident_baseline"],"platformTaskId":TASK}, expected=201)
    assert linked["sourceSessionId"] == state["incident_baseline"] and linked["dataPackageId"] == state["incident_baseline_package"]
    assert bridge("GET", detail_path)["sourceSessionId"] == state["incident_baseline"]
    assert verify_database()["baseline_binding_count"] == 0
    content = Path('/home/engram/Documents/tmp/artifacts/native-bridge-e2e-2026-11-09/lifecycle-final/complete-diagnostic.zip').read_bytes()
    package = bridge("POST", base + "packages/", {"name":"启动异常真实栈与配置","defect_id":state["incident_id"],"source_system":"ENGRAM_DAQ","external_id":"incident-"+event_id,"files":[{"path":"startup-diagnostic.zip","size":len(content),"sha256":hashlib.sha256(content).hexdigest()}]},expected=201)
    bridge("POST",base+f"packages/{package['id']}/files/",files={"file":("startup-diagnostic.zip",content,"application/zip")},expected=201)
    deadline = time.monotonic()+200
    while time.monotonic()<deadline:
        detail=bridge("GET",detail_path)
        if detail["diagnostics"] and detail["diagnostics"][0]["status"] not in {"queued","running"}: break
        time.sleep(2)
    assert detail["diagnostics"][0]["status"] == "completed"
    checkpoint("actual_session_and_material_diagnostic")
    repair = call("Manager", "POST", base.split("/quality/")[0] + "/issues/", {"name":"启动异常实际技术修复"}, expected=201)
    patch_defect("Manager",assignee_id=native_ids["TeamLeader"],repair_issue_id=repair["id"])
    patch_defect("TeamLeader",status="in_progress",resolution="核对隔离连接服务并修复启动顺序")
    solution=call("TeamLeader","POST",base+"solutions/",{"defect_id":state["incident_id"],"title":"启动服务并校验监听端口","root_cause":"本机隔离服务未启动，目标端口无监听；不推断硬件故障。","steps":"启动受控监听服务，修复启动顺序后重新采集。","verification":"必须使用修复送测后新Session、新数据包且平台ready，再由经理复读确认。","risk":"仅隔离模拟环境","rollback":"停止隔离监听服务"},expected=201)
    def submit(row):
        return call("TeamLeader","POST",base+f"solutions/{row['id']}/submit/",{"expected_version":row["edit_version"],"reviewer_ids":[native_ids["Manager"]],"required_count":1})
    solution=submit(solution)
    solution=call("Manager","POST",base+f"solutions/{solution['id']}/review/",{"revision_id":solution["revisions"][-1]["id"],"decision":"reject","comment":"补充启动顺序及成功判据。"})
    assert solution["status"]=="rejected"
    solution=call("TeamLeader","PATCH",base+f"solutions/{solution['id']}/",{"expected_version":solution["edit_version"],"steps":"先启动65123监听服务，再启动DAQ；保存连接成功日志并重新采集。"})
    solution=submit(solution)
    revision=max(solution["revisions"],key=lambda row:row["version"])
    solution=call("Manager","POST",base+f"solutions/{solution['id']}/review/",{"revision_id":revision["id"],"decision":"approve","comment":"按冻结方案验证"})
    patch_defect("TeamLeader",status="resolved",fixed_build="startup-fix-v1",resolution="第一轮恢复后送测")
    def start():
        row=call("TeamLeader","POST",base+f"defects/{state['incident_id']}/data-regressions/",{"solution_id":solution["id"],"environment":"本机隔离启动恢复"},expected=201)
        plan=row["plan"]
        plan=call("Manager","POST",base+f"plans/{plan['id']}/workflow/",{"action":"assign","expected_version":plan["workflow_version"],"assignee_id":native_ids["Annotator"]})
        return call("Annotator","POST",base+f"plans/{plan['id']}/workflow/",{"action":"claim","expected_version":plan["workflow_version"]})
    first=start()
    assert verify_database()["baseline_binding_count"]==1
    call("Annotator","POST",base+f"items/{first['items'][0]['id']}/executions/",{"request_id":str(uuid4()),"result":"failed","actual_result":"第一轮连接仍失败","evidence":"保留失败日志"},expected=201)
    failed=call("Annotator","POST",base+f"plans/{first['id']}/workflow/",{"action":"submit","expected_version":first["workflow_version"]})
    assert failed["status"]=="failed" and current()["status"]=="open"
    patch_defect("TeamLeader",status="in_progress",resolution="继续修复启动顺序")
    patch_defect("TeamLeader",status="resolved",fixed_build="startup-fix-v2",resolution="第二轮修复完成送测")
    second=start()
    execution=base+f"items/{second['items'][0]['id']}/executions/"
    passed={"request_id":str(uuid4()),"result":"passed","actual_result":"启动和新数据检查通过","evidence":"新Session连接日志与ready包完整性检查"}
    call("Annotator","POST",execution,passed,expected=400)
    session_id,package_id=str(uuid4()),"incident-fresh-"+uuid4().hex
    time.sleep(1.05)
    sql(f"SET time_zone='+08:00'; INSERT INTO data_packages(id,task_id,user_id,name,source_session_id,status,recorded_at,uploaded_at,created_at,updated_at) VALUES('{package_id}',{TASK},{ids['Collector']},'启动修复本轮新数据','{session_id}','Transferring',NOW(),NOW(),NOW(),NOW());")
    evidence=base+f"plans/{second['id']}/data-evidence/"
    call("Annotator","POST",evidence,{"source_session_id":state["incident_baseline"]},expected=400)
    call("Annotator","POST",evidence,{"source_session_id":session_id},expected=400)
    sql(f"UPDATE data_packages SET status='PendingAnnotation' WHERE id='{package_id}';")
    assert call("Annotator","POST",evidence,{"source_session_id":session_id},expected=201)["package_id"]==package_id
    call("Annotator","POST",execution,passed,expected=201)
    second=call("Annotator","POST",base+f"plans/{second['id']}/workflow/",{"action":"submit","expected_version":second["workflow_version"]})
    approval={"action":"approve","expected_version":second["workflow_version"]}
    call("Annotator","POST",base+f"plans/{second['id']}/workflow/",approval,expected=403)
    sql(f"UPDATE data_packages SET status='ConvertFailed' WHERE id='{package_id}';")
    call("Manager","POST",base+f"plans/{second['id']}/workflow/",approval,expected=400)
    assert current()["status"]=="resolved"
    sql(f"UPDATE data_packages SET status='PendingAnnotation' WHERE id='{package_id}';")
    assert call("Manager","POST",base+f"plans/{second['id']}/workflow/",approval)["status"]=="completed"
    assert current()["status"]=="closed" and verify_database()["report_count"]==0
    state.update(incident_failed_plan=first["id"],incident_passed_plan=second["id"],incident_new_session=session_id,incident_new_package=package_id)
    knowledge=base.replace('/quality/','/knowledge/')
    articles=call("Manager","GET",knowledge+'articles/?status=draft')["results"]
    article=next(row for row in articles if row.get("source_defect_id")==state["incident_id"])
    assert "先启动65123监听服务" in article["content"] and article["status"]=="draft"
    state["incident_knowledge_id"]=article["id"]
    checkpoint("closed_from_fresh_ready_data_and_knowledge_draft")
except Exception as error:
    checkpoint("failed",error_type=type(error).__name__,error=str(error)[:600])
    raise
