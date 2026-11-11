# Legacy Hub knowledge migration

Imports verified historical Hub knowledge as isolated drafts. No automatic source login, publication or project grants.

1. Inspect actual source runtime and schemas over a separately authorized read-only SSH broker. Never store SSH or datasource credentials. Historical inactive databases must say `runtime_active=false`.
2. Export the allowlisted tables using a read-only consistent transaction:

```sh
python services/knowledge-migration/remote_read.py \
  services/knowledge-migration/export_source.py \
  /home/engram/Documents/tmp/artifacts/knowledge-migration-2026-11-09/source-export.json \
  --helpers ProjectServer/plane/knowledge/legacy_migration.py
```

3. Review the export and explicit reviewer mapping. Execute `import_local.py` with Django shell on the new platform only. Its stdin JSON requires `reviewer_id` and `exports` (list of export objects). The script loads the helper from `/migration-legacy.py`. Use a dedicated review workspace/project per source database/scope; only the reviewer may be a member. All imported articles stay draft and inactive. Original foreign IDs remain provenance, never guessed foreign keys.
4. Run `verify_runtime.py` in the new API container with native Django settings. It creates short-lived verifier sessions, calls public HTTP routes through `proxy`, checks reviewer/outsider boundaries and empty retrieval, then deletes those sessions. It does not prove source-account login.
5. Keep exports, detailed plans, hashes and reports in the user artifact directory, not source control. Source missing/binary/unverified files are explicit gaps; do not synthesize evidence.

Retrying an identical import creates no rows. Changed source, mapping, target edits or historical versions require manual reconciliation. Historical revision numbers are reserved so a later reviewed publication does not collide with preserved history.

Checks:

```sh
python -m unittest discover -s services/knowledge-migration -p test_migration.py
# Use an independent test database; never share a concurrent test_plane.
pytest plane/tests/contract/app/test_knowledge_migration.py
```

See `docs/design/three-platform/知识迁移验收-20261109.md` for counts, boundaries and the missing original attachment.
