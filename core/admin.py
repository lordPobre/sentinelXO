from django.contrib import admin
from django.utils.html import format_html, mark_safe
from .models import (Client, HardwareDevice, TelemetrySnapshot, Domain,
                     M365Tenant, M365License, MaintenanceIncident, MonthlyReport)
from .models import AlertRule, AlertEvent


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["company_name", "rut", "contact_email", "plan", "health_badge", "is_active"]
    list_filter = ["plan", "is_active"]
    search_fields = ["company_name", "rut", "contact_email"]
    filter_horizontal = ["portal_users"]

    @admin.display(description="Estado de salud")
    def health_badge(self, obj):
        status = obj.get_health_status()
        colors = {"ok": "#16a34a", "warning": "#d97706", "critical": "#dc2626", "unknown": "#6b7280"}
        labels = {"ok": "OK", "warning": "Atención", "critical": "Crítico", "unknown": "Sin datos"}
        return format_html(
            '<span style="color:{};font-weight:600;">{}</span>',
            colors.get(status, "#6b7280"),
            labels.get(status, status),
        )


class TelemetryInline(admin.TabularInline):
    model = TelemetrySnapshot
    extra = 0
    max_num = 0
    can_delete = False
    show_change_link = False
    readonly_fields = [
        "captured_at", "cpu_percent", "ram_used_percent",
        "ram_total_gb", "uptime_seconds", "disk_usage",
    ]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(HardwareDevice)
class HardwareDeviceAdmin(admin.ModelAdmin):
    list_display = [
        "get_display_name", "client", "device_type",
        "os", "online_badge", "last_seen", "is_active",
    ]
    list_filter = ["device_type", "is_active", "client"]
    search_fields = ["hostname", "friendly_name", "client__company_name"]
    readonly_fields = ["agent_token", "registered_at", "last_seen"]
    inlines = [TelemetryInline]

    @admin.display(description="Nombre", ordering="hostname")
    def get_display_name(self, obj):
        return obj.friendly_name or obj.hostname

    @admin.display(description="Estado")
    def online_badge(self, obj):
        if obj.is_online:
            return format_html(
                '<span style="color:{};font-weight:600;">● {}</span>',
                "#16a34a", "Online",
            )
        return format_html(
            '<span style="color:{};">● {}</span>',
            "#dc2626", "Offline",
        )


@admin.register(TelemetrySnapshot)
class TelemetrySnapshotAdmin(admin.ModelAdmin):
    list_display = ["device", "captured_at", "cpu_percent", "ram_used_percent", "uptime_seconds"]
    list_filter = ["device__client", "device"]
    readonly_fields = [
        "device", "captured_at", "cpu_percent", "ram_used_percent",
        "ram_total_gb", "disk_usage", "uptime_seconds",
    ]
    ordering = ["-captured_at"]

    def has_add_permission(self, request):
        return False


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ["fqdn", "client", "expiry_date", "days_left", "status", "resolves_dns"]
    list_filter = ["status", "client"]
    search_fields = ["fqdn", "client__company_name"]

    @admin.display(description="Días restantes", ordering="expiry_date")
    def days_left(self, obj):
        days = obj.days_until_expiry
        if days is None:
            return "—"
        if days < 0:
            return format_html(
                '<span style="color:{};font-weight:600;">{}</span>',
                "#dc2626", "Vencido",
            )
        color = "#dc2626" if days < 30 else "#d97706" if days < 90 else "#16a34a"
        return format_html(
            '<span style="color:{};">{} días</span>',
            color, days,
        )

@admin.register(M365Tenant)
class M365TenantAdmin(admin.ModelAdmin):
    list_display = ["client", "tenant_id", "last_synced", "is_active"]
    readonly_fields = ["last_synced", "sync_error"]

@admin.register(M365License)
class M365LicenseAdmin(admin.ModelAdmin):
    list_display = [
        "friendly_name", "client", "consumed_licenses",
        "total_licenses", "utilization_percent", "capability_status",
    ]
    list_filter = ["capability_status", "client"]

@admin.register(MaintenanceIncident)
class MaintenanceIncidentAdmin(admin.ModelAdmin):
    list_display = ["title", "client", "severity", "is_resolved", "created_at"]
    list_filter = ["severity", "is_resolved", "client"]
    search_fields = ["title", "client__company_name"]
    actions = ["mark_resolved"]

    @admin.action(description="Marcar como resuelto")
    def mark_resolved(self, request, queryset):
        for incident in queryset:
            incident.resolve()
        self.message_user(request, f"{queryset.count()} incidentes marcados como resueltos.")

@admin.register(MonthlyReport)
class MonthlyReportAdmin(admin.ModelAdmin):
    list_display = ["client", "period_year", "period_month", "status", "generated_at", "sent_at"]
    list_filter = ["status", "client"]
    readonly_fields = ["generated_at", "sent_at", "summary_data"]

@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display  = ("client", "device", "metric", "threshold", "severity",
                     "cooldown_minutes", "notify_email", "is_active")
    list_filter   = ("client", "severity", "metric", "is_active")
    list_editable = ("threshold", "severity", "is_active", "notify_email")
    ordering      = ("client", "metric")

@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display  = ("fired_at", "device", "metric", "value", "threshold",
                     "severity", "status", "notified")
    list_filter   = ("severity", "status", "metric", "notified")
    readonly_fields = ("fired_at", "device", "rule", "metric", "value",
                       "threshold", "severity", "notified", "message")
    ordering      = ("-fired_at",)

