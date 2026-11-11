# 配套服务

本目录保存平台配套运行服务和迁移工具；可执行的跨平台验收工具集中在 [tests/](../tests/README.md)。

| 目录                                        | 职责                   |
| ------------------------------------------- | ---------------------- |
| `diagnostic-agent/`                         | 隔离运行的诊断 Agent   |
| `embedding-service/`                        | 中文知识向量服务       |
| `document-ocr/`                             | 可选的文字识别服务     |
| `collaboration/`                            | 实时文档协作           |
| `admin/`                                    | 实例管理界面           |
| `space/`                                    | 共享内容访问界面       |
| `proxy/`                                    | 网关                   |
| `knowledge-migration/`、`legacy-migration/` | 知识及历史数据迁移工具 |

需要数据库、模型、外部平台或迁移写入的工具，应按各目录说明选择明确的目标环境。普通启动使用根目录 `start.sh`；服务部署配置见 [deploy/](../deploy/README.md)。
