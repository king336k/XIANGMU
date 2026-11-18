"""Run with ProjectServer's Django runtime; no database or network mutations."""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','plane.settings.test')
import django
django.setup()
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from rest_framework.exceptions import PermissionDenied
from plane.quality import remote_research as research


class ResearchViewTest(unittest.TestCase):
    def setUp(self):
        self.cache=MagicMock()
        self.cache.incr.return_value=1
        self.cache.get.return_value=True
        self.run=SimpleNamespace(pk='run',workstation=SimpleNamespace(agent=SimpleNamespace(project_id='project',project='project'),
            capabilities={'agent_context':{'inspect_argv':['fixed-inspect']}}),remotecommand_set=MagicMock())
        self.run.remotecommand_set.filter.return_value.__getitem__.return_value=[SimpleNamespace(
            payload={'kind':'run','argv':['fixed-inspect']},result={'ok':True,'exit_code':0})]
        self.request=SimpleNamespace(auth=self.run,data={'operation':'read_source','source_id':'rai','path':'README.md','gap':'specific gap'})

    def test_external_requires_knowledge_attempt(self):
        self.cache.get.return_value=False
        with patch('django.core.cache.cache',self.cache),self.assertRaises(PermissionDenied):
            research._view()().post(self.request)

    def test_failed_inspection_is_not_current_evidence(self):
        self.run.remotecommand_set.filter.return_value.__getitem__.return_value=[SimpleNamespace(
            payload={'kind':'run','argv':['fixed-inspect']},result={'ok':False,'exit_code':1})]
        with patch('django.core.cache.cache',self.cache),self.assertRaises(PermissionDenied):
            research._view()().post(self.request)

    def test_kb_error_does_not_permanently_block_approved_research(self):
        with patch('django.core.cache.cache',self.cache),patch.object(research,'knowledge',side_effect=RuntimeError('synthetic')):
            response=research._view()().post(SimpleNamespace(auth=self.run,data={'operation':'knowledge','query':'fault'}))
        self.assertEqual(response.data['error'],'knowledge_unavailable')
        self.cache.set.assert_called_once()

    def test_approved_source_requires_gap_and_uses_authenticated_project(self):
        with patch('django.core.cache.cache',self.cache),patch.object(research,'read_source',return_value={'content':'reference'}) as fetch:
            response=research._view()().post(self.request)
        self.assertEqual(response.data['content'],'reference')
        self.assertEqual(fetch.call_args.args[:3],('project','rai','README.md'))


if __name__=='__main__':
    unittest.main()
