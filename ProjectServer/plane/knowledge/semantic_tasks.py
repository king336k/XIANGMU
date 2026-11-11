from celery import shared_task


@shared_task(name="plane.knowledge.build_semantic_index", soft_time_limit=115, time_limit=125)
def build_semantic_index(project_id, token):
    from .semantic import run_build

    return run_build(project_id, token)
