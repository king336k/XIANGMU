# 五场景受控真实软件故障盲测

只操作新隔离容器与专用Secret项目FAULTLAB149。原DAQ镜像、networknone、8MiB tmpfs、512MiB内存上限；不填宿主磁盘、不连机器人、不部署195。实际异常使用原DAQ logger及validate_ros1_config。

controlled_faults.py只执行与观测；generate_controlled_faults.py将oracle放artifact/ground_truth.json。上传包仅system.log、environment.json、capture_manifest.json、runtime.json，不含oracle/observations或raw。run_real_faults.py不读取ground_truth，经5个独立Collector/task/Session及真实JWT/HMAC桥接提交中性标题与说明，并发2。禁止为提高结果透题或重复调用模型。

review_controlled_faults.py在模型完成后才读真值，保留逐案摘录、引用、tokens、人工可审阅判断和限制。每类仅1例，不能外推现场准确率。

本轮证据位于 /home/engram/Documents/tmp/artifacts/diagnostic-blind-faults-2026-11-09/。原5包不变。首版runtime误含still-running时Docker默认exit_code0；报告明确该值不适用。未来工具已改container_status与exit_code_if_exited，不重新上传改题。
