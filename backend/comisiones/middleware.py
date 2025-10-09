# comisiones/middleware.py

import jwt
from functools import wraps
from urllib.parse import parse_qs

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from channels.db import database_sync_to_async

# Importa tu modelo de permisos personalizado
from intranet.models import Permisos_usuarios # <-- AJUSTA LA RUTA A TU MODELO

User = get_user_model()

@database_sync_to_async
def get_user_and_check_permissions(token_key):
    """
    Función asíncrona que decodifica el token, obtiene el usuario
    y verifica el permiso específico de 'asesor_comisiones'.
    """
    try:
        # 1. Decodificar el token usando PyJWT (como en tu decorador)
        payload = jwt.decode(token_key, settings.SECRET_KEY, algorithms=['HS256'])
        
        user_id = payload.get('id')
        if not user_id:
            return AnonymousUser()

        # 2. Obtener el usuario
        user = User.objects.get(id=user_id)
        
        # 3. Verificar el permiso personalizado (lógica de tu decorador)
        if not Permisos_usuarios.objects.filter(user=user, permiso__permiso='asesor_comisiones', tiene_permiso=True).exists():
            # Si no tiene el permiso, lo tratamos como un usuario anónimo
            return AnonymousUser()
            
        # Si todo es correcto, devolvemos el usuario autenticado y autorizado
        return user

    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError, User.DoesNotExist):
        # Si el token es inválido o el usuario no existe, es anónimo
        return AnonymousUser()

class TokenAuthMiddleware:
    """
    Middleware de Channels que autentica al usuario a partir de un token JWT
    en la URL y verifica sus permisos.
    """
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        # Extraemos el token de la query string de la URL
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)
        token = query_params.get("token", [None])[0]

        if token:
            # Llamamos a nuestra nueva función que valida token y permisos
            scope['user'] = await get_user_and_check_permissions(token)
        else:
            scope['user'] = AnonymousUser()
        
        # Continuamos con el resto del proceso de Channels
        return await self.inner(scope, receive, send)