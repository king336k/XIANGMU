# 验证工具

本目录保存跨平台联调、离线评测和压力验收工具。应用单元与契约测试继续随模块维护：前端在 `ProjectFront/tests/`，后端在 `ProjectServer/plane/tests/`；[后端测试指南](../ProjectServer/tests/RUNNING_TESTS.md)包含隔离数据库的执行方法。

| 目录                                                      | 用途                                                           | 执行环境                       |
| --------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------ |
| `bridge-validation/`                                      | 数据平台与项目平台的身份桥接、分块材料、来源回读及问题闭环验证 | 专用联调容器和隔离测试项目     |
| `daq-validation/`                                         | DAQ 运行探针与采集故障验证，含验证镜像 Dockerfile              | 配套 DAQ / ROS 容器            |
| [diagnostic-evaluation/](diagnostic-evaluation/README.md) | 诊断与检索离线基准、受控故障材料及闭环检查                     | 离线样本或显式指定的联调环境   |
| [diagnostic-load/](diagnostic-load/README.md)             | 诊断排队、超时及并发压力验收                                   | 专用验收容器、项目和测试数据库 |

## 离线入口

从仓库根目录执行：

```bash
python3 -m unittest discover -s tests/diagnostic-evaluation -p 'test_*.py'
```

该检查使用合成样本，不连接业务平台。真实闭环和压力工具会创建测试数据或操作专用容器；执行前按各目录说明核对目标环境，不能把整个目录作为无副作用测试集批量运行。

工具由 `services/` 迁入本目录，脚本之间的相对层级保持不变。外部验收脚本如引用旧路径，应将 `services/<验证目录>/` 更新为 `tests/<验证目录>/`。构建 DAQ 验证镜像时使用 `tests/daq-validation/Dockerfile.capture-test`；Java 桥接验证的 `BRIDGE_VERIFICATION_JAVA` 指向 `tests/bridge-validation/java` 的绝对路径。

测试报告、诊断包和现场输出应写到命令显式指定的产物目录，不写入源码目录或系统 `/tmp`。报告须区分合成检查与真实现场验证。
