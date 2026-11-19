# 诊断 Agent 的源码、现场能力与验收边界

核对日期：2026-11-19。本文件描述当前代码与本轮新增能力，不表示已部署，也不表示任何实机恢复。平台仓库为 EngramProject；DAQ 路径均相对 `engram_Teleop_DAQ` 仓库。已读取实际远程入口、策略、launcher 服务接口、配置诊断与中央研究调用链；未声称通读全部源码。

## 实际调用链

上传材料 → 平台 `ProjectServer/plane/quality/remote_materials.py:feedback_materials` → `remote_tasks.py` 的可信 context → `services/diagnostic-agent/remote_runner.py:analyze` → 中央受限 RPC → DAQ `scripts/remote-diagnostics/connector.py:run_command` → 本机 launcher `app/launcher/api/router.py:remote_diagnostics` → launcher runtime 的 `remote_diagnostics` → `app/launcher/robot/remote_diagnostics.py` / `configuration_diagnostics.py`。

模型得到的用户描述、上传日志和源码都是事实数据，不能增加执行权限。平台 `remote_tools_policy.py:check_tool` 与 DAQ `connector.py:Policy.argv/read/patch` 独立校验固定命令和文件；模型不能把 argv 的 purpose 改成 inspect 来绕过变更约束。源码下载与现场执行是不同能力；读到修复函数不代表获准调用它。

## 能力矩阵

| 故障类别                             | 当前真实取证入口                                                                                                                                                | 当前真实修改入口                                                                                                                                                                                                                                           | 当前验证与缺口                                                                                                                                                                                                                                                       |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 运行配置结构、数值、有效配置覆盖关系 | 固定 inspect 的 configuration：artifact/override/effective 路径、哈希、字段 findings、baseline trust、snapshot_sha256；`ConfigurationDiagnostics.inspect`       | 本轮新增的固定 repair + 当前 snapshot SHA，由 `ConfigurationDiagnostics.repair` 在设备认可的标定来源/显式计划支持时恢复被证实无效的 initial_joint_states；不改变 joints_name/joint_limits，不允许模型给值/路径，保留 artifact，备份与CAS，目标revision复核 | 固定 verify 只验证 configuration_validation；configuration_repaired 与业务 repaired 分开。当前值无效不证明正确目标值；release默认/历史备份仅candidate。缺设备标定provenance时correct_value_unknown并阻断。其它配置字段、配置缺失或不可信 baseline 均不是自动恢复能力 |
| 缺文件/模板/路径                     | 文件 API 能在明确 readable_files 内读取；配置 inspect 可报告 present=false；批准源码可读模板作为参考                                                            | 仅已有明确 editable_files 的非代码配置可 CAS patch；DAQ 默认登记 profile 未提供通用文件创建/模板安装授权                                                                                                                                                   | 缺字段、文件来源、版本及目标目录必须具体；不能将仓库存在模板等同现场文件恢复。需要按模板类别增加受限安装入口及检查                                                                                                                                                   |
| Python/系统依赖、解释器或容器环境    | 上传原始异常；固定 inspect 目前只有 sdk 状态及配置；specialist health 只报告自身依赖是否可用                                                                    | 未提供生产依赖安装入口。无自动 pip/apt/任意 shell                                                                                                                                                                                                          | 不能证实目标业务进程解释器/venv/容器包集合；应新增只读运行清单，再提供锁定包/版本/环境的管理员修复入口。import 成功不证明业务恢复                                                                                                                                    |
| 服务进程未就绪或崩溃                 | 固定 inspect 的 launcher_service、robot_connection、sdk 和已知 components 状态；日志来自上传材料；launcher `LauncherService.status/node_logs/logs` 已有内部接口 | 未为 Agent 暴露任意 start/stop/restart。launcher 服务本身有启动与停止方法，不表示 Agent 可调用                                                                                                                                                             | 需要固定只读进程/日志快照，绑定 component、deployment revision、退出码与关联错误。重启能力需限定组件及前置状态；复测必须针对原服务接口与业务操作                                                                                                                     |
| ROS/DDS、机器人连接/反馈             | 固定 inspect 的连接层及组件；已配置 ROSA/RAI 可 health 后只读 topics/services；Holmes 只读固定 inspect；launcher `probe_robot_network` 有内部接口               | 未提供连接参数、DDS配置、网络或机器人状态变更入口                                                                                                                                                                                                          | Ping 或组件running不能证明订阅者接收与新鲜反馈。需固定源/消费者/QoS/时间戳/拓扑观测，验证连接变化与original failure；运动/复位单独授权                                                                                                                               |
| DAQ采集、媒体、存储                  | 上传capture/节点原始日志；固定 inspect 检查真实采集卷剩余空间、组件状态                                                                                         | 无清理数据、改挂载、重启媒体或实际录制入口                                                                                                                                                                                                                 | 空间检查不覆盖相机帧、录制session、文件写入、停止封包、上传闭环。应从已有 DAQ/session/media 接口接入限定只读取证，再按具体故障设计安全修复与可执行验收                                                                                                               |
| 业务源码定位、代码补丁               | 项目知识检索 + `research_sources(catalog/list_source_paths/read_source)`：批准 GitHub/docs 和按项目授权的 Gitea 固定 ref/root                                   | 现场 Policy 明确禁止 editable_files 包含可执行代码；无代码 patch/build/deploy 工具                                                                                                                                                                         | Agent 可提出有来源的定位与建议，不能称代码已修改/构建/部署。代码修复应进入受控仓库工作区并通过构建/回归/部署过程，再独立现场验收                                                                                                                                     |

设备批准合同为独立private runtime文件 `remote-diagnostics/configuration-repair-approval.json`，schema `robot-config-repair-approval-v1`，authority限定 `explicit_repair_plan|verified_device_baseline`，并绑定robot/target_revision/snapshot_sha256/baseline_manifest_sha256/allowed_fields/expires_at。inspect中的release_candidate不是许可；缺审批返回baseline_not_approved_for_device。Agent不能写这个批准文件；其正确值仍由独立用户计划或设备认可的标定来源负责。用户已明确的注错及正确值可以形成有限计划，未知故障不能自动把release默认认作正确值。

配置 repair 是上述分类中的有限一类，不是“所有问题通用修复”。本地fake gateway的依赖/服务/存储三场景测试仅证明：模型工具循环允许在首次失败后继续取证并处理新的不同原因、要求最终检查，并不会给设备补出这些尚缺的生产工具。

## 同版本源码研究

1. 从本次 deploymentSnapshot、version_info 的主仓库与每个子仓库 commit 建立版本表。父仓库 commit 不代表子仓库当前实现；dirty/source snapshot hash也要保留。
2. 先用当前原始错误及模块名检索项目知识，返回条目的 version/version_scope 和历史案例仅作参考。历史案例没有deployment revision时不能判定版本相同。
3. `research_sources(operation='catalog')` 返回管理员批准的 source id、repository/ref/root；模型只能列相对路径和读取固定 ref，不可自选 URL、host 或 ref。
4. 现有 Gitea 配置 `REMOTE_RESEARCH_SOURCES` 支持 `kind/host/repository/ref/root/project_ids/allowed_cidrs/token_env`，可让管理员为每个子仓库配置精确部署 commit；凭据仅由中央服务读取。仓库未批准或ref不同必须报告具体缺项。
5. `read_source` 的 content API `revision` 目前来自文件 blob SHA，不是仓库 commit；`reference` 才是配置的 ref。不得把blob hash当部署提交匹配证据。更通用方案是服务端从已验证deploymentSnapshot解析项目授权仓库与不可变commit，返回repository_commit/blob_sha256两个独立字段；现阶段没有这个自动解析能力。
6. 只读文件可跟踪 error producer→调用者→输入校验→配置来源→实际生效链。遇到子模块目录必须选对应批准子仓库；列表中的submodule不能被当作已读取源码。

## 当前最小补齐顺序

1. 完成负向 inspect 的证据准入：结构化检查发现故障并返回exit1仍是已完成取证，不能阻断知识和修复。runner已处理明确scope+checks/configuration回执；中央 `remote_research.py:ResearchView.post` 原先仅认可exit0，也需要同步处理同一合同。
2. 固定 inspect 返回每类 capability：真实目标/容器、支持的只读操作、支持的repair id、版本、验证覆盖范围及未支持原因。当前配置结果已有 `configuration.capabilities`；runner将其原样送入get_diagnostic_state.observed_capabilities并输出真实capability_gaps，服务/依赖/连接repair明确false；不要用一个repair_allowed代表全域能力。
3. 复用 launcher现有 `node_logs/status/version_info/probe_robot_network/hardware_acceleration_status` 提供固定只读bundle。bundle只接受已登记组件id、有限时间窗/行数，返回原始错误前后文、环境与版本，不接收shell或任意目标路径。否则Agent只能说明缺口。
4. 建立同版本主仓库/子仓库中央批准源码映射；无源码时明确请求哪一个repository@commit的相对文件及调用链，不编造函数。
5. 按类别逐项增加最小修复adapter及真正业务验收。依赖修复只针对可信锁与正确环境；服务只针对已登记组件；媒体/采集应保留数据并验原流程。每个adapter具备预检、权限、CAS/目标revision、备份/回退、幂等与失败回执。

## 失败后的最小上下文与报告

`get_diagnostic_state` 重供 uploaded:N 历史证据、tool:N 当前回执、剩余预算、固定入口、文件许可与验证scope。上传原始材料不应再次被概述为“没有原始日志”；缺的是当前环境、同版本源码、baseline还是业务验收，需要逐项说明。

`findings.kind=observed` 必须引用已有真实证据编号；假设使用 predicted。服务端会检查编号存在，但不声称自动证明每句话的逻辑蕴含。`remaining_gaps` 是模型给出的具体缺证据/缺能力；执行操作、修改定位和验证通过仍仅依据回执。

首次推理超时只在同messages请求层重试一次，不重跑整个工具流程；持续超时保留已完成回执。相同修复在没有变化的现场inspect/read证据下禁止重复。失败后应该先确定新原因、不同输入或缺能力，再选择下一步。不能把请求重试、知识命中、配置检查、组件running或fake环境通过写成现场业务恢复。

## 本轮验证

`test_remote_runner.py` 使用真实PydanticAI/LangGraph、真实本机HTTP gateway、合成凭据、可变fake设备与function model；推理超时使用真实OpenAI适配器及httpx MockTransport。覆盖配置/业务scope分离、原始证据准入、越权写入、负向取证、CAS参数、重复修复、跨原因后续修复、持续超时与401。不是生产部署或实机E2E。
