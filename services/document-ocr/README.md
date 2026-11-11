# 本地文档OCR候选转写

只识别图中文字，不理解照片、流程图/表格语义或手写。Tesseract即使返回非空文字也可能有错；所有结果固定 `requires_review:true`，不能直接确认或发布知识。原件/图片不发送模型或远端OCR。

## 构建与运行

工具镜像为 `engramproject/document-ocr-runtime:163`（Tesseract5.5.0、chi_sim+eng、Poppler25.03.0）；构建不下载依赖：

```sh
docker build --pull=false --network=none -t engramproject/document-ocr:163 services/document-ocr
```

新机先构建工具层，再构建服务：

```sh
docker build -t engramproject/document-ocr-runtime:163 -f services/document-ocr/runtime.Dockerfile .
docker build -t engramproject/document-ocr:163 services/document-ocr
```

工具层使用 `runtime.Dockerfile` 的固定基础digest与包版本，也可使用经过校验的离线镜像。旧版本Debian包如仓库已撤下需从官方snapshot解析版本并重新验收，不能静默升级；本轮未重新执行apt或安装宿主依赖。

默认模板 `compose.yml` 为internal网络、无宿主端口、UID1000、只读root、drop ALL、no-new-privileges、2CPU/1GiB memory+swap合计/128PID、128MiB任务tmpfs。密钥由部署进程RAM环境注入（至少16字符），不写源码/报告/.env文件：

```sh
docker compose -f services/document-ocr/compose.yml up -d
```

平台API/worker应加入同一受控internal网络，服务根地址 `http://document-ocr:18886`，配置同一RAM环境密钥。不要挂Docker socket，不必发布公网端口。平台出站仍须exact origin allowlist和项目权限；这些由平台集成层处理。单独安全检查可 `docker run --network none ...`，再容器内loopback访问。

## 协议

- `GET /health`：只返回ready和公开limits，不需要key。
- `POST /v1/extract`：`Authorization: Bearer ...`、`Content-Type: application/octet-stream`、`Content-Length`、`X-Document-Type: pdf|docx|png`、`X-Content-SHA256: <64hex>`；body是原始文件，不接收路径/URL/动态语言参数。
- 最大20MiB、一次1任务，忙429；缺key401，SHA不符/类型/元数据400，过大413。禁用chunked传输，请求读超时15秒。
- 成功响应HTTP200：`{status:"completed",source_sha256,engine:"tesseract",segments:[{key,text,method:"ocr",page?,part?,paragraph?,source_image?,width,height}],failures:[],requires_review:true}`。`completed`表示本次尝试结束，**有failures或错字都不能当准确**；无文字保留failure，部分成功页不隐藏失败页。
- PDF全页渲染，物理页码；DOCX只支持内嵌PNG，保part/paragraph/image关系；独立PNG的source_image固定“原始PNG”，平台应绑定真实原文件名/SHA。JPEG未实测不支持。

固定chi_sim+eng/PSM6/200dpi，无默认重采样或自动猜词。每页15秒、整任务120秒、20页/图、单9M像素/累计60M、100000字符、输出JSON最多2MiB。原件仅写任务目录，结束清理；子进程硬AS768MiB/单文件32MiB/CPU120秒/64FD，外层容器继续限制。平台原严格DOCX/PDF安全解析应在出站前完成，本服务也拒绝加密PDF、危险ZIP路径/实体/外部图片关系等，OCR不能绕过原门禁。

## 验证

```sh
python -m unittest discover -s services/document-ocr -p test_http.py
```

守卫测试是真HTTP socket，但使用明确fake extraction检查协议/并发；本轮独立container实际OCR测试另见163/service/live-proof.json。真实错字PNG被保留为候选，不以非空保证准确。生产长期并发/SLO、JPEG、复杂版式、手写和图片语义不在本服务首版验收范围。

## 接入平台

使用平台主部署时，叠加 `platform.override.yml` 使API/普通worker和OCR服务加入同一内部网络，显式profile才启动服务：

```sh
docker compose --env-file deploy/local/.env -f docker-compose.yml -f services/document-ocr/platform.override.yml --profile document-ocr up -d
```

通过部署管理器或当前进程环境注入同一个 `DOCUMENT_OCR_API_KEY`，并为API/worker设置 `DOCUMENT_OCR_BASE_URL=http://document-ocr:18886`、`DOCUMENT_OCR_ALLOWED_HTTP_ORIGINS=http://document-ocr:18886`。不要把实际密钥提交源码。未配置服务时原文字导入行为保持，图片识别请求返回未配置。

网页在“文档与知识→导入知识草稿”选择PDF、DOCX或PNG，先预检，再按需“识别图片文字”。逐页对照原件修订候选、勾选已核对后“采用核对结果”，最后确认导入草稿；未识别范围仍存在时不能采用。识别完成不代表文字准确，也不自动发布知识。
