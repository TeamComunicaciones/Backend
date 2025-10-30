from functools import wraps
from rest_framework.response import Response
from rest_framework.exceptions import AuthenticationFailed
import jwt
from django.conf import settings
from .models import User, Permisos_usuarios # Asegúrate de importar tus modelos

def admin_permission_required(view_func):
    """
    Decorador para verificar que el usuario está autenticado y tiene
    permisos de administrador para gestionar el panel.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                raise AuthenticationFailed('Token no proporcionado o con formato incorrecto.')
            
            token = auth_header.split(' ')[1]
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            
            user_id = payload.get('id')
            if not user_id:
                raise AuthenticationFailed('El token no contiene un identificador de usuario válido.')

            user = User.objects.get(id=user_id)
            request.user = user
            
            # --- Verificación de ADMIN ---
            # Asumimos que el permiso para este panel se llama 'admin_comisiones'
            # ¡Ajusta este string si tu permiso se llama diferente!
            if not Permisos_usuarios.objects.filter(user=user, permiso__permiso='admin_comisiones', tiene_permiso=True).exists():
                raise AuthenticationFailed('No tienes los permisos de Administrador necesarios para este recurso.')
            
            return view_func(request, *args, **kwargs)

        except (jwt.InvalidTokenError, jwt.ExpiredSignatureError, AuthenticationFailed, User.DoesNotExist) as e:
            return Response({'detail': str(e)}, status=403)
        except Exception as e:
            return Response({'detail': f'Ocurrió un error interno: {str(e)}'}, status=500)
            
    return wrapper
