"""Offline smoke contract for synthetic/real separation and project/version exclusions."""
import importlib.util
import json
from pathlib import Path
import unittest
root=Path(__file__).parent
spec=importlib.util.spec_from_file_location('evaluation',root/'evaluate_retrieval.py');evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)
class EvaluationTests(unittest.TestCase):
    def test_reproducible_report_and_boundaries(self):
        data=json.loads((root/'synthetic-retrieval.json').read_text());report=evaluation.evaluate(data)
        self.assertEqual(report['external_calls'],0);self.assertEqual(report['groups']['real']['status'],'no_dataset')
        self.assertEqual(report['groups']['synthetic']['case_count'],5)
        excluded={'DRAFT','REVOKED','OTHER-PROJECT'}
        for row in report['cases']:self.assertFalse(excluded & set(row['semantic']+row['keyword']))
        self.assertEqual(report['cases'][0]['semantic'],['KN-NET'])
    def test_unlabelled_cases_are_rejected(self):
        data=json.loads((root/'synthetic-retrieval.json').read_text());data['cases'][0].pop('provenance')
        with self.assertRaises(ValueError):evaluation.evaluate(data)
if __name__=='__main__':unittest.main()

class DiagnosticEvaluationTests(unittest.TestCase):
    def test_real_and_synthetic_outputs_are_separate_and_bad_citations_fail(self):
        spec=importlib.util.spec_from_file_location('diagnostics',root/'evaluate_diagnostics.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        data=json.loads((root/'synthetic-diagnostics.json').read_text());outputs=json.loads((root/'synthetic-outputs.json').read_text())
        report=module.evaluate(data,outputs);self.assertEqual(report['groups']['real']['evaluated_count'],0)
        self.assertEqual(report['groups']['synthetic']['citation_pass_count'],2)
        outputs['outputs'][0]['citations']=['PRIVATE'];outputs['outputs'][0]['answer']+=' fixture-secret-value'
        report=module.evaluate(data,outputs)
        self.assertEqual(report['groups']['synthetic']['citation_pass_count'],1)
        self.assertEqual(report['groups']['synthetic']['sensitive_output_pass_count'],1)
