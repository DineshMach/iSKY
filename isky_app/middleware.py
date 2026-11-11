from django.shortcuts import render
from django.template import TemplateDoesNotExist
from django.conf import settings


class TemplateDoesNotExistMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, TemplateDoesNotExist):
            context = {
                # Only reveal the missing template's path in DEBUG mode —
                # never leak internal file paths to a real user in production.
                "template_name": str(exception) if settings.DEBUG else None,
            }
            return render(request, "template_missing.html", context, status=404)
        return None  # let every other exception continue as normal (→ handler500, etc.)