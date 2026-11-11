# SPDX-License-Identifier: AGPL-3.0-only
from django.urls import path
from . import views, chat_views
from .document_analysis import ArticleAnalysis, ArticleAnalysisApply
from .sharing import ShareTargets, ArticleShares, ShareWithdraw
from .configuration import ModelConfiguration
from .semantic_views import SemanticIndexView
from .governance import Governance, GovernanceMerge, GovernanceOffline, GovernanceIgnore, GovernanceUndo

urlpatterns = [
    path("articles/<uuid:pk>/analysis/", ArticleAnalysis.as_view()),
    path("articles/<uuid:pk>/analysis/apply/", ArticleAnalysisApply.as_view()),
    path("share-targets/", ShareTargets.as_view()),
    path("articles/<uuid:pk>/shares/", ArticleShares.as_view()),
    path("shares/<uuid:pk>/withdraw/", ShareWithdraw.as_view()),
    path("semantic-index/", SemanticIndexView.as_view()),
    path("governance/ignore/", GovernanceIgnore.as_view()),
    path("governance/merges/<uuid:pk>/undo/", GovernanceUndo.as_view()),
    path("governance/", Governance.as_view()),
    path("governance/merge/", GovernanceMerge.as_view()),
    path("governance/offline/", GovernanceOffline.as_view()),
    path("configuration/", ModelConfiguration.as_view()),
    path("articles/", views.ArticleList.as_view()),
    path("articles/<uuid:pk>/", views.ArticleDetail.as_view()),
    path("articles/<uuid:pk>/workflow/", views.ArticleWorkflow.as_view()),
    path("search/", views.KnowledgeSearch.as_view()),
    path("status/", chat_views.AssistantStatus.as_view()),
    path("chat/", chat_views.ChatEndpoint.as_view()),
    path("conversations/", chat_views.ConversationList.as_view()),
    path("conversations/<uuid:pk>/", chat_views.ConversationDetail.as_view()),
    path("messages/<uuid:pk>/feedback/", chat_views.ChatFeedback.as_view()),
]
