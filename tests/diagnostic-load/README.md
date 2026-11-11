# 独立诊断压力验收

仅用于已授权的本机验收环境：`16335` authority、`18880` 项目平台，独立 `LOAD149` 项目、`1491109` 上游项目及每次新建的采集员、任务、Session、数据包、缺陷。不会使用 `native140` 或 demo 登录，不修改模型/worker配置。凭据只在内存派生，不输出或写文件。测试数据保留供复核。

```bash
python tests/diagnostic-load/verify_load.py --count 2 --output /home/engram/Documents/tmp/artifacts/diagnostic-pressure-2026-11-09/baseline-2
python tests/diagnostic-load/verify_load.py --count 4 --output /home/engram/Documents/tmp/artifacts/diagnostic-pressure-2026-11-09/load-4
python tests/diagnostic-load/verify_load.py --count 10 --output /home/engram/Documents/tmp/artifacts/diagnostic-pressure-2026-11-09/load-10
```

每个客户端独立真实登录，完成上报和manifest后在屏障处等待，同时提交材料。记录每个模型任务的入队、启动、完成时间，区分排队、执行、HTTP可见终态；同时采样Docker内存/CPU。p50/p95采用线性插值，小样本仅描述本轮。

模型成功比例指 `model_status=completed`，不是诊断准确率。`model_usage`只含provider返回的数值计数，不代表账单金额；实际费用必须结合该provider当时价格/账单核对。失败任务可能已消耗token而无usage返回，必须报告未计量部分，不能按0费用处理。

每个诊断最多5次主Agent逻辑请求及1次兜底请求，每次请求的max_tokens为2500；SDK重试的实际HTTP次数不包含在逻辑请求上限中，不得把这个上限等同实际计费请求数。

隔离回归检查：

```bash
python tests/diagnostic-load/run_checks.py --output /home/engram/Documents/tmp/artifacts/diagnostic-pressure-2026-11-09/diagnostic-final-verified.log
```

复用测试容器的依赖但复制独立源码，显式改用 `test_diagnostic_pressure_149` 数据库和Redis DB14，禁止与另一压力回归进程同时运行此命令。不会访问共享默认测试数据库。

`verify_timeout.py`在diagnostic worker容器用Django解释器执行，启动回环地址的无响应provider，只对这一次函数调用传入合成配置，不修改全局模型设置。它验证runner/子进程真实时间边界且不产生外部模型费用。
