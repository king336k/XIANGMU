# 当前部署入口

本目录维护 EngramProject 当前构建、部署、发布和隔离测试配置。

| 目录或入口                                          | 职责                                                              |
| --------------------------------------------------- | ----------------------------------------------------------------- |
| `build.sh`                                          | 生成当前平台的本机镜像，构建与启动分开                            |
| `local/`                                            | 根目录 `docker-compose.yml` 使用的 Dockerfile、网关配置及环境模板 |
| `dev/`                                              | 开发环境 Compose 配置                                             |
| `test/`                                             | 后端隔离测试 Compose 配置                                         |
| [release/](release/部署说明.md)                     | 业务包、运行镜像包、安装升级和日志交付                            |
| [network/frp-bridge/](network/frp-bridge/README.md) | 可选的受限网络连接包                                              |

从仓库根目录使用 `./deploy/build.sh` 构建，使用 `./start.sh` 启动现有制品，使用 `./stop.sh` 停止服务。发布包通过 `./package-offline.sh` 生成。参数和环境准备以[根目录说明](../README.md)及[发布部署说明](release/部署说明.md)为准。

`deployments/` 维护其他部署方式，仍有 CI 工作流引用其中的路径，见其[目录说明](../deployments/README.md)。新增当前产品部署能力优先放入本目录；涉及其他部署方式时同步核对对应工作流。
