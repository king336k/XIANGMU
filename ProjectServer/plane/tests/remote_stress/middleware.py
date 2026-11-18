from django.conf import settings


class IsolationMarker:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['X-Remote-Stress-Isolation'] = settings.REMOTE_STRESS_ISOLATION
        return response
