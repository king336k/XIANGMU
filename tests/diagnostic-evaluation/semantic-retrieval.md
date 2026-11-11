# 可选语义检索

默认关闭。复用知识模型连接的加密密钥、base URL 和服务器目的地白名单。实例管理员在 `/knowledge/configuration/` 设置 `semantic_enabled`、`embedding_model`；聊天模型不会自动作为向量模型。

项目知识审核管理员显式 `POST /knowledge/semantic-index/ {"action":"build"}` 后，该项目才加入索引范围。GET读取 `eligible_count/indexed_count/status/error_code/can_build` 安全元数据。任务使用既有 Celery worker、PostgreSQL JSON向量及标准库cosine，检索与索引复用既有组件；独立Embedding服务见 `services/embedding-service/README.md`。每次128篇当前版本、256片、每片350字符、每批16片、约90秒应用预算；超限明确失败，不默默截断。内容摘要复用索引，任务token和发布快照摘要使重复及过期任务失效。

只索引当前项目有效发布版本。敏感扫描、发起人审核权限及发布状态均在出站前检查；未主动加入的项目不自动发送内容。撤销、换版、项目边界及连接/模型指纹在检索时重新过滤。失败索引不参与语义召回。原关键词literal命中全部保留并优先排列；禁用、缺配置、provider异常等均回退关键词。

早期聊天接口未提供可确认的Embedding模型，因此采用独立BGE-small-zh-v1.5 ONNX CPU服务。本机已部署并验证真实向量；后续V06在独立PostgreSQL和内部Docker网络完成40项真实配置、回滚、DNS检索与三进程读回检查，原服务配置保持不变。现场标注召回率/诊断准确率仍未建立，不把向量相似度当正确率。完整证据见 `/home/engram/Documents/tmp/artifacts/project-hub-followup-160-2026-11-10/embedding-real-isolated/report.md`。
