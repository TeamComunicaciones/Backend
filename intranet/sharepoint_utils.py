# core/sharepoint_utils.py
import base64
import uuid
import requests
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed

GRAPH_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


def get_graph_access_token():
    tenant_id = settings.GRAPH_TENANT_ID
    client_id = settings.GRAPH_CLIENT_ID
    client_secret = settings.GRAPH_CLIENT_SECRET

    url = GRAPH_TOKEN_URL.format(tenant_id=tenant_id)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default"
    }

    response = requests.post(url, headers=headers, data=data)

    if response.status_code != 200:
        raise AuthenticationFailed("Error obteniendo access token de Graph")

    return response.json().get("access_token")


def upload_comision_image(file_obj):
    """
    Sube un archivo (comprobante) a SharePoint en el site ImgComisiones
    y devuelve el nombre de archivo con el que se guardó.
    """
    access_token = get_graph_access_token()

    # ⚠️ En settings.py debes definir este SITE_ID del site ImgComisiones
    site_id = settings.SHAREPOINT_COMISIONES_SITE_ID

    # Carpeta dentro del drive raíz (puedes cambiar 'uploads' si usas otra)
    folder_path = getattr(settings, "SHAREPOINT_COMISIONES_FOLDER", "uploads")

    original_name = file_obj.name
    ext = original_name.split(".")[-1] if "." in original_name else "jpg"
    unique_name = f"{uuid.uuid4().hex}.{ext}"

    upload_url = f"{GRAPH_BASE_URL}/sites/{site_id}/drive/root:/{folder_path}/{unique_name}:/content"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/octet-stream",
    }

    file_bytes = file_obj.read()
    response = requests.put(upload_url, headers=headers, data=file_bytes)

    if response.status_code not in (200, 201):
        raise Exception(f"Error subiendo archivo a SharePoint: {response.text}")

    drive_item = response.json()
    web_url = drive_item.get("webUrl")

    return {
        "filename": unique_name,  # esto es lo que vamos a guardar
        "web_url": web_url,
    }


def download_comision_image(filename):
    """
    Descarga el archivo desde SharePoint por nombre (filename) y lo devuelve
    como base64 + content_type, igual a tu get_image_corresponsal.
    """
    access_token = get_graph_access_token()
    site_id = settings.SHAREPOINT_COMISIONES_SITE_ID
    folder_path = getattr(settings, "SHAREPOINT_COMISIONES_FOLDER", "uploads")

    download_url = f"{GRAPH_BASE_URL}/sites/{site_id}/drive/root:/{folder_path}/{filename}:/content"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    response = requests.get(download_url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Error descargando archivo desde SharePoint: {response.text}")

    encoded_image = base64.b64encode(response.content).decode("utf-8")
    content_type = response.headers.get("Content-Type", "image/jpeg")

    return encoded_image, content_type
