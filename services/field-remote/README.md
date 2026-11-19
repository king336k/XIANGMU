# 独立现场远程连接器与机器人仿真

仅依赖 Linux/Python 3 标准库，不启动旧 DAQ，不导入 ROS，不连接电机。`connector.py` 从采集机主动 HTTP 轮询中央服务；人类终端是真实主机 PTY，中央 Agent 使用独立 `run/read_file/patch_file` 工具。

## 边界

- 以当前普通用户运行。人类 PTY 提供该用户完整 shell 权限，可按既有 SSH 授权进入 177；工具 argv 策略并非 OS 沙箱，必须审核每个允许程序本身的能力。
- `approved_root` 必须是专用、仅放非敏感仿真文件的目录。文件工具拒绝绝对路径、`..`、symlink、hardlink、非普通文件、常见凭据名称及 `.field-*` 客户端内部文件；单文件上限 128 KiB。未知文件名下的秘密不能靠名称识别，不应放进此目录。
- `editable_files` 是必需的显式可编辑相对文件名白名单；省略即禁止全部补丁。195 示例只允许 `collector-config.json`，不能修改 connector、robot_peer、策略、SSH设置或其它脚本。177固定 helper只允许修复 `robot-config.json`。常见代码扩展名不能加入 editable_files。
- `allowed_commands` 是精确 argv 前缀列表，默认不允许任何工具。必须用绝对 executable 路径；不允许 shell、sudo、ssh 或 env；解释器必须固定批准根目录内的脚本，不允许 `-c`。额外参数中 `..` 和根目录外的绝对文件路径被拒绝。应把前缀收紧到固定脚本及 operation。
- `run` 无 shell 拼接，限时 60 秒（推荐服务端 15 秒），stdout/stderr 各最多 64 KiB，超时、完成或客户端退出清理进程组。run 在单独工作线程中执行，不阻塞人类 PTY。
- PTY 限制 2 个会话、4096 字节单次输入、5 分钟输入空闲、1 小时寿命、30 秒中央服务断连；退出清理进程组。终端输出最多约 512 KiB 待确认内存，满后对 PTY 施加背压；不会写终端日志。SIGINT/SIGTERM 清理，SIGKILL/主机断电无法执行用户态清理。
- PTY 子进程移除 token/secret/password/API_KEY 环境变量。工具同样移除，但显式保留仅用于机器人仿真认证的 `FIELD_SIM_TOKEN`。客户端 enrollment token 在启动时从环境取出，不传给任何子进程。
- 每个命令必须有 `id` 和未过期的 Unix 秒 `expires_at`。相同 ID 不重执行，返回缓存结果。run/patch 在执行前 fsync mode600 `.field-remote-state.json` 非敏感执行墓碑；不存参数、文件内容或 stdout/stderr。重启后的重复命令返回 `recovered:true` 与结果状态，不重执行。崩溃时状态可能表示未确认失败，需要新 ID 重新检查真实结果。
- 每条 terminal output 有稳定 UUID `id`，服务端应按 device+id 去重；每条 command（包括 terminal input/resize）均有 result。HTTP 成功且响应结构有效即确认整批 outputs/results；请求超时/响应失败时保留原批重传。服务端须幂等接收结果，并忽略已经完成命令的 recovered/重复结果。
- 补丁须提供原内容 `expected_sha256`，先生成 mode600 原文件备份，再 fsync/atomic replace。根目录只能由受信任当前用户写入；SHA 条件检查不能替代与外部写入者的事务锁。每个根目录仅允许一个 connector 实例。

## 部署到 195 和 177（需操作者明确授权后执行）

在 195 创建专用目录，将 `collector_sim.py` 复制进去，将 `collector-config.example.json` 改名为 `collector-config.json`。`robot_host` 必须改成真实 177 私网 IP；示例故意使用错误端口 18778，正常端口 18777。`policy.example.json` 中 approved_root 和脚本 argv 必须同步改为该目录。策略不包含任何凭据。

177 用已批准的 SSH 或真实 PTY 启动独立仿真服务，不能覆盖现有采集程序或占用其端口：

```bash
python3 robot_sim.py --bind <177_PRIVATE_IP> --port 18777
```

非 loopback bind 必须有 token，从 `FIELD_SIM_TOKEN` 环境读取或通过隐藏终端提示输入，不接受 token 命令行参数。195 的采集工具需要通过现有安全渠道在环境中提供相同 `FIELD_SIM_TOKEN`。不把 token 写入 JSON、脚本、日志或任务产物。默认不支持公共地址、0.0.0.0、DNS 域名、重定向或电机接口。

195 启动 connector；`FIELD_REMOTE_TOKEN` 从已存在环境读取，缺失时隐藏提示输入。后台服务启动应通过已有凭据管理器注入环境：

```bash
python3 connector.py --server https://central.example --policy /approved/path/policy.json
```

中央仿真服务使用已授权私网 HTTP 时显式加 `--allow-http`（同义 `--allow-http-private-lan`）；默认仅 HTTPS。HTTP 仅允许 literal private/loopback IP，不能使用 0.0.0.0 或公开地址。Authorization 为 `Bearer rw_<secret>`，不使用登录 Cookie，不接受重定向，不读取代理环境。

用户指定的公网 HTTP 测试入口须单独显式开启：

```bash
python3 connector.py --server http://180.153.172.19:18886 --policy /approved/path/policy.json --allow-insecure-public-http
```

该独立开关只接受 literal public IP，拒绝域名、loopback、multicast 和 unspecified 地址；不会扩大 `--allow-http` 私网开关的含义。公网 HTTP 会明文传输 enrollment token、终端数据和工具结果，仅用于用户明确指定的当前测试，不能作为生产默认。默认 HTTPS 仍开启证书验证；凭据仍仅来自既有安全环境或隐藏输入，不放入命令行。

## 中央工具验收顺序

1. `run` 固定 argv `python3 <approved-root>/collector_sim.py inspect`；结果包含 configured/expected port、SHA256、连通状态和 collector hostname。
2. `read_file collector-config.json` 获取当前内容与 SHA256。
3. `patch_file` 仅修正 `robot_port` 为预期值，传当前 `expected_sha256` 和完整新内容，保留返回的 backup 路径。
4. `run` 固定 argv `python3 <approved-root>/collector_sim.py verify`。该工具先验证远程 `/health` 的 `service=field-robot-sim`，然后发送 6 个幅度不超过 0.02 的模拟 joint target；要求 command ack、遥测 sequence 和 targets 一致，再 fsync 写入 195 的 `simulation-records.jsonl`。
5. 留存返回的 sequence、record SHA256 和双方 hostname/IP，独立检查 JSONL。此闭环证明仿真网络与本地落盘；不代表电机、ROS、旧 DAQ 或实体机器人采集验收。

JSONL 上限 10 MiB，达到后由现场操作者归档轮转；工具不会自动删除历史证据。

## 195 经 SSH 修复 177 的隔离异常

将 `robot_peer.py`、`connector.py`、`collector_sim.py` 复制到两端专用根目录。177 同时有 `robot_sim.py` 与 `robot-config.json`（从 `robot-config.example.json` 复制）；以 `robot_sim.py --config /isolated/root/robot-config.json` 启动，其他 bind/port/token 参数同上。

该配置只包含 `telemetry_enabled`、`accept_commands`、`hardware_required` 三个布尔值。服务每次请求热读；`telemetry_enabled:false` 可构造“控制有确认但遥测不返回”，`accept_commands:false` 可构造拒收命令，`hardware_required:true` 表示软件补丁无效、必须现场操作。`GET /status` 提供这些仿真状态，仍需要仿真 token。

195 创建 `robot-peer.json`（按示例配置 literal private host、username、ssh_key 路径、known_hosts 路径和177 remote_root）。凭据仅使用操作者明确配置的专用测试 key，工具不会读取或输出其内容。StrictHostKeyChecking、BatchMode、IdentitiesOnly 固定开启，禁用密码交互和伪终端，不执行 Agent 传入的任意远程命令。

只批准固定脚本及 operation：

```json
[
  ["/usr/bin/python3", "/approved/195/root/robot_peer.py", "inspect"],
  ["/usr/bin/python3", "/approved/195/root/robot_peer.py", "repair"],
  ["/usr/bin/python3", "/approved/195/root/robot_peer.py", "verify"]
]
```

每次 run 的额外参数为 `--root /approved/195/root`。先 `inspect` 获取177故障配置 `config_sha256`，再 `repair --expected-sha256 <64hex>`。SSH 调用的远程 helper 只允许读写固定 `robot-config.json`，repair 只把 `telemetry_enabled/accept_commands` 设为 true，保留 hardware_required；写前检查 SHA256 并备份。第三步 `verify` 先用 SSH 再检查177状态，再从195调用 HTTP command/telemetry 并写195 JSONL。

自主工具拒绝 `--remote`，并要求 `--root` 与 approved_root 完全一致。`robot_peer.py` 只接受 `inspect|repair|verify --root <fixed-root>`，repair 仅可再跟 `--expected-sha256 <64hex>`，不能追加其它开关、重复 root 或指定子目录。`collector_sim.py` 同样只接受 inspect/verify 及可选固定 root。

检测到 `hardware_required:true`，inspect/repair/verify 返回 `requires_onsite:true`；repair 不写文件，CLI 退出码2。中央 Agent 应向用户说明需现场介入，不能声称软件修复成功。此固定 SSH 工具只用于隔离仿真，与人类平台终端中手动 SSH177 的权限互不替代。

## ROSA / RAI / Holmes 接入

客户端没有伪造 ready 状态，也不会给中央 Agent 开放 `docker exec`。可以把实际 `specialist.py` 及依赖部署到独立 approved_root，并仅批准如下固定前缀（每个 operation 分别列项）：

```json
["/usr/bin/python3", "/approved/root/specialist.py", "rosa", "health"]
```

`rai/holmes`、`health/inspect` 同理。实际能力由该集成适配器检查 import、ROS 环境和可用工具；195 主机没有 ROS、现有 teleop 容器有 ROS 时，只有把适配器明确部署到已授权运行环境并通过专用固定桥接程序后才可报告可用。本目录不负责部署 ROS、修改 teleop 容器或开放广泛 shell 命令。

## 本地回归

```bash
python3 -m unittest discover -s services/field-remote/tests -v
python3 -m compileall -q services/field-remote
```

测试仅使用临时专用目录、loopback HTTP 和主机 PTY，不触碰现有 DAQ 或机器人。测试临时目录创建在 `/home/engram/Documents/tmp/artifacts/field-remote-tests-20261118/`。

## 自动实时通道

DAQ 包内置 `station_stream.py` 和 websocket-client 1.8.0 的原版 Python 源码（Apache-2.0，许可及逐文件校验见 vendor/）。现场用户无需 pip、WebSocket 地址或端口配置；沿用平台 URL 和用户配置目录中的设备凭据，由 launch_web.sh 自动安装、登录后启动。客户端仅主动向平台的同源 /api/quality-auth/remote-diagnostics/station-stream/ 连接，不监听现场入站端口。无浏览器 Origin 的设备凭据鉴权与网页登录 Cookie 独立。

小窗口最多4批未确认输出、消息序号及原引擎命令ID去重、连接中断时保留未确认字节并回退 HTTP。原设备/项目权限、目标机器人版本和执行策略仍由平台与现场校验。当前通道模式及最近往返耗时在设备能力中提供，不把握手成功当作性能验收通过。
