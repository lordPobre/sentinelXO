from django.contrib import admin
from django.utils.html import format_html
from .models import EmailLog, SmtpCheck

@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ["sent_at", "status_badge", "recipient", "subject_short", "category", "client"]
    list_filter  = ["status", "category", "client"]
    search_fields = ["recipient", "subject"]
    readonly_fields = ["sent_at"]
    ordering = ["-sent_at"]

    def status_badge(self, obj):
        colors = {"sent": "#16a34a", "failed": "#dc2626", "bounced": "#d97706"}
        return format_html(
            '<span style="color:{};font-weight:600;">{}</span>',
            colors.get(obj.status, "#6b7280"),
            obj.get_status_display(),
        )
    status_badge.short_description = "Estado"

    def subject_short(self, obj):
        return obj.subject[:60] + ("…" if len(obj.subject) > 60 else "")
    subject_short.short_description = "Asunto"


@admin.register(SmtpCheck)
class SmtpCheckAdmin(admin.ModelAdmin):
    list_display = ["checked_at", "status_badge", "response_ms", "smtp_host", "smtp_port"]
    list_filter  = ["status"]
    readonly_fields = ["checked_at"]
    ordering = ["-checked_at"]

    def status_badge(self, obj):
        colors = {"ok": "#16a34a", "timeout": "#d97706", "error": "#dc2626"}
        label  = {"ok": "● OK", "timeout": "● Timeout", "error": "● Error"}
        return format_html(
            '<span style="color:{};font-weight:600;">{}</span>',
            colors.get(obj.status, "#6b7280"),
            label.get(obj.status, obj.status),
        )
    status_badge.short_description = "Estado"
