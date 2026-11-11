# 其他部署方式

本目录保留 AIO、CLI、Kubernetes 和 Swarm 部署资源。

| 目录          | 内容                            |
| ------------- | ------------------------------- |
| `aio/`        | 一体化部署与对应镜像构建资源    |
| `cli/`        | 命令行安装、恢复和 Compose 资源 |
| `kubernetes/` | Kubernetes 部署资源             |
| `swarm/`      | Docker Swarm 部署资源           |

当前 EngramProject 的日常开发、隔离测试和发布入口位于 [deploy/](../deploy/README.md)。本目录中的 AIO、CLI 和 Swarm 路径仍被 [build-branch.yml](../.github/workflows/build-branch.yml) 引用，因此保留原路径；本次目录整理不代表这些部署方式已经重新验收。

修改或迁移此处资源时，应同时核对 `.github/workflows/` 的构建上下文、发布资产路径和安装脚本引用。各方式有独立的环境模板，使用前按目标环境核对配置。
