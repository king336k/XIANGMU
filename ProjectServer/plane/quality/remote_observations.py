"""Transport success and a negative diagnostic observation are different facts."""
import json


def completed_inspection(receipt):
    if (not isinstance(receipt, dict) or receipt.get('error') or receipt.get('timed_out')
            or receipt.get('truncated')):
        return False
    if receipt.get('exit_code') == 0 and receipt.get('ok') is not False:
        return True
    if receipt.get('exit_code') != 1:
        return False
    try:
        observed = json.loads(receipt.get('stdout', ''))
    except (TypeError, ValueError):
        return False
    return (isinstance(observed, dict)
        and observed.get('scope') in {'configuration_validation', 'read_only_connectivity'}
        and isinstance(observed.get('checks'), list) and bool(observed['checks'])
        and all(isinstance(check, dict) and check.get('state') in {'pass', 'fail', 'unknown'}
                for check in observed['checks']))
