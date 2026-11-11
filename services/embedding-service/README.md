# 本地中文向量服务

独立提供 OpenAI 兼容的 `/v1/models`、`/v1/embeddings`。使用 BGE-small-zh-v1.5 的 ONNX Runtime CPU 编码器，不更改聊天模型。默认部署脚本只检查，显式 `--apply` 才创建服务或写平台配置。

## 平台默认内置连接（新安装入口）

平台内置BGE无需在页面填写向量URL、模型或密钥。首次安装由部署操作者运行：

```sh
# 已有已验离线模型和镜像：仅检查，不修改
python3 services/embedding-service/setup_platform.py --model-dir /your/verified/model
# 自动启动内置服务并把连接注入本平台API/worker/诊断进程
python3 services/embedding-service/setup_platform.py --apply --model-dir /your/verified/model
# 首次缺模型/镜像时，明确允许固定来源下载和一次镜像构建
python3 services/embedding-service/setup_platform.py --apply --download-model --build-image
```

默认模型cache在当前用户`Documents/tmp/artifacts/embedding-model-cache/bge-small-zh-v1.5/`；使用`model-manifest.json`固定revision/大小/SHA，已存在错哈希文件拒绝且不覆盖，只有下载完成校验后原子保存。普通`--apply`不会联网下载或构建；现有`start.sh`仍保持只启动已有服务、不编译/拉取的契约。

新入口自动包含`platform.override.yml`和embedding profile，服务DNS固定`builtin-embedding:18885`、无宿主端口、专用internal网络。重启包含内置能力的平台时继续用这个入口；只运行旧start.sh不会为已删除的内置服务补建连接。`--project-root`、`--project-name`、`--compose-file`（可重复）、`--env-file`、`--network`、`--api-services`可指定独立部署；默认平台服务为migrator/api/worker/beat-worker/diagnostic-worker。既有同名服务必须属于相同Compose project/service且镜像/模型挂载/网络匹配才复用key，不重建或旋转key。

随机key只在部署进程和容器环境，不打印、不写.env；只注入`KNOWLEDGE_BUILTIN_EMBEDDING_BASE_URL/API_KEY/MODEL`及专用allowlist，不写provider数据库、不修改聊天、mode或停用开关。已有external连接/显式关闭由平台配置优先级保留；部署结果`provider_verified:false`诚实表示脚本验证了内置health和环境注入，实际provider/索引验证由平台进行。

`--apply`会按本次Compose范围启动/必要时重建指定API进程以注入默认连接，应在安装/部署窗口运行；不会擅自接管其他项目容器。独立安装不支持一条setup命令修改现有原平台，其project/env必须由操作者选对。

## 手动运维与高级检查

以下保留原独立服务手动运维入口；普通平台用户无需填写这些连接字段。

### 在新电脑准备

1. 安装 Docker、Python 及现有 Docker SDK（`docker`）；平台 API、普通 worker、诊断 worker 应连接同一个自定义 Docker 网络。可用 `docker network ls` 查看实际网络名；脚本不会创建网络或把已有容器接入其他网络。
2. 在任意持久目录放置 `model.onnx` 和 `tokenizer.json`，确保容器 UID10001 可读。使用下列固定来源，文件名放在模型目录根层。无需复制本机实验目录，脚本不会自动下载模型或执行远端模型代码。
3. 在仓库根构建镜像：

```sh
docker build -t engramproject/embedding:bge-small-zh-v1.5 services/embedding-service
```

模型来源与启动 SHA256 校验：

| 文件 | 固定来源 | SHA256 |
| --- | --- | --- |
| `model.onnx`（94,851,877 B） | [Xenova，revision 75c43b069aac4d136ba6bc1122f995fedcfd2781，onnx/model.onnx](https://huggingface.co/Xenova/bge-small-zh-v1.5/tree/75c43b069aac4d136ba6bc1122f995fedcfd2781) | `69a0b846f4f116b5e6aabf9546ea6754d02264f3211a13a1bd69b31b8040749a` |
| `tokenizer.json` | [BAAI，revision 7999e1d3359715c523056ef9478215996d62a620](https://huggingface.co/BAAI/bge-small-zh-v1.5/tree/7999e1d3359715c523056ef9478215996d62a620) | `48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26` |

原模型按其 model card 为 MIT。原始和 ONNX 仓库 tokenizer git blob 相同；采用官方首个 `[CLS]` token 池化、512维、L2归一化，无隐藏检索前缀。启动脚本检查文件存在，服务启动时验证上述文件哈希。

## 检查与创建服务

以下路径和网络为示例，替换为新电脑实际值：

```sh
export EMBEDDING_MODEL_DIR=/srv/models/bge-small-zh-v1.5
export EMBEDDING_DOCKER_NETWORK=engramproject_default
export EMBEDDING_SERVICE_NAME=engramproject-embedding
python3 services/embedding-service/start_local.py
python3 services/embedding-service/start_local.py --apply
```

可用 `--model-dir`、`--network`、`--service-name` 覆盖环境变量。默认服务名 `engramproject-embedding`、网络 `engramproject_default`；模型目录必须提供。镜像可用 `--image` / `EMBEDDING_IMAGE`，宿主端口可用 `--host-port` / `EMBEDDING_HOST_PORT`，默认18885。Docker SDK 使用当前 Docker context/环境。

已存在的同名容器始终保留，不重建、不重启、不旋转密钥。若其镜像、模型或网络与预期不同，请选择新的服务名并核对；脚本不会自动替换。内部地址稳定使用 `http://<服务名>:18885/v1`，无需复制动态容器 IP。对宿主只绑定 `127.0.0.1:<宿主端口>`。

仅供平台容器内部访问时，两次启动命令都加 `--no-publish`，不发布宿主端口；此模式仍使用同一Docker网络DNS地址。

容器保持原限制：非root UID10001、只读根和模型、drop ALL capabilities、no-new-privileges、1GiB内存与swap合计、2CPU、128PIDs。生成的 bearer key 仅在容器环境和配置进程内存中，不打印或写入文件。

## 设置平台

平台部署环境应为 API、普通 worker、诊断 worker 设置同一明确来源：

```text
KNOWLEDGE_EMBEDDING_ALLOWED_HTTP_ORIGINS=http://engramproject-embedding:18885
```

服务名变更时同步此 origin；保留原 allowlist 内容，不覆盖其他有效来源。该设置要求平台版本支持 embedding 专用 allowlist 中的容器 DNS。脚本会检查实际校验器，版本不支持或未放行时直接失败。不要为此更改聊天模型 allowlist。

选择实际 API 容器，然后先验证，再应用：

```sh
export PLATFORM_API_CONTAINER=your-platform-api-container
python3 services/embedding-service/configure_platform.py
python3 services/embedding-service/configure_platform.py --apply
```

也可使用 `--api-container`、`--network`、`--service-name`；API与向量容器必须已连接所选网络。默认检查通过 API 容器真实请求两个固定中文短句，不写数据库；因此服务尚未ready时应稍后重试。`--apply` 仅更新 embedding URL/model/加密key 与 semantic enabled，全部写入和连通/二维512向量验证在同一数据库事务内；验证异常回滚。检查同时核对聊天配置指纹，保留已有聊天模型设置。输出只有公开回执，不保存任何配置证据文件或凭据。

`--apply` 成功后，其他工作进程须已有相同网络和 origin 环境。脚本不会修改、重启平台容器或调整其环境变量。重建向量服务会生成新key，需再次明确应用配置。

## 健康和限制

```sh
curl http://127.0.0.1:18885/health
```

健康接口不需要key、不返回key；模型和向量接口需要bearer。一个编码worker、2个CPU线程、1个并发；忙100ms返回429，ONNX执行15秒限时。每批1–16个非空文本、单文本最多1024字符且含特殊token最多512 tokens，超限400且不截断；请求体64KiB。只返回512维float，不记录请求正文或key。知识分块（含标题）建议小于400汉字，仍须处理明确token超限。

## 回归检查

```sh
python3 -m pytest services/embedding-service/test_deployment.py services/embedding-service/test_service.py -q --basetemp=/your/persistent/artifacts/embedding-pytest
```

部署测试使用真实临时文件路径、模拟Docker/子进程和事务感知内存数据库，明确不代表新电脑Docker实际运行、真实数据库回滚或真实ONNX数值验证。HTTP守卫测试使用假encoder；原实际ONNX数值行为不由这些测试代替。不要把相似度示例当作诊断准确率。

## 离线镜像依赖与代码分开交付

默认产物是低频依赖包（公开模型+可选embedding镜像），代码部署包独立。日常新业务只更新总平台部署包中的组件代码，不重打/重传95MB权重；本组件code应由总平台部署包收纳，不要求用户单独管理多个代码包。

```sh
# 默认只检查；dependencies需要已验模型目录
python3 services/embedding-service/package_offline.py --model-dir /your/verified/model
# 低频依赖包：仅模型、固定manifest、可选独立tag镜像
python3 services/embedding-service/package_offline.py --model-dir /your/verified/model --include-image --output /your/artifacts/embedding-dependencies.tar.gz
# 小代码包：仅固定白名单服务/部署源码，不含模型/镜像，也不读取权重
python3 services/embedding-service/package_offline.py --package-kind code --output /your/artifacts/embedding-code.tar.gz
```

显式新output才创建，已存在输出/错SHA模型/软链接拒绝且不覆盖；不递归读目录，不含.env/DB/key或用户材料。每包bundle-manifest.json独立size/SHA，镜像归档只带临时独立offline-export tag，docker load不覆盖原主tag。依赖包解压的models目录与总部署包内service/setup_platform.py组合使用，平台镜像与配置由目标部署提供。

这是**离线预置依赖验收**，不代表官方模型源在线冷下载已通过；不是全平台统一大包。所有产物只在显式持久目录，不使用系统/tmp。部署源最终freeze后才打正式code包，依赖包可长期复用。
