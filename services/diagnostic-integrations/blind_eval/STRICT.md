# 原始证据与模型提交内容的严格评测

`run_strict.py` 使用 Pydantic Evals 2.66.0 运行真实 `remote_runner.analyze`。
默认只运行一个已认可基线案例，模型执行限时 295 秒，SDK task 限时 305 秒。
`--case candidate` 为仅发布候选，`--case both` 顺序运行两者；
`--fault limit|type|dimension` 可选择故障类别，实际组和索引仍随机。

本模式中 inspect 不返回语义 validator findings、建议变更、正确替换值或评分目标。
它只提供原始节点日志、通用只读根、文件索引和实际源码目录。模型需通过 read_file
读取当前 YAML、原始基线 YAML、manifest 及故障前设备批准记录，自己比较数值、
类型、维度和限位。list_source_paths/read_source/search_source 提供实际仓库原文，
不提供合成修复步骤。基线原文属于可读取证据，不能据此推断缺少设备批准的值可用。

修复工具为 patch_file：模型必须提交当前文件实际 SHA256 和完整候选 YAML。
执行端独立解析模型内容，拒绝安全限位变化、合法定制值变化、未经批准的字段、
无效候选、错误基线值、身份/快照或授权变化。模型提交内容决定写入值；执行端不会
将错误提案偷偷替换为基线正确值，也不读取 hidden oracle 生成 patch。
实际写入仍仅为隔离持久 override，并执行仓库真实 overlay、读回验证。

授权案例使用故障前独立认可的 fixture 快照，随机故障选择发生在其后；这只是
隔离设备执行策略模拟。没有认可来源的案例禁止写入，要求模型说明未知正确值。
隐藏目标只由 scorer 使用。原文件保留、修改回执、模型提交内容和完整工具轨迹
另存以供检查，不能把自动 validator 结果混称为模型定位。

运行配置仍从 stdin 输入内存，不落盘。`--selfcheck` 只验证 SDK 和原始 patch
适配器，并明确 `model_called=false`；它的候选由测试代码给出，不能当作模型盲测。
真实运行的 evidence 目录含 model-report、actual-tool-trajectory、model-patch-receipts、
score 和 Pydantic Evals 报告。全部评测使用隔离文件，无生产或机器人复位操作。
