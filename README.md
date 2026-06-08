# Perseus MSP — Plataforma de Monitoreo

**Perseus Technology** · plataforma SaaS B2B para Managed Service Providers

---

## Stack

- **Backend**: Python 3.12 + Django 5.x
- **Base de datos**: SQLite (dev) / PostgreSQL (producción)
- **Frontend**: Django Templates + HTMX + Tailwind CSS CDN
- **Tareas en segundo plano**: Celery + Redis
- **API**: Django REST Framework (para el agente)
- **Reportes PDF**: ReportLab

---

## Instalación local

### 1. Clonar y configurar entorno

```bash
git clone <repo>
cd perseus_msp
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 2. Variables de entorno

```bash
cp .env.example .env
# Editar .env con tu editor preferido
```

### 3. Base de datos y superusuario

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4. Correr el servidor

```bash
python manage.py runserver
```

Abrir http://127.0.0.1:8000

---

## Celery (tareas automáticas)

Requiere Redis corriendo. En desarrollo:

```bash
# Terminal 1: Redis (si tienes Docker)
docker run -p 6379:6379 redis:alpine

# Terminal 2: Celery worker
celery -A config worker -l info

# Terminal 3: Celery Beat (tareas programadas)
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

### Tareas programadas (se configuran en Django Admin → Periodic Tasks)

| Tarea                               | Horario               | Descripción                        |
|-------------------------------------|-----------------------|------------------------------------|
| `monitoring.refresh_all_domains`    | Diario 06:00          | WHOIS de todos los dominios        |
| `monitoring.sync_m365_all_clients`  | Cada 4 horas          | Licencias Microsoft 365            |
| `monitoring.check_expiry_alerts`    | Diario 09:00          | Emails de alerta de vencimientos   |
| `reports.generate_monthly_reports_all` | Día 1 del mes 08:00 | Reportes PDF mensuales             |

---

## Agente de telemetría

El agente se instala en los equipos de los clientes.

```bash
cd agent/
pip install psutil requests
cp .env.example .env
# Completar PERSEUS_TOKEN con el token del dispositivo (del panel)
python agent.py
```

**Programar ejecución automática:**

- **Windows**: Task Scheduler → repetir cada 15 min
- **Linux**: `*/15 * * * * /usr/bin/python3 /opt/perseus/agent.py`

---

## URLs principales

| URL                              | Descripción                        |
|----------------------------------|------------------------------------|
| `/dashboard/`                    | Redirige según rol del usuario     |
| `/dashboard/admin/overview/`     | Panel administrador Perseus        |
| `/dashboard/admin/clients/`      | Listado de todos los clientes      |
| `/dashboard/portal/<uuid>/`      | Dashboard del cliente final        |
| `/monitoring/domains/`           | Estado de dominios                 |
| `/reports/`                      | Listado de reportes PDF            |
| `/api/v1/telemetry/`             | Endpoint POST del agente           |
| `/admin/`                        | Django Admin                       |
| `/auth/login/`                   | Login                              |

---

## Primeros pasos tras instalar

1. Crear un superusuario: `python manage.py createsuperuser`
2. Ingresar al panel: http://127.0.0.1:8000/admin/
3. Crear el primer **Cliente** (Core → Clientes)
4. Crear un **HardwareDevice** para ese cliente (el token del agente se genera automáticamente)
5. Copiar el token al archivo `.env` del agente
6. Ejecutar el agente en el equipo del cliente
7. Para M365: crear un **M365 Tenant** con las credenciales de Azure AD

---

## Estructura del proyecto

```
perseus_msp/
├── config/             # Configuración Django (settings, urls, celery)
├── core/               # Modelos principales + API REST
│   ├── models.py       # Client, HardwareDevice, TelemetrySnapshot, Domain, M365License, etc.
│   ├── views_api.py    # Endpoints para el agente
│   └── serializers.py
├── monitoring/         # Lógica WHOIS y M365
│   ├── services.py     # check_domain_whois(), sync_m365_client()
│   └── tasks.py        # Tareas Celery de monitoreo
├── reports/            # Generación y envío de PDFs
│   ├── generator.py    # build_report_pdf() con ReportLab
│   └── tasks.py        # generate_monthly_reports_all()
├── dashboard/          # Vistas y URLs del dashboard
│   └── views.py        # Panel admin + portal cliente + HTMX fragments
├── templates/          # HTML Templates
│   ├── base/           # base.html, layout.html (sidebar)
│   ├── dashboard/      # admin_overview, client_portal, partials/
│   ├── monitoring/     # domain_list, partials/
│   └── registration/   # login.html
└── agent/              # Agente Python para equipos del cliente
    └── agent.py
```
