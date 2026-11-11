# 初始历史知识种子

seed_version：legacy-157-20261109-v1。11条来自已核来源导出的历史/隔离验收资料、8个历史版本；不是现场设备手册，原PUBLISHED不代表当前可信。所有导入始终待复核draft，不自动发布或跨项目共享。

manifest.json为机器校验入口，schema=engramproject-initial-knowledge-manifest-v1，files只列knowledge-bundle.json的size/SHA256。bundle仅保白名单知识正文/步骤/适用/版本/来源ID/hash，不含原DB全表、账号、session、密码、内部备注或用户附件路径。184B缺失原件只保size/SHA/source_missing，不生成替代物。

部署包可stage到shared/initial-knowledge/<seed_version>，重装不覆盖；无管理员/显式目标时imported=0，不可称初始RAG已可用。

```sh
python3 deploy/release/seed_knowledge.py --check --seed-dir deploy/release/initial-knowledge
# 仅现有真正实例管理员、明确私有项目/工作空间：
python3 deploy/release/seed_knowledge.py --apply --seed-dir deploy/release/initial-knowledge --workspace <slug> --project <UUID> --actor <UUID>
```

仅第一次明确导入成功写入持久初始化标记；此后任何种子版本均already_initialized/imported=0，升级不读、不暂存、不导入新种子。人工编辑/发布/撤回完全保留，不回退任何用户记录。历史版本保追溯且publication_active=false。要用于RAG须管理员逐条复核/扫描/审核发布，原缺附件和fixture限制不得去掉。当前没有预置curated已发布规则资料，不以“随代码带包”冒称已发布。
