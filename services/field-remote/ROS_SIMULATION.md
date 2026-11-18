# 原生 ROS 2 隔离仿真验证

`ros_simulation.py` 运行在已有 ROS Humble 环境内，不修改现有 DAQ schema、启动配置或真实机器人节点。脚本只使用 Domain **173** 与 `/remote_diagnostic_sim/{command,telemetry,status}` 三个固定 `std_msgs/msg/String` topic；六个模拟关节目标绝对值不超过 0.025，不调用机器人驱动或执行电机指令。

## 真实运行环境探测

在195和177已经授权的 `engram-teleop-1` 容器内，source 既有 ROS Humble 环境，显式设置隔离 domain，然后探测：

```bash
export ROS_DOMAIN_ID=173
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
python3 /isolated/root/ros_simulation.py probe
```

probe 真实导入 `rclpy`、`std_msgs.msg`、`rosbag2_py`；ROS bag writer 插件查询 API 可用时返回实际注册插件。不把包可导入等同于 DDS 跨主机可达。

如果当前 environment 的 ROS_DOMAIN_ID 不等于173，脚本直接拒绝运行；必须用此次进程环境覆盖，不能修改真实机器人节点的共享配置。跨主机 DDS 还依赖既有容器网络、接口和组播配置，脚本不会擅自调整这些设置。

## 177 构造隔离故障

177专用目录内创建 `robot-config.json`，仅有三项布尔值：

```json
{ "telemetry_enabled": false, "accept_commands": true, "hardware_required": false }
```

```bash
python3 /isolated/root/ros_simulation.py robot --config /isolated/root/robot-config.json --duration 300
```

机器人角色订阅 command；每条命令重新读取配置。它只处理带 `simulation:true`、正整数 sequence 和六个有限有界 targets 的 JSON。`telemetry_enabled:false` 时命令已收到但不发遥测，status 仍定期发布配置、最后收到的 sequence 和 robot hostname。`accept_commands:false` 或 `hardware_required:true` 时拒绝处理命令。

配置格式错误、文件不可读时按需要现场介入的禁用状态处理，不恢复到默认正常配置。超时或退出后本脚本节点销毁，不处理任何既有真实节点。

## 195 实际采集与证据

```bash
python3 /isolated/root/ros_simulation.py collect \
  --duration 8 \
  --output /isolated/evidence/native-ros-roundtrip.jsonl \
  --bag /isolated/evidence/native-ros-before \
  --bag-storage auto
```

collector 等待 command 订阅发现，再反复发布相同 sequence。只有实际通过 rclpy 订阅收到 `transport:native_ros2`、相同 sequence、相同目标数组和177 hostname 的遥测时，才输出 `verified:true` 和退出码0；未收到匹配遥测则记录错误、status样本，退出码2。JSONL fsync 落盘且保留195/177 hostname、时间、sequence、topic和结果。文件上限10MiB，拒绝最终文件symlink/hardlink。

传 `--bag` 时使用真正的 `rosbag2_py.SequentialWriter`，记录实际发布命令和实际收到的匹配遥测，CDR序列化类型为 `std_msgs/msg/String`。bag目录必须不存在。auto 在插件探测确认 MCAP 可用时选择mcap，否则使用sqlite3；可明确 `--bag-storage mcap`，不可用时报告失败，不能以JSONL替代声称MCAP已写。结束时返回实际bag文件路径、大小、SHA256，需再用既有 `ros2 bag info` 或只读Reader检查topic/message计数。

故障状态下预期只有command、没有匹配telemetry。通过已批准的固定 `robot_peer.py repair --expected-sha256 ...` 修复177专用配置后，以新bag目录重复195 collect，预期同时有command与telemetry并且sequence一致。

`hardware_required:true` 无法通过同一软件repair清除；status可达时collector明确记录 `requires_onsite:true`。DDS完全不可达时只能报告未收遥测，不能据此推断具体硬件故障。

## 证据边界

脚本所有结果固定标记 `native_daq_verified:false`。JSONL是此次真实ROS收发的观察记录，rosbag2是本脚本对实际ROS消息的录制；二者都不自动证明现有 DAQ capture_service、业务采集流程、传感器或电机已验收。现有DAQ必须另行通过已授权采集入口录制这些隔离topic并核对其原生产物。

## 本机回归

```bash
python3 -m unittest discover -s services/field-remote/tests -v
python3 -m compileall -q services/field-remote/ros_simulation.py
```

标准库回归验证输入限幅、domain隔离、配置热读、遥测匹配与文件边界。主机无ROS时probe如实返回不可用；跨195/177 DDS与bag实物必须在真实ROS容器另外验证。
