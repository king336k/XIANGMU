# Central knowledge-first research

`RemoteResearch` is exported from `plane.quality.remote_research`. Route its `as_view()` at `/api/quality-auth/remote-diagnostics/agent-research/`. It reuses `ToolAuthentication`, including current task credential, owner permissions, station identity and expiry checks.

The runner exposes sequential `search_project_knowledge(query)` and `research_sources(operation, source_id, path, gap)` tools. It derives the research endpoint from the trusted gateway origin. Set trusted `context.require_knowledge_search=true` to require a KB attempt before accepting a final report. The model cannot choose an external URL, headers, credentials, repository, branch or network grant.

POST operations:

- `knowledge`: `query` up to2000 characters. Returns published/current and valid shared project KB, plus current-owner/same-project historical runs whose workstation remains permitted. Both success and failure outcomes retain scope and execution evidence; `counts` distinguishes publications from historical cases. Historical `reported_repaired` is not revalidated current success. No automatic Article publication occurs.
- `catalog`: returns fixed approved source IDs and administrator-granted private sources for this project. Credentials and private CIDR configuration are omitted.
- `read_source` / `list_source_paths`: `source_id`, relative `path`, and a specific `gap` up to1000 characters. Requires a KB attempt and a successful current run's exact configured inspection command. Empty/unavailable KB does not permanently block approved external research. No log/query/private source text is sent to an external search service; only bounded source file/directory requests occur.

External calls use HTTPS with normal certificate verification, validate every DNS result, pin the chosen validated address while preserving hostname verification, follow no redirects, use no environment proxies, and limit response size to256KiB. Public sources must resolve globally. Private `git.transcengram.com` is Gitea: only administrator-configured repositories, refs, project IDs and private CIDRs are accepted; loopback/link-local/metadata/multicast addresses remain forbidden. No arbitrary Git process or shell runs.

Private configuration shape (administrator supplies actual project ID, network CIDR and credential through deployment configuration; never commit credential values):

```json
{
  "teleop-source": {
    "kind": "gitea",
    "host": "git.transcengram.com",
    "repository": "remote_control_robot/engram_Teleop_DAQ",
    "ref": "test/teleop-daq-diagnostic-feedback-20261111",
    "root": "",
    "project_ids": ["<authorized-project-id>"],
    "allowed_cidrs": ["<administrator-approved-cidr>"],
    "token_env": "REMOTE_RESEARCH_GITEA_TOKEN"
  }
}
```

Place this object in `REMOTE_RESEARCH_SOURCES` on the central API only. The referenced token must be a read-only repository credential. Do not pass it to the runner, browser or field devices. The platform source can be a separately granted source ID for repository `long/EngramProject`, ref `feat/coverage-followups-152`; never infer permission from another repository grant.

Returned source metadata includes source ID, reference, path, URL, fetched time, blob revision, SHA256 and truncation. Content is redacted, bounded and marked untrusted. A cited branch may move; match runtime versions and current observations before recommending changes. Large/binary files and unsupported directory objects fail closed. No E2E private-source access is claimed without deployment credentials and current project authorization verification.

Knowledge governance already exists: `Article.source_defect`, `Article.source_regression`, draft/version fields, `ArticleWorkflow`, immutable `PublishedRevision` and valid `KnowledgeShare`. Historical remote runs augment retrieval without bypassing these publication controls. This accumulates reusable evidence rather than changing model weights or expanding permissions.

Validation: `research_test.py` runs without Django; `research_django_test.py` runs with the ProjectServer Django environment and mocked storage/network boundaries; `test_remote_runner.py` exercises real typed agent orchestration against a local HTTP gateway. A live public GitHub README read through the actual pinned transport was verified for RAI1.1.0. Root deployment and fresh full-pipeline verification remain separate acceptance steps.
