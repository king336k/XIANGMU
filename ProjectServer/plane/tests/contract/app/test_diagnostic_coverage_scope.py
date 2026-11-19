"""Unread verified attachments narrow overall semantic coverage, not source integrity."""
import pytest
from plane.quality.tasks import run_diagnostic
from plane.tests.contract.app.test_diagnostic_verified_subset import prepare

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.mark.parametrize('image_mode', ['unsupported_jpg', 'ocr_failed'])
def test_verified_log_with_unread_image_is_partial_without_blocking_analysis(workspace, create_user, settings, tmp_path, mocker, image_mode):
    job, add = prepare(workspace, create_user, settings, tmp_path, mocker)
    add(b'ERROR actual verified log fault\n', 'observed.log')
    image = add(b'\x89PNG\r\n\x1a\nfixture', 'screenshot.jpg' if image_mode=='unsupported_jpg' else 'screenshot.png')
    mocker.patch('plane.quality.diagnostic_image_text.extract_png', return_value={
        'status': 'unavailable', 'reason': 'ocr_unavailable', 'text': ''})
    model = mocker.patch('plane.quality.tasks.analyze_diagnostic', return_value={'answer': 'observed fault', 'citations': []})
    route = mocker.patch('plane.quality.module_routing.route_completed')
    severity = mocker.patch('plane.quality.diagnostic_severity_apply.apply_severity')
    run_diagnostic(job.id); job.refresh_from_db()
    assert model.call_count == 1
    config, text, _, references, _ = model.call_args.args
    assert config['analysis_scope']=='verified_read_subset'
    assert config['material_coverage']=='partial' and 'actual verified log fault' in text
    unread = next(row for row in config['partial_source_warning']['unread_sources'] if row['file_id']==str(image.id))
    assert unread['kind']=='image' and unread['status'] in {'not_read', 'unsupported'}
    assert unread['reason']
    assert any(row['reference']=='MATERIAL-COVERAGE' for row in references)
    assert job.result['semantic_scan_complete'] is False and job.result['material_coverage_status']=='partial'
    assert job.result['materials_status']=='partial' and job.result['integrity_verified'] is True
    assert job.result['repaired'] is False
    route.assert_not_called(); severity.assert_not_called()


def test_successful_ocr_text_marks_coverage_read_without_claiming_unread_image(workspace, create_user, settings, tmp_path, mocker):
    job, add = prepare(workspace, create_user, settings, tmp_path, mocker)
    add(b'ERROR actual verified log fault\n', 'observed.log')
    image=add(b'\x89PNG\r\n\x1a\nfixture', 'screenshot.png')
    mocker.patch('plane.quality.diagnostic_image_text.extract_png', return_value={
        'status': 'read', 'reason': '', 'text': 'ERROR image OCR text needs original review'})
    mocker.patch('plane.quality.tasks.analyze_diagnostic', return_value={'answer':'read sources', 'citations':[]})
    run_diagnostic(job.id); job.refresh_from_db()
    coverage=next(row for row in job.result['material_coverage'] if row['file_id']==str(image.id))
    assert coverage['status']=='analyzed' and coverage['semantic_scan_complete'] is True
    source=next(row for row in job.result['sources'] if row['file_id']==str(image.id))
    assert source['origin']=='image_ocr' and source['requires_review'] is True
    assert job.result['analysis_scope']=='full_evidence_scan'


def test_only_unsupported_image_still_does_not_invoke_model(workspace, create_user, settings, tmp_path, mocker):
    job, add = prepare(workspace, create_user, settings, tmp_path, mocker)
    add(b'fixture image', 'unsupported.jpg')
    model=mocker.patch('plane.quality.tasks.analyze_diagnostic')
    run_diagnostic(job.id);job.refresh_from_db()
    model.assert_not_called()
    assert job.result['model_status']=='materials_unsupported'
    assert job.result['semantic_scan_complete'] is False
    assert job.result['material_coverage_status']=='partial'
