from plane.quality.diagnostic_context import select_reviews


def test_related_review_is_context_not_automatic_truth():
    rows = [
        {
            "id": "old",
            "defect_id": "current",
            "feedback": "unhelpful",
            "feedback_note": "已收到附件，请核对接收回执",
            "description": "Galbot recording startup validation",
        }
    ]
    result = select_reviews(rows, defect_id="current")
    assert result[0]["reference"] == "REVIEW-old"
    assert "复核" in result[0]["title"]
    assert "接收回执" in result[0]["content"]


def test_unrelated_and_empty_reviews_are_excluded_and_context_bounded():
    assert not select_reviews(
        [{"id": "old", "feedback": "helpful", "feedback_note": "ok", "description": "network upload failure"}],
        defect_id="current",
    )
    rows = [
        {
            "id": str(i),
            "defect_id": "current",
            "feedback": "helpful",
            "feedback_note": "正常验收" * 500,
            "description": "camera calibration",
        }
        for i in range(10)
    ]
    result = select_reviews(rows, defect_id="current")
    assert len(result) == 3
    assert all(len(row["content"]) < 1100 for row in result)


def test_shared_report_template_does_not_make_different_faults_related():
    description = "测试诊断1212压力 synthetic replay 请依据附件观测诊断，缺失事实保持未验证"
    rows = [
        {
            "id": "budget-job",
            "defect_id": "budget-defect",
            "feedback": "unhelpful",
            "feedback_note": "核对父预算与 journal 预留",
            "description": description,
            "sources": [{"excerpt": "ERROR storage_quota_exceeded limit=12 used=13"}],
        }
    ]
    assert not select_reviews(rows, defect_id="current")


def test_no_review_is_selected_from_only_generic_failure_words():
    rows = [
        {
            "id": "old",
            "defect_id": "other",
            "feedback": "unhelpful",
            "feedback_note": "不要照搬旧结论",
            "description": "error timeout connection failed",
            "sources": [{"excerpt": "ERROR timeout connection failed"}],
        }
    ]
    assert not select_reviews(rows, defect_id="current")


def inspected(line):
    return [
        {
            "file_id": "verified",
            "sha256": "a" * 64,
            "scan_incomplete": False,
            "preview_truncated": False,
            "excerpt": line,
        }
    ]


def test_matching_verified_native_fault_reuses_feedback_with_different_template():
    row = {
        "id": "old",
        "defect_id": "other",
        "feedback": "unhelpful",
        "feedback_note": "核对父预算",
        "description": "旧标题",
        "sources": inspected("ERROR storage_quota_exceeded limit=12 used=13"),
    }
    refs = select_reviews(
        [row], defect_id="current", sources=inspected("ERROR storage_quota_exceeded limit=100 used=101")
    )
    assert refs[0]["reference"] == "REVIEW-old"


def test_same_defect_feedback_survives_changed_description_and_missing_source():
    rows = [
        {
            "id": "old",
            "defect_id": "same",
            "feedback": "unhelpful",
            "feedback_note": "补充实际配置来源",
            "description": "旧标题",
        }
    ]
    assert select_reviews(rows, defect_id="same")[0]["reference"] == "REVIEW-old"


def test_cross_defect_requires_verified_specific_fault_not_metadata_or_healthy_text():
    current = inspected("ERROR invalid video_input_mode custom_fixture galbot")
    for old in [
        inspected("ERROR storage_quota_exceeded limit=12"),
        inspected("INFO no errors invalid video_input_mode custom_fixture galbot"),
        [{"excerpt": "ERROR invalid video_input_mode custom_fixture galbot"}],
        [{**current[0], "scan_incomplete": True}],
        inspected("ERROR timeout connection failed"),
    ]:
        rows = [
            {
                "id": "old",
                "defect_id": "other",
                "feedback": "unhelpful",
                "feedback_note": "旧评价",
                "description": "相同模板",
                "sources": old,
            }
        ]
        assert not select_reviews(rows, defect_id="current", sources=current)


def test_negated_history_and_aggregate_failure_codes_do_not_reuse_foreign_reviews():
    row = {"id": "old", "defect_id": "other", "feedback": "unhelpful", "feedback_note": "旧评价"}
    for prefix in ["已确认不存在", "historical", "example", "未出现", "previous"]:
        old = {**row, "sources": inspected("ERROR " + prefix + " invalid video_input_mode custom_fixture galbot")}
        assert not select_reviews(
            [old], defect_id="current", sources=inspected("ERROR invalid video_input_mode custom_fixture galbot")
        )
    old = {**row, "sources": inspected("ERROR failure_class=raw_failed MCAP write failed")}
    assert not select_reviews(
        [old], defect_id="current", sources=inspected("ERROR failure_class=raw_failed raw accounting type invalid")
    )
