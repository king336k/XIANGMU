from plane.knowledge.reference_excerpt import excerpt


def test_long_document_uses_matching_late_evidence_not_only_first_5000_characters():
    text = (
        "简介与一般环境。\n" * 1000
        + "\n磁盘故障：ENOSPC，检查录制目录剩余空间与配额；清理后重新录制并核对输出。\n"
        + "结束说明。\n" * 1000
    )
    result = excerpt(text, "录制报错 ENOSPC 怎么检查磁盘", limit=5000)
    assert "ENOSPC" in result["content"] and "配额" in result["content"]
    assert len(result["content"]) <= 5000
    assert any(row["start"] > 5000 for row in result["ranges"])
    for row in result["ranges"]:
        assert text[row["start"] : row["end"]] in result["content"]
    assert result["is_excerpt"] is True


def test_short_document_preserved_and_unmatched_document_is_explicit_excerpt():
    assert excerpt("短文", "查找")["content"] == "短文"
    result = excerpt("背景说明。" * 3000, "ERR_UNKNOWN", limit=5000)
    assert result["is_excerpt"] and len(result["content"]) <= 5000


def test_matching_error_code_keeps_later_actionable_evidence_and_validation_context():
    text = (
        "通用背景说明。" * 400
        + "\n错误索引：topic_rate_too_low 表示有效频率未达标。\n"
        + "错误码分类说明。" * 200
        + "\n同一窗口的最小取证链：核对源发布频率、源时间戳、有效profile与Schema来源。\n"
        + "消费资源属于进一步只读补证建议：核对CPU、线程调度与队列等待。\n"
        + "验证标准：频率和新鲜度同时通过，保持原始证据。\n"
        + "一般附录。" * 500
    )
    result = excerpt(text, "topic_rate_too_low", limit=5000)
    assert "topic_rate_too_low" in result["content"]
    assert "源发布频率" in result["content"] and "消费资源" in result["content"]
    assert len(result["content"]) <= 5000
    for row in result["ranges"]:
        assert text[row["start"] : row["end"]] in result["content"]
