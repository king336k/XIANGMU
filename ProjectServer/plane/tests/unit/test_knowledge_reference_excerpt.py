from plane.knowledge.reference_excerpt import excerpt


def test_long_document_uses_matching_late_evidence_not_only_first_5000_characters():
    text="简介与一般环境。\n"*1000+"\n磁盘故障：ENOSPC，检查录制目录剩余空间与配额；清理后重新录制并核对输出。\n"+"结束说明。\n"*1000
    result=excerpt(text,"录制报错 ENOSPC 怎么检查磁盘",limit=5000)
    assert "ENOSPC" in result["content"] and "配额" in result["content"]
    assert len(result["content"])<=5000
    assert any(row["start"]>5000 for row in result["ranges"])
    for row in result["ranges"]: assert text[row["start"]:row["end"]] in result["content"]
    assert result["is_excerpt"] is True


def test_short_document_preserved_and_unmatched_document_is_explicit_excerpt():
    assert excerpt("短文", "查找")["content"]=="短文"
    result=excerpt("背景说明。"*3000,"ERR_UNKNOWN",limit=5000)
    assert result["is_excerpt"] and len(result["content"])<=5000
