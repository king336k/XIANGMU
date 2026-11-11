"""Receiver facts and bounded human review context, separate from incident evidence."""
import re
from .diagnostic_materials import redact


def select_reviews(description, rows):
    def words(value):
        return set(re.findall(r'[a-z0-9_]{3,}', value.lower()) + re.findall(r'(?=([\u4e00-\u9fff]{2}))', value))
    current = words(description)
    selected = []
    for row in rows:
        note = row.get('feedback_note', '').strip()
        previous = words(row.get('description', ''))
        if not note or not current or not previous:
            continue
        score = len(current & previous) / max(1, len(current | previous))
        if score < 0.15:
            continue
        selected.append((score, {
            'reference': f"REVIEW-{row['id']}",
            'title': '历史人工评价（待结合本次证据复核）',
            'content': redact(f"评价：{row['feedback']}；说明：{note[:1000]}"),
        }))
    return [value for _, value in sorted(selected, key=lambda item: item[0], reverse=True)[:3]]


def diagnostic_context(job, report_only=False):
    from .models import DiagnosticJob, PackageFile
    from .daq_incidents import trusted_incident, signed_record
    from .deployment_snapshots import read_feedback
    from .views import Conflict

    defect = job.defect
    link = trusted_incident(defect)
    record = signed_record(link) if link else None
    files = list(PackageFile.objects.filter(project=job.project, package__defect=defect,
        package__status='files_verified').order_by('-created_at')[:100])
    components = 0
    for row in files:
        if row.name.startswith('feedback-') and row.name.endswith('.json'):
            try:
                snapshot = read_feedback(row)
                if snapshot:
                    components = len(snapshot['components'])
                    break
            except (ValueError, OSError, Conflict):
                pass
    receipt = {
        'defect': defect.code, 'source_received': record is not None,
        'collector': (record or {}).get('reporter', {}).get('username', ''),
        'session_reference': (record or {}).get('payload', {}).get('sourceReference', ''),
                'version_components': components,
        'boundary': '仅证明项目平台已接收并关联以上材料，不证明设备、遥操或录制本身无故障；与数据平台上传无关。',
    }
    receipt_text = f"记录：{receipt['defect']}\nDAQ 来源签名：{'已核验' if receipt['source_received'] else '无 DAQ 签名来源'}\n采集员：{receipt['collector'] or '未记录'}\nSession：{receipt['session_reference'] or '未关联'}\n已校验附件：{len(files)} 份\n版本组件：{components} 项\n" + '\n'.join(f"{row.name} · {row.size} 字节 · SHA256 {row.sha256}" for row in files) + '\n' + receipt['boundary']
    references = [{'reference': 'PLATFORM-RECEIPT', 'title': '本项目平台接收回执', 'content': receipt_text}]
    candidates = DiagnosticJob.objects.filter(project=job.project, status='completed',
        feedback__in=['helpful', 'unhelpful']).exclude(pk=job.pk).exclude(feedback_note='').order_by('-created_at')
    # Report-only collectors never gain another collector's report access.
    if report_only:
        candidates = candidates.filter(created_by_id=job.created_by_id)
    rows = []
    for previous in candidates.select_related('defect')[:30]:
        if not previous.result.get('feedback_review', {}).get('actor_id'):
            continue
        rows.append({'id': str(previous.id), 'feedback': previous.feedback, 'feedback_note': previous.feedback_note,
            'description': previous.defect.title + '\n' + previous.defect.description})
    references.extend(select_reviews(defect.title + '\n' + defect.description, rows))
    return references
