# SPDX-License-Identifier: AGPL-3.0-only
from django.urls import path
from . import attachments, requirements, discussion
from .attachment_archive import DefectAttachmentArchive
from .roles import RoleList, RolePolicy
from . import views, plans
from .team import DefectTeam
from .collaboration_admin import ProjectCollaborationSettings, DefectRouting, DefectReminders
from .diagnostics import DiagnosticList, DiagnosticDetail
from .owner_statistics import OwnerStatistics
from .deployment_snapshots import DefectDeploymentSnapshots
from .resources import (
    FieldAgents,
    FieldAgentDetail,
    FieldHeartbeat,
    TelemetryReview,
    FieldAgentClient,
    FieldAgentCredential,
    FieldAgentInstallPackage,
)
from .saved_views import SavedViews, SavedViewDetail
from .bulk import BulkActions
from .triage import DefectDisposition
from .connection_settings import ConnectionSettings, FeishuConnectionOptions
from .document_imports import DocumentImports, DocumentConfirm, FeishuDocumentImport, DocumentFileDownload
from .document_ocr import DocumentOcr, DocumentOcrReview
from .test_resources import TestResources, TestResourceDetail, Preflight, PlanResources
from .report_delivery import NotificationTargets, NotificationTargetDetail, ReportDeliveries, ReportDeliverySend
from .native_policy import NativeIssuePolicy
from .case_picker import CaseOptions
from .work_item_kinds import WorkItemKinds
from .task_packages import TaskPackages, TaskPackageConfirm
from .statistics import DefectStatistics
from .project_report import ProjectPeriodReport
from .record_progress import RecordProgress
from .project_versions import (
    ProjectVersions,
    ProjectVersionDetail,
    ProjectVersionWorkflow,
    ProjectVersionSync,
    ProjectVersionOptions,
)
from .workflow import PlanWorkflow
from .work_item_options import WorkItemOptions
from . import solutions
from . import assets
from . import sources, reports, imports
from .defect_verification import (
    DefectVerification,
    DefectVerificationResult,
    DefectVerificationWorkflow,
    DefectVerificationResults,
)

urlpatterns = [
    path("owner-statistics/", OwnerStatistics.as_view()),
    path("defects/<uuid:pk>/reassign/", views.DefectReassign.as_view()),
    path("verification-results/", DefectVerificationResults.as_view()),
    path("defects/<uuid:pk>/verification/", DefectVerification.as_view()),
    path("defects/<uuid:pk>/verification/result/", DefectVerificationResult.as_view()),
    path("defects/<uuid:pk>/verification/workflow/", DefectVerificationWorkflow.as_view()),
    path("collaboration-settings/", ProjectCollaborationSettings.as_view()),
    path("defects/<uuid:pk>/routing/", DefectRouting.as_view()),
    path("defects/<uuid:pk>/reminders/", DefectReminders.as_view()),
    path("work-item-options/", WorkItemOptions.as_view()),
    path("record-progress/", RecordProgress.as_view()),
    path("versions/options/", ProjectVersionOptions.as_view()),
    path("versions/", ProjectVersions.as_view()),
    path("versions/<uuid:pk>/", ProjectVersionDetail.as_view()),
    path("versions/<uuid:pk>/workflow/", ProjectVersionWorkflow.as_view()),
    path("versions/<uuid:pk>/sync/", ProjectVersionSync.as_view()),
    path("project-report/", ProjectPeriodReport.as_view()),
    path("work-item-kinds/", WorkItemKinds.as_view()),
    path("case-options/", CaseOptions.as_view()),
    path("native-issues/<uuid:pk>/policy/", NativeIssuePolicy.as_view()),
    path("field-agents/<uuid:pk>/install-package/", FieldAgentInstallPackage.as_view()),
    path("notification-targets/", NotificationTargets.as_view()),
    path("notification-targets/<uuid:pk>/", NotificationTargetDetail.as_view()),
    path("reports/<uuid:pk>/deliveries/", ReportDeliveries.as_view()),
    path("report-deliveries/<uuid:pk>/send/", ReportDeliverySend.as_view()),
    path("test-resources/", TestResources.as_view()),
    path("test-resources/<uuid:pk>/", TestResourceDetail.as_view()),
    path("plans/<uuid:pk>/preflight/", Preflight.as_view()),
    path("plans/<uuid:pk>/resources/", PlanResources.as_view()),
    path("reports/<uuid:pk>/conclusion/", reports.ReportConclude.as_view()),
    path("document-files/<uuid:pk>/", DocumentFileDownload.as_view()),
    path("document-imports/", DocumentImports.as_view()),
    path("document-imports/feishu/connections/", FeishuConnectionOptions.as_view()),
    path("document-imports/<uuid:pk>/confirm/", DocumentConfirm.as_view()),
    path("document-imports/<uuid:pk>/ocr/", DocumentOcr.as_view()),
    path("document-imports/<uuid:pk>/ocr/review/", DocumentOcrReview.as_view()),
    path("document-imports/feishu/", FeishuDocumentImport.as_view()),
    path("integrations/connections/", ConnectionSettings.as_view()),
    path("defects/<uuid:pk>/disposition/", DefectDisposition.as_view()),
    path("bulk-actions/", BulkActions.as_view()),
    path("field-agents/<uuid:pk>/credential/", FieldAgentCredential.as_view()),
    path("field-agent-client/", FieldAgentClient.as_view()),
    path("saved-views/", SavedViews.as_view()),
    path("saved-views/<uuid:pk>/", SavedViewDetail.as_view()),
    path("field-agents/", FieldAgents.as_view()),
    path("field-agents/<uuid:pk>/", FieldAgentDetail.as_view()),
    path("field-agents/<uuid:pk>/heartbeat/", FieldHeartbeat.as_view()),
    path("telemetry/<uuid:pk>/review/", TelemetryReview.as_view()),
    path("defects/<uuid:pk>/diagnostics/", DiagnosticList.as_view()),
    path("defects/<uuid:pk>/deployment-snapshots/", DefectDeploymentSnapshots.as_view()),
    path("diagnostics/<uuid:pk>/", DiagnosticDetail.as_view()),
    path("task-packages/", TaskPackages.as_view()),
    path("task-packages/<uuid:pk>/confirm/", TaskPackageConfirm.as_view()),
    path("defects/<uuid:pk>/team/", DefectTeam.as_view()),
    path("defect-statistics/", DefectStatistics.as_view()),
    path("requirements/", requirements.RequirementList.as_view()),
    path("requirements/<uuid:pk>/", requirements.RequirementDetail.as_view()),
    path("requirements/<uuid:pk>/tasks/", requirements.RequirementTasks.as_view()),
    path("requirements/<uuid:pk>/workflow/", requirements.RequirementWorkflow.as_view()),
    path("defects/<uuid:pk>/attachments/", attachments.DefectAttachments.as_view()),
    path("defects/<uuid:pk>/attachments/download/", DefectAttachmentArchive.as_view()),
    path("files/<uuid:pk>/preview/", attachments.ImagePreview.as_view()),
    path("packages/<uuid:pk>/files/", attachments.PackageFiles.as_view()),
    path("files/<uuid:pk>/download/", attachments.FileDownload.as_view()),
    path("roles/", RoleList.as_view()),
    path("role-policy/", RolePolicy.as_view()),
    path("case-imports/", imports.ImportList.as_view()),
    path("case-imports/<uuid:pk>/confirm/", imports.ImportConfirm.as_view()),
    path("reports/", reports.ReportList.as_view()),
    path("reports/<uuid:pk>/", reports.ReportDetail.as_view()),
    path("reports/<uuid:pk>/download/", reports.ReportDownload.as_view()),
    path("source-defects/", sources.SourceDefect.as_view()),
    path("defects/<uuid:pk>/collaboration/", sources.DefectCollaboration.as_view()),
    path("defects/<uuid:pk>/comments/", discussion.DefectDiscussion.as_view()),
    path("defects/<uuid:pk>/comments/<uuid:comment_id>/replies/", discussion.DiscussionReplies.as_view()),
    path("defects/<uuid:pk>/comments/files/", discussion.DiscussionFiles.as_view()),
    path("defects/<uuid:pk>/comments/files/<uuid:file_id>/download/", discussion.DiscussionFile.as_view()),
    path(
        "defects/<uuid:pk>/comments/files/<uuid:file_id>/preview/",
        discussion.DiscussionFile.as_view(),
        {"preview": True},
    ),
    path("defects/<uuid:pk>/sources/", sources.DefectSources.as_view()),
    path("packages/", sources.PackageList.as_view()),
    path("packages/preflight/", sources.PackagePreflight.as_view()),
    path("suites/", assets.SuiteList.as_view()),
    path("suites/<uuid:pk>/", assets.SuiteDetail.as_view()),
    path("suites/<uuid:pk>/copy/", assets.SuiteCopy.as_view()),
    path("suites/<uuid:pk>/publish/", assets.SuitePublish.as_view()),
    path("releases/", assets.ReleaseList.as_view()),
    path("releases/<uuid:pk>/", assets.ReleaseDetail.as_view()),
    path("releases/<uuid:pk>/copy/", assets.ReleaseCopy.as_view()),
    path("releases/<uuid:pk>/admit/", assets.ReleaseAdmit.as_view()),
    path("solutions/", solutions.SolutionList.as_view()),
    path("solutions/<uuid:pk>/", solutions.SolutionDetail.as_view()),
    path("solutions/<uuid:pk>/submit/", solutions.SolutionSubmit.as_view()),
    path("solutions/<uuid:pk>/review/", solutions.SolutionDecision.as_view()),
    path("report/", views.QualityReport.as_view()),
    path("context/", views.QualityContext.as_view()),
    path("cases/", views.CaseList.as_view()),
    path("cases/<uuid:pk>/", views.CaseDetail.as_view()),
    path("plans/", views.PlanList.as_view()),
    path("plans/<uuid:pk>/", plans.PlanDetail.as_view()),
    path("plans/<uuid:pk>/copy/", plans.PlanCopy.as_view()),
    path("plans/<uuid:pk>/workflow/", PlanWorkflow.as_view()),
    path("executions/", views.ExecutionList.as_view()),
    path("items/<uuid:pk>/executions/", views.ExecutionList.as_view()),
    path("executions/<uuid:pk>/defect/", views.ExecutionDefect.as_view()),
    path("defects/", views.DefectList.as_view()),
    path("defects/<uuid:pk>/", views.DefectDetail.as_view()),
    path("defects/<uuid:pk>/report/", views.DefectReportEdit.as_view()),
]
