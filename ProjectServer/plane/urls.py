# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""plane URL Configuration"""

from django.apps import apps
from django.conf import settings
from django.urls import include, path, re_path
from plane.quality.member_context import WorkspaceMemberContext
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

handler404 = "plane.app.views.error_404.custom_404_view"

from plane.knowledge.configuration import WorkspaceModelConfiguration

urlpatterns = [
    path("api/workspaces/<str:slug>/model-configuration/", WorkspaceModelConfiguration.as_view()),
    path("api/workspaces/<str:slug>/member-context/", WorkspaceMemberContext.as_view()),
    path("api/quality-auth/", include("plane.quality.auth_urls")),
    path("api/workspaces/<str:slug>/projects/<uuid:project_id>/knowledge/", include("plane.knowledge.urls")),
    path("api/workspaces/<str:slug>/projects/<uuid:project_id>/quality/", include("plane.quality.urls")),
    path("api/", include("plane.app.urls")),
    path("api/public/", include("plane.space.urls")),
    path("api/instances/", include("plane.license.urls")),
    path("api/v1/", include("plane.api.urls")),
    path("auth/", include("plane.authentication.urls")),
    path("", include("plane.web.urls")),
]

if settings.ENABLE_DRF_SPECTACULAR:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path(
            "api/schema/swagger-ui/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
        path(
            "api/schema/redoc/",
            SpectacularRedocView.as_view(url_name="schema"),
            name="redoc",
        ),
    ]

if settings.DEBUG and apps.is_installed("debug_toolbar"):
    try:
        import debug_toolbar

        urlpatterns = [re_path(r"^__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass
