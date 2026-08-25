# Team Comunicaciones — Backend

API REST del sistema interno de gestión comercial de Team Comunicaciones. Maneja comisiones de asesores, liquidación de pagos, precios de equipos, turnos, reportes de ventas y administración de usuarios.

**Stack:** Python 3.11 / Django 4.2 / Django REST Framework / PostgreSQL / Celery + Redis

---

## Requisitos

- Python 3.11.6
- Redis (en producción corre en el mismo servidor; en local usar Docker)
- PostgreSQL (producción en DigitalOcean; en local se puede usar SQLite)

---

## Configuración local

### Solo la primera vez

```bash
# 1. Crear y activar entorno virtual
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Crear archivo .env (junto a manage.py) a partir de la plantilla
copy .env.example .env        # Windows
# cp .env.example .env        # Linux/Mac
#
# Completar al menos DJANGO_SECRET_KEY (podés generarla con:
#   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
# ). Las variables de PostgreSQL (DB_*), Microsoft Graph, Shopify y del SQL
# Server externo "Stok" pueden dejarse vacías si no vas a probar esas
# integraciones en local. Ver .env.example para el detalle de cada variable.
#
# Si preferís usar SQLite en vez de PostgreSQL en local, no hace falta tocar
# .env: alcanza con sobreescribir DATABASES en backend/local_settings.py
# (archivo opcional, ignorado por git):
#
#   from pathlib import Path
#   BASE_DIR = Path(__file__).resolve().parent.parent
#   DATABASES = {
#       'default': {
#           'ENGINE': 'django.db.backends.sqlite3',
#           'NAME': BASE_DIR / 'db_local.sqlite3',
#       }
#   }

# 4. Aplicar migraciones
python manage.py migrate

# 5. Crear superusuario para el admin de Django
python manage.py createsuperuser

# 6. Cargar datos de prueba
python manage.py crear_datos_prueba

# 7. Levantar Redis (requiere Docker)
docker run -d -p 6379:6379 --name redis-local redis
```

### Cada vez que se ejecuta en local

Abrir 3 terminales desde `Backend/`:

**Terminal 1 — Servidor Django**
```bash
venv\Scripts\activate
python manage.py runserver
```

**Terminal 2 — Celery Worker**
```bash
venv\Scripts\activate
celery -A backend worker -l info -P eventlet
```

**Terminal 3 — Celery Beat** (solo si se quiere probar el schedule)
```bash
venv\Scripts\activate
celery -A backend beat -l info
```

### URLs locales

| Servicio | URL |
|---|---|
| API | http://localhost:8000/api/v1.0/ |
| Admin Django | http://localhost:8000/admin/ |

### Usuarios de prueba

| Usuario | Contraseña | Rol |
|---|---|---|
| admin | Admin2024! | Administrador |
| carlos.torres | Asesor2024! | Asesor (RUTA-01) |
| maria.lopez | Asesor2024! | Asesor (RUTA-02) |
| juan.perez | Super2024! | Supervisor |

> El campo "email" del login acepta el nombre de usuario (username), no el email.

---

## Despliegue en producción

El servidor es un Droplet de DigitalOcean (Ubuntu). El código vive en `/var/www/backend/backend-teams-comunicaciones/`.

### Variables de entorno requeridas

`backend/settings.py` ya no tiene secretos hardcodeados: todos se leen de variables de entorno (ver `.env.example` para la lista completa — `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DB_*`, `MS_OAUTH_*`, `GRAPH_*`, `SHOPIFY_*`, `STOK_DB_*`, `EMAIL_HOST_*`). En el servidor, la forma más simple es crear un archivo `.env` en `/var/www/backend/backend-teams-comunicaciones/.env` (junto a `manage.py`, mismo formato que `.env.example`) — `settings.py` lo carga automáticamente. **Ese `.env` de producción se crea y edita a mano en el servidor, nunca se sube al repositorio.**

Alternativa equivalente: definir las mismas variables como `Environment=` (o `EnvironmentFile=`) en los `.service` de systemd de `gunicorn`, `celery` y `celerybeat`, como ya se hacía para `EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD` en el ejemplo de abajo.

### Solo la primera vez en el servidor

```bash
# Configurar celerybeat como servicio systemd
# Crear /etc/systemd/system/celerybeat.service con:
#
#   [Unit]
#   Description=Celery Beat Scheduler
#   After=network.target
#
#   [Service]
#   User=root
#   WorkingDirectory=/var/www/backend/backend-teams-comunicaciones
#   Environment="EMAIL_HOST_USER=..."
#   Environment="EMAIL_HOST_PASSWORD=..."
#   ExecStart=/var/www/backend/backend-teams-comunicaciones/venv/bin/celery -A backend beat -l info
#   Restart=always
#
#   [Install]
#   WantedBy=multi-user.target

systemctl daemon-reload
systemctl enable celerybeat
systemctl start celerybeat
```

### Cada despliegue

```bash
cd /var/www/backend/backend-teams-comunicaciones

# 1. Traer cambios
git pull

# 2. Instalar dependencias nuevas (si las hay)
source venv/bin/activate
pip install -r requirements.txt

# 3. Aplicar migraciones
python manage.py migrate

# 4. Reiniciar servicios
systemctl restart gunicorn
systemctl restart celery
systemctl restart celerybeat
```

### Verificar que todo está corriendo

```bash
systemctl status gunicorn
systemctl status celery
systemctl status celerybeat
```

---

## Arquitectura

```
Nginx
├── api.teamcomunicaciones.com.co  →  Gunicorn (Django)
└── teamcomunicaciones.com.co      →  Archivos estáticos del frontend (dist/)

Celery Worker  ←→  Redis  ←→  Celery Beat (schedule diario 00:05)
                              └── vencer_comisiones_por_inactividad()
```

## Servicios externos

| Servicio | Propósito |
|---|---|
| PostgreSQL (DigitalOcean) | Base de datos de producción |
| Redis (local en el servidor) | Broker de Celery |
| Microsoft SharePoint (Graph API) | Almacenamiento de comprobantes de pago |
| Microsoft Azure AD | SSO OAuth2 |
| Gmail SMTP | Notificaciones por correo |
