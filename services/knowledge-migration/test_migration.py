"""Migration boundaries are independent from live platform configuration."""

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "hub_migration",
    Path(__file__).parents[2] / "ProjectServer/plane/knowledge/legacy_migration.py",
)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def snapshot():
    return {
        "schema": "hub-knowledge-export-v1",
        "source": {
            "host": "10.10.10.157",
            "database": "hub",
            "source_verified": True,
            "runtime_active": False,
        },
        "tables": {
            "knowledge_drafts": [
                {
                    "id": 1,
                    "title": "网络诊断",
                    "content": "检查网络",
                    "status": "PUBLISHED",
                    "visibility_scope": "GLOBAL",
                    "source_issue_id": 2,
                }
            ],
            "knowledge_versions": [
                {
                    "id": 4,
                    "knowledge_id": 1,
                    "source_draft_id": 1,
                    "version_no": 2,
                    "title": "原始版本",
                    "content_snapshot": '{"content":"历史依据"}',
                    "status": "ACTIVE",
                }
            ],
            "issue_tickets": [{"id": 2, "project_id": 9}],
            "knowledge_imports": [],
            "problem_package_files": [],
            "attachments": [],
        },
        "attachments": [],
    }


class MigrationTests(unittest.TestCase):
    def test_preserves_version_and_source_scope_without_publishing(self):
        plan = migration.build_plan(snapshot())
        article = plan[0]
        self.assertEqual(article["source_project"], "global")
        self.assertEqual(article["status"], "draft")
        self.assertFalse(article["publication_active"])
        self.assertEqual(article["versions"][0]["version"], 2)
        self.assertIn("历史依据", article["versions"][0]["content"])
        self.assertIn("PUBLISHED", article["content"])
        self.assertIn("source_issue_id", article["content"])
        self.assertEqual(plan, migration.build_plan(snapshot()))
        captured = snapshot()
        captured["source"]["captured_at"] = "2030-01-01"
        self.assertEqual(plan, migration.build_plan(captured))

    def test_source_project_is_resolved_by_issue_never_by_name(self):
        data = snapshot()
        data["tables"]["knowledge_drafts"][0]["visibility_scope"] = "PROJECT"
        self.assertEqual(migration.build_plan(data)[0]["source_project"], "9")
        data["tables"]["issue_tickets"] = []
        self.assertEqual(migration.build_plan(data)[0]["source_project"], "unmapped")

    def test_refuses_unverified_active_source_and_orphan_versions(self):
        data = snapshot()
        data["source"]["source_verified"] = False
        with self.assertRaises(ValueError):
            migration.build_plan(data)
        data = snapshot()
        data["tables"]["knowledge_versions"][0]["source_draft_id"] = 99
        with self.assertRaises(ValueError):
            migration.build_plan(data)

    def test_scrubs_credentials_from_nested_content_before_persistence(self):
        data = {
            "password": "SYNTHETIC_ONLY",
            "body": "password=TOPSECRET api_key=TOPSECRET\nAuthorization: Bearer TOPSECRET\nhttps://user:TOPSECRET@example.test/path\n-----BEGIN PRIVATE KEY-----\nTOPSECRET\n-----END PRIVATE KEY-----",
            "nested": '{"access_token":"TOPSECRET"}',
        }
        sanitized = migration.redact(data)
        self.assertNotIn("TOPSECRET", str(sanitized))
        self.assertNotIn("SYNTHETIC_ONLY", str(sanitized))
        self.assertIn("[redacted]", str(sanitized))

    def test_rejects_duplicate_source_identity_and_unverified_attachment(self):
        data = snapshot()
        data["tables"]["knowledge_drafts"].append(
            dict(data["tables"]["knowledge_drafts"][0])
        )
        with self.assertRaises(ValueError):
            migration.build_plan(data)
        data = snapshot()
        data["tables"]["knowledge_imports"] = [
            {"id": 1, "knowledge_draft_id": 1, "stored_filename": "evidence.log"}
        ]
        with self.assertRaises(ValueError):
            migration.build_plan(data)


if __name__ == "__main__":
    unittest.main()
