"""Run over the authorized read-only SSH broker. Emits only sanitized JSON.

The local caller prepends the shared pure redactor and identity helpers.
"""

import base64
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from hub_migration_helpers import digest, redact

DATABASES = ["sz2607_project_hub_local", "sz2607_project_hub_acceptance_20260902"]
TABLES = [
    "knowledge_drafts",
    "knowledge_versions",
    "knowledge_imports",
    "knowledge_chunks",
    "knowledge_review_records",
    "knowledge_sanitization_records",
    "knowledge_sanitization_findings",
    "issue_tickets",
    "issue_solutions",
    "regression_tests",
    "regression_test_data",
    "issue_attachments",
    "regression_test_attachments",
    "problem_packages",
    "problem_package_files",
    "agent_reports",
]


def mysql(sql):
    result = subprocess.run(
        [
            "docker",
            "exec",
            "transcengram-mysql",
            "sh",
            "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot -N -B -r -e "$1"',
            "read",
            sql,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode:
        raise RuntimeError("Source SELECT failed; no sensitive error details emitted")
    return result.stdout


exports = []
for db in DATABASES:
    schema = mysql(
        "SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='"
        + db
        + "' ORDER BY TABLE_NAME,ORDINAL_POSITION"
    )
    columns = {}
    for line in schema.splitlines():
        table, column = line.split("\t")
        if table in TABLES:
            columns.setdefault(table, []).append(column)
    statements = [
        "SET TRANSACTION READ ONLY",
        "START TRANSACTION WITH CONSISTENT SNAPSHOT",
    ]
    for table, names in columns.items():
        pairs = ",".join("'" + column + "',`" + column + "`" for column in names)
        statements.append(
            "SELECT JSON_OBJECT('table','"
            + table
            + "','row',JSON_OBJECT("
            + pairs
            + ")) FROM `"
            + db
            + "`.`"
            + table
            + "`"
            + (" ORDER BY id" if "id" in names else "")
        )
    statements.append("COMMIT")
    tables = {table: [] for table in columns}
    for line in mysql(";".join(statements)).splitlines():
        item = json.loads(line)
        tables[item["table"]].append(item["row"])
    hashes = {table: digest(rows) for table, rows in tables.items()}
    files = []
    for table, path_key, size_key in [
        ("knowledge_imports", "stored_filename", "size_bytes"),
        ("issue_attachments", "file_path", "file_size"),
        ("problem_package_files", "file_path", "file_size_bytes"),
    ]:
        for row in tables.get(table, []):
            original = row.get(path_key)
            if not original:
                continue
            path = Path(original)
            entry = {
                "table": table,
                "id": str(row["id"]),
                "source_path": original,
                "expected_bytes": row.get(size_key),
                "expected_sha256": row.get("content_hash")
                or row.get("checksum_sha256"),
            }
            if table == "knowledge_imports":
                entry["import_id"] = str(row["id"])
            if not path.is_absolute():
                entry.update(
                    {
                        "verified": False,
                        "reason": "relative_storage_path_requires_runtime_root",
                    }
                )
            elif not path.is_file():
                entry.update({"verified": False, "reason": "source_file_missing"})
            elif path.stat().st_size > 20 * 1024 * 1024:
                entry.update({"verified": False, "reason": "requires_streamed_export"})
            else:
                raw = path.read_bytes()
                original_sha = hashlib.sha256(raw).hexdigest()
                try:
                    sanitized = redact(raw.decode("utf-8")).encode()
                    entry.update({"redacted": raw != sanitized, "media": "text"})
                    entry["base64"] = base64.b64encode(sanitized).decode()
                    entry["sha256"] = hashlib.sha256(sanitized).hexdigest()
                    entry["original_sha256"] = original_sha
                    entry["bytes"] = len(sanitized)
                    entry["verified"] = entry["expected_bytes"] in (
                        None,
                        len(raw),
                    ) and entry["expected_sha256"] in (None, "", original_sha)
                    if not entry["verified"]:
                        entry["reason"] = "source_metadata_hash_or_size_mismatch"
                except UnicodeDecodeError:
                    entry.update(
                        {
                            "verified": False,
                            "reason": "binary_requires_privacy_review",
                            "original_sha256": original_sha,
                        }
                    )
            files.append(entry)
    exports.append(
        redact(
            {
                "schema": "hub-knowledge-export-v1",
                "source": {
                    "host": "10.10.10.157",
                    "database": db,
                    "source_verified": True,
                    "runtime_active": False,
                    "classification": "historical_acceptance"
                    if "acceptance" in db
                    else "historical_local",
                    "captured_at": datetime.now(UTC).isoformat(),
                    "activity_evidence": "source-activity.json + source-hub.json: Hub containers exited, no Hub listener/DB connection",
                },
                "source_table_sha256": hashes,
                "tables": tables,
                "counts": {table: len(rows) for table, rows in tables.items()},
                "attachments": files,
            }
        )
    )
print(json.dumps(exports, ensure_ascii=False))
