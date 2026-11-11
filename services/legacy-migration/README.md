# 全业务旧 Hub 迁移工具

本工具只处理离线已脱敏快照，默认dry-run。生产/157原库没有执行迁移或切换。已知69张源表全部列于schema；可等价表达的核心实体导入native，其余归档或明确排除，**不表示全部旧流程可在新平台原样操作**。详见MAPPING.md。

## 命令

先从本机已获得的离线JSON表数据生成来源包（不含密码hash、session、token或配置secret）。每个源附件需独立manifest，包含table/id/verified/bytes/sha256/base64；文本先脱敏并media=text，二进制需privacy_reviewed=true。

```bash
python services/legacy-migration/export_source.py --input-json source-tables.json --host-label reviewed-offline-source --database project_hub_local --attachment-manifest reviewed-files.json --output source-export.json
```

也可显式读取**独立本机MySQL容器**，export内部使用REPEATABLE READ + READ ONLY一致性事务。工具不会SSH。不要将原库或生产地址凭据写入文件。

```bash
python services/legacy-migration/export_source.py --mysql-container isolated-source-mysql --host-label isolated-fixture --database project_hub_fixture --output source-export.json
```

目标Django数据库必须已执行quality0040迁移。mapping.json只含显式project/user UUID及source_instance，不含凭据。账号必须已有精确source PlatformIdentity，不会按姓名合并、复制密码、创建新的登录权限或放宽角色。

```json
{"source_instance":"legacy-fixture","projects":{"9":"TARGET_PROJECT_UUID"},"users":{"1":"TARGET_USER_UUID"}}
```

使用目标环境的Python和环境配置：

```bash
python services/legacy-migration/migrate.py dry-run --source source-export.json --mapping mapping.json --actor TARGET_REVIEWER_UUID --output dry-run.json
python services/legacy-migration/migrate.py apply --source source-export.json --mapping mapping.json --actor TARGET_REVIEWER_UUID --output applied.json
python services/legacy-migration/migrate.py rollback --run-id IMPORT_RUN_UUID --actor TARGET_REVIEWER_UUID --output rollback.json
```

- dry-run会在事务中完整预演native映射后回滚，校验编号/实际关联/目标冲突，附件不写入磁盘。
- apply对所有业务写与审计一次atomic；新附件用独占文件路径写入，数据库失败时清理新文件。源hash/mappinghash/planhash、重复ID、未知字段/表、孤儿、跨项目、缺actor映射、附件异常均阻止apply。
- 默认缺失附件阻止apply。仅用户明确选择 `allow_missing_attachment_metadata:true` 时保留missing标记及源manifest，归档未恢复，不能宣称完整恢复。
- 相同源身份重复apply仅在source/mapping及所有目标字段/附件bytes一致时返回unchanged；新来源内容必须人工核对，不覆盖用户编辑。
- rollback先核对每个目标完整hash、附件bytes、反向依赖和当前管理权，再只删除该run创建的对象；任何新增评论/关联或编辑均拒绝全批。保留迁移审计、已有项目/账号及用户后续工作。
- 历史方案/知识/套件/版本/发布回到待复核状态；旧regression/agent/review配置归档，不能作为本平台新采集证据，且不发送通知、调用模型或启动硬件。

## 已验证

独立Postgres `test_legacy_full_finish` / copied source `/legacy-full-finish`。完整schema fixture包含33行源数据、16+核心领域及review/agent/regression历史，创建53个目标（含业务编号/关联），第二遍33条unchanged，rollback实际移除53目标，保留33审计记录；源项目和source-managed账号保留。实际附件字节/hash验证。10专项测试覆盖dry-run、atomic失败清理、复合主键、跨项目、源变更、用户编辑、新依赖和回滚。

证据在 `/home/engram/Documents/tmp/artifacts/legacy-full-migration-2026-11-09/fixture/verification.json`。`fixture/source-export.json`与`mapping.json`可供复核，不含密码或token；原157及原DP无写入。

未覆盖为native工作流的实体：全部archive_only/excluded明细见source-schema.json及MAPPING.md。实际源版本新增DDL/字段、丢失附件、同名歧义、旧知识已迁对象冲突需人工核对，工具会停止，不自动猜映射。正式原库导出/实数验收/切换仍需单独授权与已备份演练，不能用本机fixture代替生产验收。
