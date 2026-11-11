# 诊断与检索离线回归基准

无需数据库、网络、新依赖或模型下载。所有内置样本、向量、输出都是明确标注的 synthetic fixture。它们验证评测机制，不代表 embedding 或现场故障诊断准确率。真实样本需人工审阅、脱敏并标为 `real`；真实组和合成组始终分别输出，不混合计数。

在仓库根目录运行：

```bash
python -m unittest discover -s tests/diagnostic-evaluation -p 'test_*.py'
python tests/diagnostic-evaluation/evaluate_retrieval.py --output /home/engram/Documents/tmp/artifacts/diagnostic-evaluation/retrieval-report.json
python tests/diagnostic-evaluation/evaluate_diagnostics.py --dataset tests/diagnostic-evaluation/synthetic-diagnostics.json --outputs tests/diagnostic-evaluation/synthetic-outputs.json --output /home/engram/Documents/tmp/artifacts/diagnostic-evaluation/diagnostic-report.json
```

检索报告分别记录关键词及向量 Recall@3/MRR@3、无答案拒答、项目/发布版本排除。诊断评测只读取显式提供的输出，检查必需现象/操作词、禁止敏感文本、引用白名单和拒答预期；未提供实际输出记 `missing_output`，不计为通过。真实效果应另用获准的脱敏现场样本和实际模型输出评估。
