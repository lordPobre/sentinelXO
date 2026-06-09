from django.conf import settings

def perseus_context(request):
    return {
        "SENTINEL_COMPANY_NAME": getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO"),
        "SENTINEL_SUPPORT_EMAIL": getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev"),
    }