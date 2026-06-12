"""
Servicios de monitoreo: WHOIS para dominios y Microsoft Graph para M365.
"""
import logging
from datetime import timezone as dt_tz
from django.utils import timezone

logger = logging.getLogger("perseus")


# ─── Dominios ────────────────────────────────────────────────────────────────

def check_domain_whois(fqdn: str) -> dict:
    """
    Consulta WHOIS para obtener la fecha de vencimiento de un dominio.
    Retorna dict con: expiry_date, registrar, resolves_dns, error.
    """
    import whois
    import dns.resolver

    result = {
        "fqdn": fqdn,
        "expiry_date": None,
        "registrar": "",
        "resolves_dns": False,
        "error": "",
    }

    # Verificar resolución DNS
    try:
        dns.resolver.resolve(fqdn, "A")
        result["resolves_dns"] = True
    except Exception:
        try:
            dns.resolver.resolve(fqdn, "AAAA")
            result["resolves_dns"] = True
        except Exception:
            result["resolves_dns"] = False

    # Consulta WHOIS
    try:
        w = whois.whois(fqdn)
        expiry = w.expiration_date
        if isinstance(expiry, list):
            expiry = expiry[0]
        if expiry:
            if hasattr(expiry, "tzinfo") and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=dt_tz.utc)
            result["expiry_date"] = expiry.date()
        result["registrar"] = w.registrar or ""
    except Exception as e:
        logger.warning(f"WHOIS error para {fqdn}: {e}")
        result["error"] = str(e)

    return result


def check_domain_ssl(fqdn: str, port: int = 443, timeout: int = 8) -> dict:
    """
    Conecta vía TLS al dominio y obtiene info del certificado SSL:
    fecha de vencimiento, emisor, y protocolo TLS negociado.
    """
    import ssl
    import socket
    from datetime import datetime as dt

    result = {
        "ssl_expiry_date": None,
        "ssl_issuer":      "",
        "ssl_protocol":    "",
        "ssl_error":       "",
    }

    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((fqdn, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=fqdn) as ssock:
                cert = ssock.getpeercert()
                result["ssl_protocol"] = ssock.version() or ""

                # Fecha de vencimiento — formato 'Mon DD HH:MM:SS YYYY GMT'
                not_after = cert.get("notAfter")
                if not_after:
                    expiry_dt = dt.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                    result["ssl_expiry_date"] = expiry_dt.date()

                # Emisor — tupla de tuplas de tuplas
                issuer_parts = dict(x[0] for x in cert.get("issuer", []))
                result["ssl_issuer"] = (
                    issuer_parts.get("organizationName")
                    or issuer_parts.get("commonName")
                    or ""
                )

    except ssl.SSLCertVerificationError as e:
        result["ssl_error"] = f"Certificado inválido: {e.verify_message or e}"[:300]
    except socket.timeout:
        result["ssl_error"] = "Timeout al conectar (puerto 443 sin respuesta)"
    except ConnectionRefusedError:
        result["ssl_error"] = "Conexión rechazada en puerto 443"
    except socket.gaierror as e:
        result["ssl_error"] = f"Error DNS: {e}"[:300]
    except Exception as e:
        result["ssl_error"] = str(e)[:300]
        logger.warning(f"SSL check error para {fqdn}: {e}")

    return result


def refresh_domain_ssl(domain) -> bool:
    """Actualiza el estado del certificado SSL de un Domain instance."""
    data = check_domain_ssl(domain.fqdn)

    domain.ssl_expiry_date = data["ssl_expiry_date"]
    domain.ssl_issuer      = data["ssl_issuer"]
    domain.ssl_protocol    = data["ssl_protocol"]
    domain.ssl_error       = data["ssl_error"]

    if data["ssl_error"]:
        logger.warning(f"SSL error {domain.fqdn}: {data['ssl_error']}")

    domain.refresh_ssl_status()
    domain.save(update_fields=[
        "ssl_expiry_date", "ssl_issuer", "ssl_protocol", "ssl_error", "ssl_status"
    ])
    return True


def refresh_domain(domain) -> bool:
    """Actualiza el estado de un Domain instance. Retorna True si hubo cambios."""
    from core.models import Domain
    data = check_domain_whois(domain.fqdn)

    domain.last_checked = timezone.now()
    domain.resolves_dns = data["resolves_dns"]

    if data.get("expiry_date"):
        domain.expiry_date = data["expiry_date"]
    if data.get("registrar"):
        domain.registrar = data["registrar"]
    if data.get("error"):
        logger.warning(f"Error WHOIS {domain.fqdn}: {data['error']}")

    domain.refresh_status()
    domain.save(update_fields=[
        "last_checked", "resolves_dns", "expiry_date",
        "registrar", "status"
    ])

    # También verificar el certificado SSL
    try:
        refresh_domain_ssl(domain)
    except Exception as e:
        logger.warning(f"Error verificando SSL de {domain.fqdn}: {e}")

    return True



# ─── Microsoft 365 ────────────────────────────────────────────────────────────

# Mapa de SKU a nombres legibles
SKU_FRIENDLY_NAMES = {
    "SPE_E3": "Microsoft 365 E3",
    "SPE_E5": "Microsoft 365 E5",
    "O365_BUSINESS_PREMIUM": "Microsoft 365 Business Premium",
    "O365_BUSINESS_ESSENTIALS": "Microsoft 365 Business Basic",
    "O365_BUSINESS": "Microsoft 365 Apps for Business",
    "EXCHANGESTANDARD": "Exchange Online (Plan 1)",
    "EXCHANGEENTERPRISE": "Exchange Online (Plan 2)",
    "TEAMS_EXPLORATORY": "Microsoft Teams Exploratory",
    "PROJECTPREMIUM": "Project Plan 5",
    "VISIOCLIENT": "Visio Plan 2",
    "POWER_BI_PRO": "Power BI Pro",
    "INTUNE_A": "Microsoft Intune",
    "EMS": "Enterprise Mobility + Security E3",
    "EMSPREMIUM": "Enterprise Mobility + Security E5",
}


def get_graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Obtiene un access token de Microsoft Graph vía Client Credentials."""
    import msal
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id, authority=authority, client_credential=client_secret
    )
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        raise ValueError(f"Error obteniendo token M365: {result.get('error_description', 'Unknown')}")
    return result["access_token"]


def fetch_m365_licenses(tenant_id: str, client_id: str, client_secret: str) -> list[dict]:
    """
    Llama a Graph API y retorna lista de licencias con:
    sku_part_number, friendly_name, total, consumed, status
    """
    import requests
    token = get_graph_token(tenant_id, client_id, client_secret)
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(
        "https://graph.microsoft.com/v1.0/subscribedSkus",
        headers=headers, timeout=15
    )
    resp.raise_for_status()

    # SKUs internos de Microsoft que no son licencias reales
    SKIP_SKUS = {
        "FLOW_FREE", "POWER_BI_STANDARD", "TEAMS_EXPLORATORY",
        "MICROSOFT_REMOTE_ASSIST", "WINDOWS_STORE", "DEVELOPERPACK",
        "DEVELOPERPACK_E5", "SHAREPOINTDESKLESS", "MCOIMP",
        "RIGHTSMANAGEMENT_ADHOC", "VISIOONLINE_PLAN1", "SPZA_IW",
    }

    skus = resp.json().get("value", [])
    licenses = []
    for sku in skus:
        sku_number = sku.get("skuPartNumber", "")
        total = sku["prepaidUnits"]["enabled"]

        # Filtrar SKUs internos y licencias con más de 10000 unidades
        if sku_number in SKIP_SKUS:
            continue
        if total >= 10000:
            continue
        if total == 0 and sku.get("consumedUnits", 0) == 0:
            continue

        licenses.append({
            "sku_part_number": sku_number,
            "friendly_name": SKU_FRIENDLY_NAMES.get(sku_number, sku_number),
            "total_licenses": total,
            "consumed_licenses": sku.get("consumedUnits", 0),
            "capability_status": sku.get("capabilityStatus", "Enabled"),
        })
    return licenses


def sync_m365_client(client) -> bool:
    """
    Sincroniza las licencias M365 de un cliente.
    Crea o actualiza objetos M365License. Retorna True si exitoso.
    """
    from core.models import M365License

    if not hasattr(client, "m365_tenant") or not client.m365_tenant.is_active:
        return False

    tenant = client.m365_tenant
    try:
        licenses = fetch_m365_licenses(
            tenant.tenant_id, tenant.azure_client_id, tenant.azure_client_secret
        )
        for lic_data in licenses:
            obj, _ = M365License.objects.update_or_create(
                client=client,
                sku_part_number=lic_data["sku_part_number"],
                defaults={
                    "friendly_name": lic_data["friendly_name"],
                    "total_licenses": lic_data["total_licenses"],
                    "consumed_licenses": lic_data["consumed_licenses"],
                    "capability_status": lic_data["capability_status"],
                    "last_synced": timezone.now(),
                }
            )
        tenant.last_synced = timezone.now()
        tenant.sync_error = ""
        tenant.save(update_fields=["last_synced", "sync_error"])
        logger.info(f"M365 sync OK: {client} — {len(licenses)} SKUs")
        return True

    except Exception as e:
        tenant.sync_error = str(e)
        tenant.save(update_fields=["sync_error"])
        logger.error(f"M365 sync ERROR {client}: {e}")
        return False
