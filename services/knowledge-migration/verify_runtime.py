"""Read public HTTP routes with short-lived verifier-issued Django sessions, no password reuse."""

import json
from importlib import import_module
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.conf import settings
from plane.db.models import Project, User
from plane.knowledge.models import Article

reviewer = User.objects.get(id="01238975-42ca-4a52-9e9a-6c0b45c03f6e")
outsider = User.objects.filter(is_active=True).exclude(id=reviewer.id).first()
checks = []


def get(url, cookie):
    request = Request(
        "http://proxy" + url, headers={"Cookie": cookie, "Host": "127.0.0.1:18880"}
    )
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, {}


for user, role in [(reviewer, "reviewer"), (outsider, "outsider")]:
    session = import_module(settings.SESSION_ENGINE).SessionStore()
    session["_auth_user_id"] = str(user.id)
    session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    session["_auth_user_hash"] = user.get_session_auth_hash()
    session.create()
    try:
        cookie = settings.SESSION_COOKIE_NAME + "=" + session.session_key
        for project in Project.objects.filter(
            workspace__slug__in=["knowledge-157-local", "knowledge-157-acceptance"]
        ):
            base = f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/knowledge/"
            article = Article.objects.filter(project=project).first()
            for endpoint in [
                "articles/",
                "search/?q=",
                "articles/" + str(article.id) + "/",
            ]:
                status, data = get(base + endpoint, cookie)
                expected = 200 if role == "reviewer" else 403
                assert status == expected, (role, endpoint, status)
                check = {
                    "role": role,
                    "workspace": project.workspace.slug,
                    "endpoint": endpoint,
                    "status": status,
                }
                if role == "reviewer" and endpoint == "search/?q=":
                    assert data["count"] == 0
                    check["count"] = data["count"]
                if role == "reviewer" and endpoint == "articles/":
                    assert (
                        data["count"] == Article.objects.filter(project=project).count()
                    )
                    check["count"] = data["count"]
                if (
                    role == "reviewer"
                    and endpoint.startswith("articles/")
                    and endpoint != "articles/"
                ):
                    assert data["status"] == "draft" and not data["publication_active"]
                    assert (
                        data["source_defect_id"] is None
                        and data["source_regression_id"] is None
                    )
                checks.append(check)
    finally:
        session.delete()
print(
    json.dumps(
        {
            "authentication": "verifier-issued short-lived native Django session; no source login/password",
            "checks": checks,
        },
        ensure_ascii=False,
    )
)
