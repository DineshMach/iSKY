from django.shortcuts import redirect
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .permissions import AuthRedirect


def _wants_json(request):
    accept = request.headers.get("Accept", "")
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in accept
        or "application/json" in request.content_type
    )


def custom_exception_handler(exc, context):
    if isinstance(exc, AuthRedirect):
        request = context["request"]
        login_url = reverse("home")

        if _wants_json(request):
            
            return Response({"detail": str(exc.detail), "redirect_url": login_url},status=401,)
        return redirect(login_url)

    return drf_exception_handler(exc, context)