from plane.quality.diagnostic_context import select_reviews


def test_related_review_is_context_not_automatic_truth():
    rows = [{'id': 'old', 'feedback': 'unhelpful', 'feedback_note': '已收到附件，请核对接收回执', 'description': 'Galbot recording startup validation'}]
    result = select_reviews('Galbot recording startup validation', rows)
    assert result[0]['reference'] == 'REVIEW-old'
    assert '复核' in result[0]['title']
    assert '接收回执' in result[0]['content']


def test_unrelated_and_empty_reviews_are_excluded_and_context_bounded():
    assert not select_reviews('camera calibration', [{'id': 'old', 'feedback': 'helpful', 'feedback_note': 'ok', 'description': 'network upload failure'}])
    rows = [{'id': str(i), 'feedback': 'helpful', 'feedback_note': '正常验收' * 500, 'description': 'camera calibration'} for i in range(10)]
    result = select_reviews('camera calibration', rows)
    assert len(result) == 3
    assert all(len(row['content']) < 1100 for row in result)
