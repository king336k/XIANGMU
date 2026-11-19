from plane.quality.remote_profiles import daq_profile


def test_new_daq_adapter_grants_only_fixed_configuration_recovery():
    original={'profile':'daq-local-diagnostics-v1','repair_allowed':False,
              'verification_scope':'read_only_connectivity','readable_files':[],'editable_files':[]}
    observed={'diagnostics':{'protocol':'daq-configuration-v1','ready':True}}
    result=daq_profile(original,observed)
    assert result['repair_argv']==['daq-local-diagnostics-v1','repair']
    assert result['repair_allowed'] is True
    assert result['verification_scope']=='configuration_validation'
    assert result['editable_files']==[]
    assert original['repair_allowed'] is False


def test_old_or_broken_daq_and_manual_profiles_do_not_receive_configuration_permission():
    original={'profile':'daq-local-diagnostics-v1','repair_allowed':True,
              'repair_argv':['daq-local-diagnostics-v1','repair']}
    for observed in ({},{'diagnostics':{'protocol':'other','ready':True}},
                     {'diagnostics':{'protocol':'daq-configuration-v1','ready':False}}):
        result=daq_profile(original,observed)
        assert result['repair_allowed'] is False and 'repair_argv' not in result
    manual={'profile':'simulation','repair_allowed':False}
    assert daq_profile(manual,{'diagnostics':{'protocol':'daq-configuration-v1','ready':True}})==manual


def test_untrusted_command_claims_cannot_expand_the_fixed_profile():
    original={'profile':'daq-local-diagnostics-v1','repair_allowed':False,'readable_files':[],'editable_files':[]}
    result=daq_profile(original,{'diagnostics':{'protocol':'daq-configuration-v1','ready':True,
        'repair_argv':['bash','-c'],'editable_files':['/etc/passwd']},
        'agent_context':{'repair_argv':['bash','-c']}})
    assert result['repair_argv']==['daq-local-diagnostics-v1','repair']
    assert result['editable_files']==[]
