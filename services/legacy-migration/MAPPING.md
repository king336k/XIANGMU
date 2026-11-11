# 旧 Hub 全业务迁移映射计划

来源证据为本机复制的 Java Flyway V14–V55，字段清单与各初始 DDL SHA 在 source-schema.json。工具仅接受离线、已脱敏、带各表数量与SHA的导出包。当前未重新连接157，也不执行正式切换。

| 旧表/领域 | 新目标/处理 | 证据与限制 |
|---|---|---|
| project_hub_users | 显式source-managed账号映射 | V38；仅允许现有PlatformIdentity/PlatformAccount的source+external ID精确匹配；不迁移password_hash、session/token_hash，不通过同名合并；不自动增授项目角色 |
| platform_project_mirrors | 显式映射到隔离Project | V37；source_project_id为主键。目标由操作者明确指定且secret、active、具管理权限；保存旧项目全字段快照 |
| platform_task_mirrors | db.Issue | V37；source_task_id、source_project_id、name、description、steps、status；采集量/模式等保留归档，不伪采集Session |
| issue_tickets EXCEPTION | quality.Defect | V14/15/36/40；title/description/priority/assignee/原状态；旧号、任务/包/设备及其他字段保存在归档，不能成为可信DaqReport |
| issue_tickets FEATURE_TEST | TestPlan | V40；feature_test_items→TestCase、CaseRevision、PlanItem；旧通过状态保留历史，不能替代新平台经理本轮验收 |
| issue_comments | DefectComment | V15；内部备注/已删除评论归档，不转为公开评论 |
| issue_timeline_events/issue_assignments/feature_test_rounds | DefectEvent或PlanEvent及完整源快照 | V15/V40；历史操作人精确映射，不存在映射时不冒充迁移执行人 |
| issue_solutions | Solution+冻结SolutionRevision | V17/V36；root_cause/solution_steps/verification_method/risk_description/rollback_method/repository/commit_sha。旧审查记录保留归档，导入方案默认draft，避免把历史结论当新平台已审核 |
| embedded_test_cases | TestCase+CaseRevision | V48；case_id/module/scenario/prerequisites/steps/expected_result/priority；case_id旧业务编号保留，不覆盖BusinessNumber新号 |
| embedded_test_suites | TestSuite+SuiteItem | V49；case_ids按同源项目case_id解析，版本各为独立迁移对象；默认未发布，原发布信息归档 |
| embedded_test_tasks | TestPlan | V47；name/request_payload/status；不执行任务、不触发硬件；原状态保留快照 |
| embedded_test_executions | PlanItem+TestExecution | V51；task_id→已导入plan、case_id→同项目case业务键；结果、原payload保留，不伪新的执行时间/采集证据 |
| embedded_requirements | db.Issue+Requirement+RequirementRevision | V50；title/description/requirement_key/status/source_payload；新number独立分配，源状态快照保留 |
| embedded_versions | ProjectVersion | V50；version_key/name/description/release_date；自动流转关闭，不生成已发布声明 |
| embedded_release_plans | Release | V50；plan_key/name/description/source_payload；draft且不自动准出 |
| embedded_release_issues/records | Defect/DefectComment | V53；已关联issue_ticket时复用同一映射，不能重复生单；源差异冲突必须报告 |
| embedded_test_reports | SavedReport | V51；name/task_id/report_payload/conclusion/admission/feishu作为历史snapshot，不发送飞书 |
| problem_packages/issue_attachments/problem_package_files/embedded_test_artifacts | ProblemPackage/PackageFile（需校验实际字节）或阻塞报告 | V14/V16/V51；只有manifest中可定位的脱敏文本/已批准二进制，必须size+SHA核验；缺失、跨路径、未review二进制禁止apply，不把文件名当附件成功 |
| knowledge_drafts/versions | Article草稿/历史PublishedRevision | V17/V19；复用现有redact/canonical/digest/UUID逻辑，保留已迁知识稳定identity；默认不可检索，不绕过扫描审核 |
| embedded_test_resources | TestResource | V52；resource_type/status/payload_json；归档原数据，不建运行租约 |
| 其他已知表（回归、agent、review、通知、配置、索引、映射、任务包等） | LegacyMigrationRecord不可执行历史快照 | 保留全部白名单字段与引用。没有完全等价原生语义时明确archive_only，不创建伪DataRegression/DaqBinding/DaqReport、不启动任务、不迁移凭据或发送通知 |
| 序列表、session/幂等缓存 | 明确excluded_runtime_state | V16/V29/V31/V38；保存表数量及排除原因，密码和会话内容从导出前剔除，不复制到目标 |

每个源行都有source_hash及固定UUID，native/archived/excluded分别计数，不允许把archive_only表称为原生工作流全等迁移。未知表、未知字段、重复主键、跨项目引用、缺账号映射、源/附件hash不符会进入冲突报告并阻止apply。

apply单事务创建，现有目标ID或源指纹不同均拒绝；重跑仅在所有目标快照逐字段一致时返回unchanged。rollback只删除该run新创建且未变更的对象，先检查完整反向依赖（含新建评论/关联/编号），任一后续编辑或外部依赖即全批拒绝，不回退用户工作。目标已有project/account绝不删除。业务编号由现有BusinessNumber分配并记录，不修改旧号。
