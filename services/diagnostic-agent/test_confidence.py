"""Offline typed confidence boundary: no external model calls."""
import importlib.util
from pathlib import Path
import unittest
from pydantic import ValidationError
spec=importlib.util.spec_from_file_location('confidence_runner',Path(__file__).with_name('runner.py'));runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
def payload(**values):return {'answer':'日志确认连接拒绝','suggested_actions':[],'verification_steps':[],'citations':['FILE-local'],**values}
class ConfidenceTests(unittest.TestCase):
 def test_invalid_values(self):
  for value in [-.1,1.1,float('nan'),float('inf'),True,'0.8']:
   with self.subTest(value=value),self.assertRaises(ValidationError):runner.Report(**payload(model_confidence=value,evidence_assessment='partial',confidence_basis='根因待验证',confidence_references=['FILE-local']))
 def test_legacy_and_supported_confidence(self):
  self.assertIsNone(runner.Report(**payload()).model_confidence)
  result=runner.Report(**payload(model_confidence=.8,evidence_assessment='partial',confidence_basis='连接失败已确认，监听状态待查',confidence_references=['FILE-local']))
  self.assertEqual(result.model_confidence,.8)
 def test_json_schema_declares_numeric_bounds(self):
  variants=runner.Report.model_json_schema()["properties"]["model_confidence"]["anyOf"]
  number=next(row for row in variants if row.get("type")=="number")
  self.assertEqual(number["minimum"],0);self.assertEqual(number["maximum"],1)
 def test_basis_and_references_required(self):
  with self.assertRaises(ValidationError):runner.Report(**payload(model_confidence=.8))
if __name__=='__main__':unittest.main()
