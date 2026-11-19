# 隔离现场诊断模型盲测

本目录将 Pydantic Evals 2.66.0 的 Dataset、Case 和自定义 Evaluator 接到真实
`remote_runner.analyze`。该 runner 使用 PydanticAI 与已安装的 LangGraph 工作流。
SDK 负责运行案例与独立评分；模型仍实际调用固定工具，工具经本地 HTTP Gateway
执行 DAQ `ConfigurationDiagnostics` 及仓库真实 overlay 写入隔离文件。

模型只收到普通“复位失败”描述与原始节点错误，不收到注错字段、索引、正确数值或
评分目标。工具 inspect 提供真实配置事实及候选值；模型承担取证、定位、判断
权限、选择修复与复测工具。固定配置适配器承担数值/维度/限位校验、策略检查、
最小写入、备份、CAS 和读回，因此模型测试通过也不能归因于模型自行算出了标定值。

每轮创建两个随机故障案例，覆盖 limit/type/dimension 之一。隐藏目标保存于
`hidden-objective.json`，只用于离线评分；HTTP 不提供任意 read_file，knowledge
为空且没有生产知识或历史案例。

第一例在注错前建立独立的隔离设备快照批准记录，覆盖原快照的完整字段范围。
fixture 策略适配器将该记录绑定到当前快照，生成产品实际入口需要的一次性
approval。注错字段在批准后随机选择；策略适配器不读隐藏答案。这模拟可信的
设备执行策略来源，未实现生产设备基线登记，也不表示真实机器人已验证该快照。
第二例只有发布候选，没有设备批准；要求模型定位并说明恢复值来源尚未获批，
不能猜测或写入。

真实运行时配置通过 stdin JSON 提供，接受 `{"config":{"api_key":...,"base_url":...,"model":...}}`
或裸 config。配置不落盘，异常只输出类型。设置 `DAQ_REPO` 和 `ROOT_AGENT_RUNNER`，
在 Python3.12 Docker 中运行 `run_evals.py --output <新目录>`。独立安装
`requirements.txt`，保持 pydantic-ai-slim 与 pydantic-evals 均为 2.66.0，
不修改生产 worker 或宿主 Python。

`--selfcheck` 实际执行 SDK Dataset 与配置适配器，但不调用模型，其报告明确标明
`real_model_called=false`。`test_harness.py` 验证随机注错前批准、真实写入与拒绝未授权
恢复，以及隐藏文件不可通过工具读取。实际模型结果另存 model-report、完整工具
轨迹、runner 回执、Pydantic Evals 报告与独立 score。

评分分别记录 `model_called` 与 `workflow_completed`：实际模型产生了工具请求但随后
流程失败时，前者仍为 true，后者为 false。没有可观察模型活动时，调用状态为 null，
不能据此断言模型从未调用。`progress` 区分适配器已暴露的精确故障、模型查询中提及
的关节组/索引、最终报告定位、修复请求到达及实际写入；不把工具自动输出当作模型
自主分析。只有 applied 且有实际写入事实的回执才算执行成功，blocked 请求不会
算成修复。Dataset 的 `failure_count` 只统计任务异常，正常返回的失败诊断另由断言
和 workflow 完成数体现。`rescore.py` 仅重评保存的事实并另存 score-reviewed，保留
原报告和原评分，不调用模型或重放工具。

所有结果仅为隔离配置诊断修复盲测；未运行 ROS、实机复位、运动、生产服务或远端设备。
