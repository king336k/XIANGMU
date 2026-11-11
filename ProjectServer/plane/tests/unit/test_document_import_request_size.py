import pytest
from django.test import RequestFactory,override_settings
from django.http import HttpResponse
from plane.middleware.request_body_size import RequestBodySizeLimitMiddleware


def test_document_import_streaming_budget_does_not_raise_other_route_limits():
    handler=RequestBodySizeLimitMiddleware(lambda request:HttpResponse("accepted"))
    factory=RequestFactory()
    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1024):
        path="/api/workspaces/demo/projects/00000000-0000-0000-0000-000000000001/quality/document-imports/"
        request=factory.generic("POST",path,data=b"x"*2048,content_type="multipart/form-data; boundary=test")
        assert handler(request).status_code==200
        assert not hasattr(request,"_body")
        assert handler(factory.generic("POST","/api/other/",data=b"x"*2048,content_type="application/json")).status_code==413
        assert handler(factory.generic("POST",path,data=b"x"*2048,content_type="application/json")).status_code==413
        request=factory.generic("POST",path,data=b"x",content_type="multipart/form-data; boundary=test")
        request.META["CONTENT_LENGTH"]=str(22*1024*1024+1)
        assert handler(request).status_code==413
