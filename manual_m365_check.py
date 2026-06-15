"""
Test de conexion M365 - ejecutar localmente
Muestra el error exacto sin necesidad de Railway
"""
import urllib.request
import urllib.parse
import json
import sys

# Pega aqui los datos de tu tenant (los mismos que tienes en el admin de Sentinel XO)
TENANT_ID     = input("Tenant ID: ").strip()
CLIENT_ID     = input("Client ID: ").strip()
CLIENT_SECRET = input("Client Secret: ").strip()

print("\nProbando autenticacion Azure AD...")

# Obtener token
url  = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
data = urllib.parse.urlencode({
    "grant_type":    "client_credentials",
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "scope":         "https://graph.microsoft.com/.default",
}).encode()

try:
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode())
        if "access_token" in result:
            print("✓ Token obtenido correctamente")
            token = result["access_token"]
        else:
            print(f"✗ Error: {result.get('error_description', result)}")
            sys.exit(1)
except urllib.error.HTTPError as e:
    body = json.loads(e.read().decode())
    print(f"✗ HTTP {e.code}: {body.get('error_description', body)}")
    sys.exit(1)

# Probar Graph API
print("\nProbando Graph API...")
req2 = urllib.request.Request(
    "https://graph.microsoft.com/v1.0/organization",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(req2, timeout=10) as resp:
    org = json.loads(resp.read().decode()).get("value", [{}])[0]
    print(f"✓ Tenant: {org.get('displayName', '—')}")
    print(f"✓ Todo OK — el tenant responde correctamente")
