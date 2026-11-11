# 三个独立交付包

运行环境镜像低频更新，业务更新使用代码部署包。一键入口在仓库根：

```bash
# 显式编译当前前端/协作产物，并生成三个独立包
./package-offline.sh --artifact all --build --output /absolute/output --version 2026.11.10
# 已有编译输出时不重建
./package-offline.sh --artifact code --output /absolute/output
# 只检查固定镜像、依赖指纹和模型，不导出
./package-offline.sh --artifact images --verify-only --output /absolute/check --model-dir /verified/model
```

`--artifact code|images|frp|all`，`--output` 必填且已有同名产物拒绝覆盖。未传版本时使用 UTC 时间与实际代码树摘要；没有 Git HEAD 写 null/unavailable，不伪造提交。`--build` 只适用于 code/all，执行 `pnpm install --frozen-lockfile` 和 `pnpm build:platform`；不会构建、拉取或发布 Docker 镜像。

- `EngramProject_code_<version>.tar.gz`：当前 `ProjectServer` 业务代码、`ProjectFront/build/client`、`services/collaboration/dist`、业务脚本、发布 Compose/安装入口和说明。只收白名单；后端 `plane/tests` 测试夹具、日志、私有文件、环境配置、数据库、缓存、模型权重与 symlink 不进入；业务 `test_resources.py` 和迁移文件保留。关键构建/安装文件缺失即失败。
- `EngramProject_images_<version>.tar.gz`：按 `runtime-manifest.json` 核对完整镜像引用、ID、平台及依赖文件指纹；一次 `docker save` 生成单个 images.tar，共享镜像层不重复保存。包含固定 SHA 模型文件，不带业务代码。
- `optional/frp/EngramProject_frp_<version>.tar.gz`：FRP 0.72.0 源码、模板、说明、许可证和已验二进制，固定官方 SHA；没有自动安装/启动行为，不打包活动 TOML 配置。

每包有 `version_info.json`、包根相对路径的 `SHA256SUMS`；外部另有归档 `.sha256`。代码树摘要来自实际收录文件字节，与 Git HEAD 无关。`--runtime-manifest` 可指定测试/其他已审核清单；依赖文件变更与运行时指纹不符会拒绝，须先准备匹配的低频运行镜像。工具不读取当前部署凭据，不导出主库或卷。

镜像包解压后：

```bash
./load_images.sh
# 同时将包内已校验模型放入部署根shared/models；不覆盖已存在的不同文件
./load_images.sh --deploy-root /absolute/platform-root
```

loader 先检查包内 SHA，再导入并验证声明镜像 ID/平台；不删除旧镜像或 tag。模型只在文件不存在时复制；已存在且不一致即拒绝并保留。镜像包和代码包是独立归档，`all` 只顺序生成，不互相嵌套。中途导出失败可能留下已成功产物，重试请用新的输出目录/版本，不会自动删除或覆盖它们。

新机建议显式指定 `--model-dir` 与 `--frp-bin-dir`。默认模型路径是当前用户 `Documents/tmp/artifacts/embedding-model-cache/bge-small-zh-v1.5`，缺文件不自动下载。FRP 默认指向本机已验交付目录，其他电脑须提供含 frpc/frps 的 bin 目录及其上级 FRP-LICENSE；同样不得跳过 SHA。

安装/启停与持久卷保护由本目录 `install.py`、`launcher.py` 和 `部署说明.md` 的独立合同管理；打包工具本身不部署、不迁移数据库、不触发模型或任何服务启动。完整安装验收另由集成流程确认，不能用打包成功代替业务运行通过。

回归：

```bash
python3 -m pytest deploy/release/test_package_release.py -q --basetemp=/absolute/artifacts/package-tests
```

测试使用真实文件和 tar，Docker 导出与镜像加载命令仅在合同用例中显式替身；真正镜像导出/目标安装需单列实际证据。
