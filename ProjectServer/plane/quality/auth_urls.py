# SPDX-License-Identifier: AGPL-3.0-only
from django.urls import path
from .account_management import AccountDirectory, AccountProjectMembers, NativeWorkAccess
from .data_accounts import AccountSecurity
from .daq_reporting import (
    DaqProjectOptions,
    DaqReports,
    DaqOwnReportDetail,
    DaqOwnReportPackages,
    DaqOwnReportFiles,
    DaqOwnReportDownload,
)
from .unified_login import UnifiedLogin
from .daq_project_grants import DaqProjectGrants
from .number_lookup import NumberLookup
from .personal_todos import PersonalTodos
from .connection_settings import GlobalConnectionSettings
from .member_scopes import MemberScopes

urlpatterns = [
    path("daq-project-grants/", DaqProjectGrants.as_view()),
    path("my-todos/", PersonalTodos.as_view()),
    path("record-number/", NumberLookup.as_view()),
    path("login/", UnifiedLogin.as_view()),
    path("work-access/", NativeWorkAccess.as_view()),
    path("connections/", GlobalConnectionSettings.as_view()),
    path("member-scopes/<uuid:user_id>/", MemberScopes.as_view()),
    path("daq-project-options/", DaqProjectOptions.as_view()),
    path("daq-reports/", DaqReports.as_view()),
    path("daq-reports/<uuid:report_id>/", DaqOwnReportDetail.as_view()),
    path("daq-reports/<uuid:report_id>/packages/", DaqOwnReportPackages.as_view()),
    path("daq-reports/<uuid:report_id>/packages/<uuid:package_id>/files/", DaqOwnReportFiles.as_view()),
    path("daq-reports/<uuid:report_id>/files/<uuid:file_id>/", DaqOwnReportDownload.as_view()),
    path("daq-reports/<uuid:report_id>/files/<uuid:file_id>/<str:action>/", DaqOwnReportDownload.as_view()),
    path("accounts/", AccountDirectory.as_view()),
    path("accounts/<slug:workspace_slug>/projects/<uuid:project_id>/members/", AccountProjectMembers.as_view()),
    path("account-security/", AccountSecurity.as_view()),
]
