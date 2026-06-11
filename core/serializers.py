from rest_framework import serializers
from .models import TelemetrySnapshot, HardwareDevice


class DiskUsageSerializer(serializers.Serializer):
    mountpoint   = serializers.CharField()
    total_gb     = serializers.FloatField()
    used_percent = serializers.FloatField()


class TelemetryIngestSerializer(serializers.Serializer):
    timestamp        = serializers.DateTimeField()
    hostname         = serializers.CharField(max_length=200)
    os               = serializers.CharField(max_length=100, required=False, default="")
    os_version       = serializers.CharField(max_length=200, required=False, default="")
    cpu_percent      = serializers.FloatField(min_value=0, max_value=100)
    ram_total_gb     = serializers.FloatField(min_value=0)
    ram_used_percent = serializers.FloatField(min_value=0, max_value=100)
    disk_partitions  = DiskUsageSerializer(many=True, required=False, default=list)
    uptime_seconds   = serializers.IntegerField(min_value=0, default=0)
    ip_address       = serializers.IPAddressField(required=False, allow_null=True, default=None)
    temperatures     = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    network          = serializers.DictField(required=False, default=dict)
    cpu_freq_mhz     = serializers.FloatField(required=False, allow_null=True, default=None)
    cpu_cores        = serializers.IntegerField(required=False, allow_null=True, default=None)
    cpu_threads      = serializers.IntegerField(required=False, allow_null=True, default=None)
    gpu_name                = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    gpu_usage_percent       = serializers.FloatField(required=False, allow_null=True, default=None)
    gpu_memory_used_percent = serializers.FloatField(required=False, allow_null=True, default=None)
    gpu_memory_total_gb     = serializers.FloatField(required=False, allow_null=True, default=None)
    gpu_temp_celsius        = serializers.FloatField(required=False, allow_null=True, default=None)


class TelemetrySnapshotSerializer(serializers.ModelSerializer):
    device_name  = serializers.CharField(source="device.display_name", read_only=True)
    uptime_human = serializers.CharField(read_only=True)

    class Meta:
        model  = TelemetrySnapshot
        fields = [
            "id", "device_name", "captured_at",
            "cpu_percent", "ram_used_percent", "ram_total_gb",
            "disk_usage", "uptime_seconds", "uptime_human",
            "gpu_name", "gpu_usage_percent", "gpu_memory_used_percent",
            "gpu_memory_total_gb", "gpu_temp_celsius",
        ]


class HardwareDeviceSummarySerializer(serializers.ModelSerializer):
    is_online      = serializers.BooleanField(read_only=True)
    status         = serializers.CharField(read_only=True)
    latest_snapshot = serializers.SerializerMethodField()

    class Meta:
        model  = HardwareDevice
        fields = [
            "id", "hostname", "friendly_name", "device_type",
            "os", "last_seen", "is_online", "status", "latest_snapshot",
        ]

    def get_latest_snapshot(self, obj):
        snap = obj.snapshots.first()
        if snap:
            return TelemetrySnapshotSerializer(snap).data
        return None
