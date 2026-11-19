"""Server-owned fixed DAQ tools; device claims never supply commands or paths."""


def daq_profile(context, capabilities):
    if not isinstance(context, dict) or context.get('profile') != 'daq-local-diagnostics-v1':
        return context
    result = dict(context)
    observed = capabilities.get('diagnostics', {}) if isinstance(capabilities, dict) else {}
    ready = (isinstance(observed, dict) and observed.get('protocol') == 'daq-configuration-v1'
             and observed.get('ready') is True)
    result.update(inspect_argv=['daq-local-diagnostics-v1', 'inspect'],
                  verify_argv=['daq-local-diagnostics-v1', 'verify'],
                  verification_scope='configuration_validation' if ready else 'read_only_connectivity',
                  repair_allowed=ready)
    if ready:
        result['repair_argv'] = ['daq-local-diagnostics-v1', 'repair']
        result['repair_scope'] = 'Only restore semantically invalid initial joint states from verified release baseline through the local configuration adapter. Do not change joint limits, execute motion, restart services or infer values.'
    else:
        result.pop('repair_argv', None)
        result.pop('repair_scope', None)
    return result
