import pytest
from rest_framework.exceptions import PermissionDenied
from plane.quality.remote_tools_policy import check_tool


def test_model_cannot_label_repair_as_inspection():
    policy={"inspect_argv":["fixed","inspect"],"verify_argv":["fixed","verify"],"repair_argv":["fixed","repair","--sha"],"repair_allowed":False}
    check_tool(policy,"run",{"argv":["fixed","inspect"]})
    with pytest.raises(PermissionDenied):check_tool(policy,"run",{"argv":["fixed","repair","--sha","a"*64],"purpose":"inspect"})
    with pytest.raises(PermissionDenied):check_tool(policy,"run",{"argv":["true"]})
    policy["repair_allowed"]=True
    check_tool(policy,"run",{"argv":["fixed","repair","--sha","a"*64]})
    with pytest.raises(PermissionDenied):check_tool(policy,"run",{"argv":["fixed","repair","--sha","a"*64,"extra"]})


def test_file_allowlist_and_readonly_specialists():
    policy={"repair_allowed":True,"readable_files":["settings.json"],"editable_files":["settings.json"],"specialists":{"rosa":{"argv_prefix":["python","bridge"]}}}
    check_tool(policy,"read_file",{"path":"settings.json"})
    check_tool(policy,"patch_file",{"path":"settings.json"})
    check_tool(policy,"run",{"argv":["python","bridge","rosa","inspect"]})
    with pytest.raises(PermissionDenied):check_tool(policy,"patch_file",{"path":"bridge.py"})
