from plane.quality.module_routing import identified


def test_module_scalar_label_is_not_lost_when_failure_message_starts_with_component_name():
    options = [{"key": "daq", "name": "DAQ"}, {"key": "teleop", "name": "遥操"}]
    assert identified("ERROR simulated=true module=teleop VR connection timeout", options) == {"teleop"}
    assert identified("ERROR simulated=true module=daq MCAP queue full", options) == {"daq"}
    assert identified("ERROR module=teleoperation VR connection timeout", options) == set()


def test_ambiguous_or_quoted_human_labels_never_collapse_to_the_first_module():
    from plane.quality.module_routing import identified

    options = [{"key": "daq", "name": "DAQ"}, {"key": "teleop", "name": "遥操"}]
    for text in [
        "ERROR 模块：DAQ 和 遥操同时失败",
        "ERROR module=daq and teleop failure",
        'ERROR module="daq teleop" failure',
    ]:
        assert identified(text, options) != {"daq"}
