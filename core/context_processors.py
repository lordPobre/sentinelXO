from django.conf import settings

def perseus_context(request):
    return {
        "PERSEUS_COMPANY_NAME": getattr(settings, "PERSEUS_COMPANY_NAME", "Perseus Technology"),
        "PERSEUS_SUPPORT_EMAIL": getattr(settings, "PERSEUS_SUPPORT_EMAIL", "soporte@perseustechnology.dev"),
    }
