"""Read-only regression check for isolated Chinese fixture names through the real authority API."""
import subprocess
import json

program = '''import os,json
os.environ.setdefault("DJANGO_SETTINGS_MODULE","plane.settings.production")
import django;django.setup()
from plane.quality import platform
catalog=platform.fetch("latest-native-verification","/internal/issue-integration/catalog/projects")
rows=catalog["items"]
expected={9861:"本机账号与DAQ验收",1401109:"最新三端隔离联调",1491109:"独立诊断排队压力验收"}
for row in rows:
 if row["id"] in expected: assert row["name"]==expected[row["id"]], "Project fixture encoding mismatch for "+str(row["id"])
context=platform.fetch("latest-native-verification","/internal/issue-integration/tasks/140110901/context")
assert context["taskName"]=="本机故障回归采集", "Task fixture encoding mismatch"
print(json.dumps({"projects":[{"id":r["id"],"name":r["name"]} for r in rows if r["id"] in expected],"task":context["taskName"]},ensure_ascii=False))
'''
result=subprocess.run(['docker','exec','-w','/code','plane-local-20261106-api-1','python','-c',program],capture_output=True,text=True)
if result.returncode: raise SystemExit('Isolated source fixture Chinese encoding check failed')
print(result.stdout)
