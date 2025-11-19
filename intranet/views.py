# 1. Standard Library Imports
import ast
import base64
import calendar
import io
import json
import locale
import logging
import operator
import os
import random
import re
import shutil
import string
import tempfile
import traceback
import uuid
from collections import defaultdict
from datetime import datetime, date, timedelta, time
from decimal import Decimal, InvalidOperation
from functools import reduce, wraps
from io import BytesIO

# Third-party utility libraries
import numpy as np
import pandas as pd
import pytz
import requests
from dateutil.relativedelta import relativedelta

# Third-party security/API libraries
import jwt
from jwt.exceptions import DecodeError, ExpiredSignatureError, InvalidTokenError

# Third-party file processing libraries
from openpyxl import Workbook

# Third-party Django/DRF specific libraries
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema


# 2. Django Core & Utility Imports
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User, Group
from django.contrib.postgres.aggregates import ArrayAgg
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage, FileSystemStorage
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import IntegrityError, transaction
from django.db.models import (
    Case, Count, DecimalField, F, Max, OuterRef, Prefetch, Q, Subquery, Sum,
    Value, When
)
from django.db.models.functions import Coalesce, Lag, TruncDay, TruncMonth
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Value



# 3. Django REST Framework Imports
from rest_framework import status
from rest_framework.decorators import (
    api_view, parser_classes, permission_classes, schema
)
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView


# 4. Local Application Imports
from sqlControl.sqlControl import Sql_conexion
from . import models
from .models import (
    ActaEntrega, Comision, ImagenLogin, PagoComision, Perfil, Permisos_usuarios,
    ReporteDetalleVenta
)
from .serializers import (
    ActaEntregaSerializer, AsesorSerializer, ComisionSerializer,
    CustomTokenObtainPairSerializer, ImagenLoginSerializer,
    PagoComisionAdminSerializer, UserDataSerializer
)
from .services import process_sales_report_file
from .tasks import procesar_archivo_comisiones
from .permissions import admin_permission_required # Asegúrate de que esta importación sea correcta

# --- Helpers para decimales/KPIs y lógica de pagos ---

def decimal_or_zero(value):
    """
    Convierte cualquier cosa a Decimal >= 0, o 0 si no se puede.
    """
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal('0')


def safe_sum(qs, field_name):
    """
    Suma un campo decimal en un queryset de forma segura.
    """
    return decimal_or_zero(
        qs.aggregate(total=Coalesce(Sum(field_name), 0))['total']
    )


# Prefijos para identificar comisiones "fantasma" creadas por pagar_comisiones_view
LEDGER_PREFIXES = (
    "PAGO REGISTRADO #",
    "SALDO PENDIENTE PAGO #",
    "AJUSTE POR SOBRANTE PAGO #",
    "USO DE SALDO EN PAGO #",
)


def es_comision_ledger(comision_obj):
    """
    Devuelve True si la comisión parece ser una comisión 'artificial'
    creada por el proceso de pago (no viene del Excel original).
    """
    producto = (comision_obj.producto or "").strip()
    return any(producto.startswith(pref) for pref in LEDGER_PREFIXES)


def _get_asesor_user_queryset():
    """Helper para obtener solo usuarios con permiso de asesor."""
    asesor_user_ids = Permisos_usuarios.objects.filter(
        permiso__permiso='asesor_comisiones', 
        tiene_permiso=True
    ).values_list('user_id', flat=True)
    
    # Apuntamos a 'perfil' como en tu models.py
    return User.objects.filter(id__in=asesor_user_ids).select_related('perfil')


@api_view(['GET', 'POST'])
@admin_permission_required
def asesor_list_create(request):
    """
    GET: Lista todos los usuarios que SON asesores.
    POST: Crea un nuevo usuario Asesor.
    """
    if request.method == 'GET':
        asesores = _get_asesor_user_queryset()
        serializer = AsesorSerializer(asesores, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = AsesorSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT', 'DELETE'])
@admin_permission_required
def asesor_detail(request, pk):
    """
    PUT: Actualiza los datos de un asesor (username, email, ruta).
    DELETE: Elimina un asesor.
    """
    try:
        # Nos aseguramos de que solo podamos actuar sobre asesores
        user = _get_asesor_user_queryset().get(pk=pk)
    except User.DoesNotExist:
        return Response({'detail': 'Asesor no encontrado.'}, status=status.HTTP_44_NOT_FOUND)

    if request.method == 'PUT':
        # Usamos partial=True para que se pueda actualizar solo la ruta si se desea
        serializer = AsesorSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['PATCH'])
@admin_permission_required
def asesor_toggle_active(request, pk):
    """
    PATCH: Activa o desactiva un asesor.
    Espera: { "is_active": true/false }
    """
    try:
        user = _get_asesor_user_queryset().get(pk=pk)
    except User.DoesNotExist:
        return Response({'detail': 'Asesor no encontrado.'}, status=status.HTTP_44_NOT_FOUND)

    is_active = request.data.get('is_active')
    if is_active is None:
        return Response(
            {'detail': 'El campo "is_active" es requerido.'}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    user.is_active = bool(is_active)
    user.save(update_fields=['is_active'])
    
    return Response(
        {'detail': 'Estado actualizado.', 'is_active': user.is_active},
        status=status.HTTP_200_OK
    )


def token_required(view_func):
    """
    Decorador que verifica que el token JWT sea válido y adjunta el usuario al request.
    No comprueba permisos específicos.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return Response({'error': 'Token no proporcionado o con formato incorrecto.'}, status=401)
        
        try:
            token = auth_header.split(' ')[1]
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            
            user_id = payload.get('id')
            if not user_id:
                raise AuthenticationFailed('El token no contiene un identificador de usuario válido.')

            user = User.objects.get(id=user_id)
            request.user = user # Asignamos el usuario al request
            
        except jwt.ExpiredSignatureError:
            return Response({'error': 'El token ha expirado.'}, status=401)
        except (jwt.InvalidTokenError, User.DoesNotExist, AuthenticationFailed) as e:
            return Response({'error': f'Autenticación fallida: {str(e)}'}, status=401)
        except Exception as e:
            return Response({'error': f'Ocurrió un error interno: {str(e)}'}, status=500)
            
        # Si todo está bien, ejecutamos la vista original
        return view_func(request, *args, **kwargs)
        
    return wrapper

def asesor_permission_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                raise AuthenticationFailed('Token no proporcionado o con formato incorrecto.')
            
            token = auth_header.split(' ')[1]
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            
            # --- LÍNEA CORREGIDA ---
            # 1. Obtenemos el ID del token
            user_id = payload.get('id')
            if not user_id:
                raise AuthenticationFailed('El token no contiene un identificador de usuario válido.')

            # 2. Buscamos al usuario por su ID numérico
            user = User.objects.get(id=user_id)
            
            # Asignamos el usuario encontrado a la petición para que las vistas lo puedan usar
            request.user = user
            
            # Verificamos que el usuario tenga el permiso específico de "asesor"
            if not Permisos_usuarios.objects.filter(user=user, permiso__permiso='asesor_comisiones', tiene_permiso=True).exists():
                raise AuthenticationFailed('No tienes los permisos de Asesor necesarios para acceder a este recurso.')
            
            # Si todo está bien, ejecutamos la vista original
            return view_func(request, *args, **kwargs)

        # Capturamos todos los posibles errores de autenticación/permisos
        except (jwt.InvalidTokenError, jwt.ExpiredSignatureError, AuthenticationFailed, User.DoesNotExist) as e:
            # Devolvemos una respuesta de error clara
            return Response({'detail': str(e)}, status=403)
        except Exception as e:
            # Captura para cualquier otro error inesperado
            return Response({'detail': f'Ocurrió un error interno: {str(e)}'}, status=500)
            
    return wrapper

def cajero_permission_required(view_func):
    """
    Decorador personalizado que:
    1. Autentica al usuario vía JWT (Bearer token).
    2. Verifica que el usuario tenga el permiso de 'Cajero' (ID 11).
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            # 1. Lógica de autenticación JWT
            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                raise AuthenticationFailed('Token no proporcionado o con formato incorrecto.')
            
            token = auth_header.split(' ')[1]
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            
            user_id = payload.get('id')
            if not user_id:
                raise AuthenticationFailed('El token no contiene un identificador de usuario válido.')

            user = User.objects.get(id=user_id)
            # Asignamos el usuario a la request para que la vista lo use
            request.user = user
            
            # --- 2. VERIFICACIÓN DE PERMISO (CORREGIDA) ---
            # Verificamos el permiso de "caja" usando su ID (11)
            
            if not Permisos_usuarios.objects.filter(user=user, permiso__id=11, tiene_permiso=True).exists():
                
                # --- 3. MENSAJE DE ERROR (CORREGIDO) ---
                raise AuthenticationFailed('No tienes los permisos de Cajero necesarios para acceder a este recurso.')
            
            # Si tiene el permiso, ejecutamos la vista original
            return view_func(request, *args, **kwargs)

        # Captura de errores de autenticación o permisos
        except (jwt.InvalidTokenError, jwt.ExpiredSignatureError, AuthenticationFailed, User.DoesNotExist) as e:
            return Response({'detail': str(e)}, status=403) # 403 Forbidden
        
        # Captura de cualquier otro error
        except Exception as e:
            return Response({'detail': f'Ocurrió un error interno: {str(e)}'}, status=500)
            
    return wrapper

def get_sort_key(item):
    value = item.get('mes_pago') or item.get('mes_liquidacion')
    
    # Si no hay fecha, lo mandamos al final dándole la fecha más antigua posible
    if not value:
        return date.min
    
    # Si la fecha es un string (del serializador), la convertimos a un objeto date
    if isinstance(value, str):
        # Usamos split('T') por si es un datetime string como '2025-09-29T00:00:00'
        return date.fromisoformat(value.split('T')[0])
    
    # Si ya es un objeto date, lo retornamos tal cual
    return value

# --- VISTA 1: OBTENER TODOS LOS USUARIOS CON SU RUTA ---
# Este es el equivalente a tu `encargados_corresponsal`. Carga los datos iniciales.
@api_view(['GET'])
def usuarios_con_ruta_view(request):
    """
    Devuelve una lista de todos los usuarios del sistema, cada uno con su
    ID, username, email y la ruta que tiene asignada desde su Perfil.
    Crea un perfil para cualquier usuario que no lo tenga.
    """
    # Bucle para asegurar que cada usuario tenga un perfil asociado.
    # Es una buena práctica para evitar errores si se crean usuarios por fuera de esta lógica.
    for user in User.objects.filter(perfil__isnull=True):
        models.Perfil.objects.create(user=user)

    # Obtenemos todos los usuarios y su perfil relacionado para optimizar la consulta.
    usuarios = User.objects.select_related('perfil').all().order_by('username')
    
    # Construimos la lista de datos en el formato exacto que espera el frontend.
    data = [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "ruta_asignada": user.perfil.ruta_asignada
        }
        for user in usuarios
    ]
    return Response(data, status=status.HTTP_200_OK)


# --- VISTA 2: OBTENER LA LISTA ÚNICA DE RUTAS ---
# Este endpoint alimenta el selector desplegable en cada tarjeta de usuario.
@api_view(['GET'])
def lista_rutas_view(request):
    """
    Devuelve una lista única y ordenada de todas las rutas existentes 
    en la tabla de Comisiones para usar en los selectores.
    """
    try:
        rutas = models.Comision.objects.values_list('ruta', flat=True).distinct().order_by('ruta')
        # Nos aseguramos de no incluir rutas vacías o nulas
        rutas_validas = [ruta for ruta in rutas if ruta]
        return Response(rutas_validas, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- VISTA 3: ASIGNAR O QUITAR RUTA A UN USUARIO ---
# Este es el equivalente a tu `assign-responsible`. Se ejecuta cada vez que se cambia un selector.
@api_view(['POST'])
def asignar_ruta_view(request):
    """
    Asigna una ruta al Perfil de un usuario. Si la ruta es null, 
    se le quita el rol de asesor.
    """
    user_id = request.data.get('user_id')
    ruta = request.data.get('ruta')

    if not user_id:
        return Response({"error": "El 'user_id' es requerido."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user_a_modificar = User.objects.get(pk=user_id)
        
        # Usamos get_or_create para asegurar que el perfil exista.
        perfil, created = models.Perfil.objects.get_or_create(user=user_a_modificar)
        
        perfil.ruta_asignada = ruta
        perfil.save()
        
        mensaje = f"Ruta '{ruta}' asignada a {user_a_modificar.username}." if ruta else f"Se quitó la ruta y el rol de asesor a {user_a_modificar.username}."
        
        return Response({"mensaje": mensaje}, status=status.HTTP_200_OK)

    except User.DoesNotExist:
        return Response({"error": "El usuario especificado no existe."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": f"Ocurrió un error inesperado: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

ruta = "D:\\Proyectos\\TeamComunicaciones\\pagina\\frontend\\src\\assets"

@api_view(['GET'])
@admin_permission_required
def admin_pago_list(request):
    """
    Devuelve una lista paginada de Pagos
    filtrados para el panel de admin.
    """
    queryset = (
        PagoComision.objects
        .all()
        .select_related('creado_por')
        .prefetch_related('comisiones_pagadas')
    )
    
    ruta = request.query_params.get('ruta')
    punto_de_venta = request.query_params.get('punto_de_venta')
    fecha_inicio = request.query_params.get('fecha_inicio')
    fecha_fin = request.query_params.get('fecha_fin')

    if ruta:
        queryset = queryset.filter(creado_por__perfil__ruta_asignada=ruta)
    
    if punto_de_venta:
        queryset = queryset.filter(punto_de_venta=punto_de_venta)

    if fecha_inicio and fecha_fin:
        try:
            start_date = parse_date(fecha_inicio)
            end_date = parse_date(fecha_fin)
            if start_date and end_date:
                queryset = queryset.filter(fecha_pago__date__range=[start_date, end_date])
        except (ValueError, TypeError):
            pass

    queryset = queryset.order_by('-fecha_pago')
    
    paginator = Paginator(queryset, 10)  # 10 items por página
    page_number = request.query_params.get('page', 1)
    
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    
    serializer = PagoComisionAdminSerializer(page_obj.object_list, many=True)
    
    return Response({
        'count': paginator.count,
        'results': serializer.data,
        'current_page': page_obj.number,
        'total_pages': paginator.num_pages,
    }, status=status.HTTP_200_OK)


@api_view(['PUT', 'DELETE'])
@admin_permission_required
def admin_pago_detail(request, pk):
    """
    PUT: Actualiza un pago de comisiones.
    DELETE: Reversa un pago (borra el PagoComision y reajusta Comision).
    """
    try:
        pago = PagoComision.objects.get(pk=pk)
    except PagoComision.DoesNotExist:
        return Response({'detail': 'Pago no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

    # --- ACTUALIZAR PAGO ---
    if request.method == 'PUT':
        data = request.data or {}
        try:
            monto_str = data.get('monto')
            fecha_pago_str = data.get('fecha_pago')
            metodo_pago_str = data.get('metodo_pago')
            observacion = data.get('observacion', '')

            if not all([monto_str, fecha_pago_str, metodo_pago_str]):
                return Response(
                    {'detail': 'Monto, fecha_pago y metodo_pago son requeridos.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            monto = decimal_or_zero(monto_str)
            if monto <= 0:
                return Response(
                    {'detail': 'El monto debe ser mayor que cero.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            fecha_pago_obj = parse_date(fecha_pago_str)
            if fecha_pago_obj is None:
                return Response(
                    {'detail': 'Formato de fecha inválido (usa YYYY-MM-DD).'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            with transaction.atomic():
                pago.monto_total_pagado = monto
                pago.monto_comisiones = monto
                # Mantiene la hora, cambia solo la fecha
                pago.fecha_pago = pago.fecha_pago.replace(
                    year=fecha_pago_obj.year,
                    month=fecha_pago_obj.month,
                    day=fecha_pago_obj.day
                )
                pago.metodos_pago = {metodo_pago_str: float(monto)}
                pago.observacion = observacion
                pago.save()

            serializer = PagoComisionAdminSerializer(pago)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'detail': f'Error al actualizar: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

    # --- REVERSAR PAGO ---
    elif request.method == 'DELETE':
        """
        Reverso robusto:

        - Comisiones originales (las del Excel) -> estado='Pendiente',
          pagos=None, mes_pago = mes_liquidacion (si existe) o None.

        - Comisiones 'fantasma' creadas por el pago
          (PAGO REGISTRADO, SALDO PENDIENTE, AJUSTE, USO DE SALDO) -> se borran.

        - Luego se elimina el PagoComision.
        """
        try:
            with transaction.atomic():
                comisiones_relacionadas = pago.comisiones_pagadas.all()

                for com in comisiones_relacionadas:
                    if es_comision_ledger(com):
                        # Es un registro artificial ligado al pago → se borra
                        com.delete()
                    else:
                        # Comisión original → se revierte
                        com.estado = 'Pendiente'
                        com.pagos = None

                        # Se devuelve al mes de liquidación original, si existe
                        if com.mes_liquidacion:
                            com.mes_pago = com.mes_liquidacion
                        else:
                            com.mes_pago = None

                        com.save()

                pago.delete()

            return Response(status=status.HTTP_204_NO_CONTENT)

        except Exception as e:
            return Response(
                {'detail': f'Error al reversar el pago: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        
@api_view(['GET'])
@admin_permission_required
def admin_puntos_de_venta_list(request):
    """
    Devuelve una lista de Puntos de Venta (únicos)
    filtrados por una ruta específica.
    Usado para el dropdown dependiente en el admin.
    """
    ruta = request.query_params.get('ruta')
    if not ruta:
        return Response([], status=status.HTTP_200_OK)

    try:
        puntos = (
            Comision.objects
            .filter(ruta=ruta)
            .values_list('punto_de_venta', flat=True)
            .distinct()
            .order_by('punto_de_venta')
        )
        return Response(list(puntos), status=status.HTTP_200_OK)
    except Exception as e:
        return Response(
            {'detail': f'Error al obtener puntos de venta: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
                
@api_view(['GET'])
def filtros_asesor_view(request):
    """
    Devuelve los filtros para el dashboard del asesor.
    Automáticamente filtra por la ruta asignada al usuario.
    """
    try:
        # 1. Obtener la ruta asignada al usuario logueado desde su perfil
        ruta_asesor = request.user.perfil.ruta_asignada
        
        # 2. Si el asesor no tiene una ruta asignada en su perfil, no puede ver el dashboard.
        if not ruta_asesor:
            return Response(
                {"error": "No tienes una ruta asignada para ver este reporte."}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        # 3. Obtener los puntos de venta ÚNICAMENTE de esa ruta
        puntos_de_venta = models.Comision.objects.filter(ruta=ruta_asesor).values(
            'idpos', 'punto_de_venta'
        ).distinct().order_by('punto_de_venta')

        # 4. Devolver un objeto que solo contiene los puntos de venta.
        data = {
            'puntos_de_venta': list(puntos_de_venta)
        }
        return Response(data)

    except models.Perfil.DoesNotExist:
         return Response(
            {"error": "Tu usuario no tiene un perfil de permisos configurado."}, 
            status=status.HTTP_403_FORBIDDEN
         )

# --- DECORADOR DE PERMISOS (LO MANTENEMOS POR SEGURIDAD) ---
@api_view(['POST'])
@cajero_permission_required
def select_datos_corresponsal_cajero(request):
    try:
        # 2. YA NO NECESITAS EL TOKEN, el decorador se encargó de eso.
        #    El usuario autenticado ahora está disponible en 'request.user'.
        fecha_str = request.data['fecha']
        user = request.user  # Obtenemos el usuario directamente de la request

        responsable = models.Responsable_corresponsal.objects.filter(user=user).first()
        if not responsable or not responsable.sucursal:
            return Response({'error': 'Usuario no asignado a una sucursal válida.'}, status=404)
        
        sucursal_terminal = responsable.sucursal.terminal

        sucursal_obj = models.Codigo_oficina.objects.filter(terminal=sucursal_terminal).first()
        if not sucursal_obj:
            return Response({'error': f'El código para la sucursal {sucursal_terminal} no fue encontrado.'}, status=404)
        
        codigo_sucursal = sucursal_obj.codigo
        
        # El resto de tu lógica de fechas y filtros permanece igual.
        if len(fecha_str) == 7:
            # Para un mes completo (YYYY-MM)
            fecha_inicio_naive = datetime.strptime(fecha_str, '%Y-%m')
            fecha_fin_naive = (fecha_inicio_naive + pd.offsets.MonthEnd(1)).to_pydatetime()
        else:
            # Para un día específico (YYYY-MM-DD)
            fecha_dia = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            fecha_inicio_naive = datetime.combine(fecha_dia, time.min)
            fecha_fin_naive = datetime.combine(fecha_dia, time.max)

        fecha_inicio = timezone.make_aware(fecha_inicio_naive)
        fecha_fin = timezone.make_aware(fecha_fin_naive)
        
        transacciones_qs = models.Transacciones_sucursal.objects.filter(
            fecha__range=(fecha_inicio, fecha_fin), 
            codigo_incocredito=codigo_sucursal
        )
        
        total_datos = transacciones_qs.aggregate(total=Sum('valor'))['total'] or 0

        return Response({'total': total_datos, 'sucursal': sucursal_terminal})

    # 3. YA NO NECESITAS 'except User.DoesNotExist', el decorador lo maneja.
    except Exception as e:
        print(f"Error en select_datos_corresponsal_cajero: {str(e)}")
        return Response({'detail': f'Error interno: {str(e)}'}, status=500)
    
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        
        if response.status_code == 200:
            email = request.data.get('email')
            if email:
                try:
                    user = User.objects.get(email=email)
                    user_data = UserDataSerializer(user).data
                    response.data['user'] = user_data
                except User.DoesNotExist:
                    pass
        
        return response
    
@api_view(['GET'])
def consulta_pdv_view(request):
    """
    Busca comisiones por IDPOS y filtros.
    DEVUELVE LAS COMISIONES 'Pagada' AGRUPADAS POR DÍA Y ASESOR.
    """
    idpos_filtro = request.query_params.get('idpos', None)
    
    if not idpos_filtro:
        return Response({
            "totals": {"total_ventas": 0, "total_comisionado": 0},
            "results": []
        })

    # 1. Aplicar todos los filtros iniciales
    queryset = models.Comision.objects.filter(idpos=idpos_filtro)
    
    fecha_inicio_str = request.query_params.get('fecha_inicio', None)
    fecha_fin_str = request.query_params.get('fecha_fin', None)
    estado_filtro = request.query_params.get('estado', None)

    if fecha_inicio_str and fecha_fin_str:
        try:
            queryset = queryset.filter(mes_pago__range=[fecha_inicio_str, fecha_fin_str])
        except ValueError:
            # Ignora fechas inválidas
            pass

    if estado_filtro and estado_filtro != 'Todos':
        queryset = queryset.filter(estado=estado_filtro)

    # 2. Calcular los totales sobre el queryset ya filtrado
    totals = queryset.aggregate(
        total_ventas=Count('id'),
        total_comisionado=Sum('comision_final')
    )

    # 3. Lógica para agrupar las comisiones pagadas
    pagadas_agrupadas = queryset.filter(
        estado='Pagada'
    ).values(
        'mes_pago', 'asesor_identificador', 'mes_liquidacion'
    ).annotate(
        cantidad=Count('id'),
        valor_total=Sum('comision_final')
    ).order_by('-mes_pago')

    # 4. Obtener las demás comisiones (no pagadas)
    otras_comisiones_qs = queryset.exclude(estado='Pagada')
    
    # 5. Unificar y dar formato a los resultados
    resultados = []
    
    # Añadir filas agrupadas
    for item in pagadas_agrupadas:
        resultados.append({
            'id': f"agrupado-{item['mes_pago'].isoformat()}-{item['asesor_identificador']}",
            'agrupado': True,
            'mes_liquidacion': item['mes_liquidacion'],
            'mes_pago': item['mes_pago'],
            # Este campo ahora contiene el resumen
            'asesor_identificador': f"{item['cantidad']} ventas de {item['asesor_identificador']}",
            'comision_final': item['valor_total'],
            'estado': 'Pagada',
        })

    # Añadir filas individuales
    for comision in otras_comisiones_qs:
        resultados.append({
            'id': comision.id,
            'agrupado': False,
            'mes_liquidacion': comision.mes_liquidacion,
            'mes_pago': comision.mes_pago,
            'asesor_identificador': comision.asesor_identificador,
            'comision_final': comision.comision_final,
            'estado': comision.estado,
        })
    
    # 6. Ordenar la lista combinada por fecha de pago
    resultados.sort(key=lambda x: x['mes_pago'] if x['mes_pago'] else date.min, reverse=True)

    # 7. Construir la respuesta final
    # (No se usa paginación para mantener la simplicidad del frontend actual)
    return Response({
        "totals": {
            'total_ventas': totals.get('total_ventas') or 0,
            'total_comisionado': totals.get('total_comisionado') or 0
        },
        "results": resultados
    })
    
# intranet/views.py

# Asegúrate de tener estos imports al principio de tu archivo
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.db.models import Sum, Q
# ... y los demás imports que ya usas

@api_view(['GET'])
@asesor_permission_required
def reporte_comparativa_view(request):
    """
    Genera datos para el gráfico comparativo (mes actual vs anterior).

    Usa mes_liquidacion como referencia de mes.
    Clampea valores negativos a 0 para evitar cosas raras.
    """
    try:
        ruta_asesor = request.user.perfil.ruta_asignada
        if not ruta_asesor:
            return Response(
                {"error": "No tienes una ruta asignada."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        base_queryset = models.Comision.objects.filter(ruta__iexact=ruta_asesor)

        pdv_seleccionados = request.query_params.getlist('pdv', [])
        if not pdv_seleccionados:
            return Response([])

        # Buscar el último mes con mes_liquidacion, si existe
        ultimo_mes_obj = None
        if base_queryset.filter(mes_liquidacion__isnull=False).exists():
            ultimo_mes_obj = base_queryset.filter(mes_liquidacion__isnull=False).latest('mes_liquidacion')

        if ultimo_mes_obj:
            ultimo_mes = ultimo_mes_obj.mes_liquidacion.replace(day=1)
        else:
            ultimo_mes = timezone.now().date().replace(day=1)
        
        # Mes anterior
        if ultimo_mes.month == 1:
            mes_anterior_date = date(ultimo_mes.year - 1, 12, 1)
        else:
            mes_anterior_date = date(ultimo_mes.year, ultimo_mes.month - 1, 1)

        condicion_mes_actual = Q(
            mes_liquidacion__year=ultimo_mes.year,
            mes_liquidacion__month=ultimo_mes.month
        )
        condicion_mes_anterior = Q(
            mes_liquidacion__year=mes_anterior_date.year,
            mes_liquidacion__month=mes_anterior_date.month
        )

        resultados = []

        # TOTAL RUTA
        if 'TOTAL RUTA' in pdv_seleccionados:
            total_ruta = base_queryset.aggregate(
                total_mes_actual=Sum('comision_final', filter=condicion_mes_actual, default=0),
                total_mes_anterior=Sum('comision_final', filter=condicion_mes_anterior, default=0),
            )
            total_actual = decimal_or_zero(total_ruta.get('total_mes_actual'))
            total_anterior = decimal_or_zero(total_ruta.get('total_mes_anterior'))

            if total_actual < 0:
                total_actual = Decimal('0')
            if total_anterior < 0:
                total_anterior = Decimal('0')

            resultados.append({
                'punto_de_venta': 'TOTAL RUTA',
                'total_mes_actual': float(total_actual),
                'total_mes_anterior': float(total_anterior),
            })
            pdv_seleccionados.remove('TOTAL RUTA')

        # Por PDV
        if pdv_seleccionados:
            pdv_detalles = (
                base_queryset
                .filter(punto_de_venta__in=pdv_seleccionados)
                .values('punto_de_venta')
                .annotate(
                    total_mes_actual=Sum('comision_final', filter=condicion_mes_actual, default=0),
                    total_mes_anterior=Sum('comision_final', filter=condicion_mes_anterior, default=0),
                )
                .order_by('punto_de_venta')
            )

            for item in pdv_detalles:
                total_actual = decimal_or_zero(item.get('total_mes_actual'))
                total_anterior = decimal_or_zero(item.get('total_mes_anterior'))

                if total_actual < 0:
                    total_actual = Decimal('0')
                if total_anterior < 0:
                    total_anterior = Decimal('0')

                resultados.append({
                    'punto_de_venta': item['punto_de_venta'],
                    'total_mes_actual': float(total_actual),
                    'total_mes_anterior': float(total_anterior),
                })

        return Response(resultados)

    except models.Perfil.DoesNotExist:
        return Response([])

    
# intranet/views.py

@api_view(['GET'])
# @permission_classes([IsAuthenticated]) # Descomenta para proteger la vista
def consulta_agrupada_pdv_view(request):
    """
    Devuelve las comisiones agrupadas para un IDPOS específico,
    con filtros opcionales por mes y estado, incluyendo la fecha de pago para los grupos pagados.
    """
    idpos = request.query_params.get('idpos')
    if not idpos:
        return Response({"error": "El parámetro 'idpos' es obligatorio."}, status=status.HTTP_400_BAD_REQUEST)

    # Construir el queryset base
    base_queryset = models.Comision.objects.filter(idpos=idpos).exclude(estado='Consolidada')
    
    # Aplicar filtros opcionales
    mes_filtro = request.query_params.get('mes')
    if mes_filtro:
        try:
            fecha_obj = datetime.strptime(mes_filtro, '%Y-%m')
            base_queryset = base_queryset.filter(
                mes_pago__year=fecha_obj.year, 
                mes_pago__month=fecha_obj.month
            )
        except (ValueError, TypeError):
            pass

    estado_filtro = request.query_params.get('estado')
    if estado_filtro and estado_filtro != 'Todos':
        base_queryset = base_queryset.filter(estado=estado_filtro)

    # Calcular KPIs sobre el queryset filtrado (sin cambios)
    kpis_data = base_queryset.aggregate(
        totalPagado=Sum('comision_final', filter=Q(estado='Pagada'), default=0),
        totalPendiente=Sum('comision_final', filter=Q(estado__in=['Pendiente', 'Acumulada']), default=0)
    )
    kpis_data['totalComisiones'] = (kpis_data.get('totalPagado') or 0) + (kpis_data.get('totalPendiente') or 0)

    # CORRECCIÓN: Agrupar resultados y obtener la fecha de pago más reciente del grupo.
    grouped_results = base_queryset.values(
        'mes_pago', 'asesor_identificador', 'producto', 'estado'
    ).annotate(
        comision_final_total=Sum('comision_final'),
        fecha_pago_reciente=Max('pagos__fecha_pago') # Se anota la fecha de pago del grupo
    ).order_by('-mes_pago', 'asesor_identificador')

    # Formatear la salida
    resultados = []
    for item in grouped_results:
        # Se genera un ID único para el frontend, ya que son registros virtuales
        unique_id = f"agrupado-{item['estado']}-{item['mes_pago']}-{item['asesor_identificador']}-{item['producto']}"
        resultados.append({
            'id': unique_id,
            'asesor_identificador': item['asesor_identificador'],
            'producto': item['producto'],
            'comision_final': item['comision_final_total'],
            'estado': item['estado'],
            'mes_pago': item['mes_pago'],
            'fecha_pago': item['fecha_pago_reciente'], # Se usa la fecha anotada
        })

    data = {
        'kpis': kpis_data,
        'results': resultados
    }
    
    return Response(data)


@api_view(['POST'])
@asesor_permission_required
def pagar_comisiones_view(request):
    """
    Procesa el pago de comisiones desde el dashboard del asesor.

    Body:
    {
        "comision_ids": [1,2,3],
        "metodos_pago": {
            "Nequi": 10000,
            "Recarga": 5000,
            "Acumulado": 2000
        }
    }

    Reglas:
      - Solo comisiones en estado Pendiente o Acumulada.
      - agrupa por mismo idpos.
      - Crea un PagoComision.
      - CREA registros 'fantasma' (PAGO REGISTRADO, SALDO PENDIENTE, AJUSTE, USO DE SALDO),
        pero NUNCA con valores negativos.
      - Reversible con admin_pago_detail (DELETE).
    """
    comision_ids = request.data.get('comision_ids', [])
    metodos_pago_original = request.data.get('metodos_pago', {})

    if not comision_ids or not metodos_pago_original:
        return Response(
            {"error": "Faltan datos para procesar el pago."},
            status=status.HTTP_400_BAD_REQUEST
        )

    with transaction.atomic():
        comisiones_a_pagar = (
            models.Comision.objects
            .filter(pk__in=comision_ids, estado__in=['Pendiente', 'Acumulada'])
            .select_for_update()
        )
        
        if not comisiones_a_pagar.exists():
            return Response(
                {"error": "No se encontraron comisiones válidas para pagar."},
                status=status.HTTP_400_BAD_REQUEST
            )

        idpos_unicos = comisiones_a_pagar.values_list('idpos', flat=True).distinct()
        if idpos_unicos.count() > 1:
            return Response(
                {"error": "No se pueden pagar comisiones de diferentes Puntos de Venta a la vez."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        primera_comision = comisiones_a_pagar.first()

        # Total de comisiones a pagar
        monto_comisiones = decimal_or_zero(
            comisiones_a_pagar.aggregate(total=Sum('comision_final'))['total']
        )

        # Normalizar metodos_pago a Decimals y separar Acumulado
        monto_acumulado_usado = decimal_or_zero(
            metodos_pago_original.get('Acumulado', 0)
        )

        monto_real_pagado = Decimal('0')
        metodos_pago_normalizados = {}

        for metodo, valor in metodos_pago_original.items():
            valor_dec = decimal_or_zero(valor)
            if valor_dec <= 0:
                continue
            metodos_pago_normalizados[metodo] = float(valor_dec)
            if metodo != 'Acumulado':
                monto_real_pagado += valor_dec

        total_metodos = monto_real_pagado + monto_acumulado_usado

        if monto_comisiones <= 0:
            return Response(
                {"error": "El total de comisiones es cero o negativo."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if total_metodos <= 0:
            return Response(
                {"error": "El total ingresado en los métodos de pago debe ser mayor a cero."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Creamos el PagoComision
        pago = models.PagoComision.objects.create(
            idpos=primera_comision.idpos,
            punto_de_venta=primera_comision.punto_de_venta,
            creado_por=request.user,
            monto_total_pagado=total_metodos,
            monto_comisiones=monto_comisiones,
            metodos_pago=metodos_pago_normalizados,
        )

        # 1. Consolidar las comisiones originales que se están pagando
        comisiones_a_pagar.update(estado='Consolidada', pagos=pago)

        # Determinar mes de referencia (liquidación) para los registros fantasma
        mes_liq_ref = (
            primera_comision.mes_liquidacion
            or primera_comision.mes_pago
            or timezone.now().date().replace(day=1)
        )

        # 2. Si se usó saldo acumulado, crear un registro para reflejarlo
        if monto_acumulado_usado > 0:
            models.Comision.objects.create(
                idpos=primera_comision.idpos,
                punto_de_venta=primera_comision.punto_de_venta,
                asesor=primera_comision.asesor,
                asesor_identificador=primera_comision.asesor_identificador,
                ruta=primera_comision.ruta,
                mes_pago=mes_liq_ref,
                mes_liquidacion=mes_liq_ref,
                comision_final=monto_acumulado_usado,  # siempre positivo
                estado='Acumulada',
                producto=f"USO DE SALDO EN PAGO #{pago.id}",
                iccid=f"ACUM-{pago.id}",
                pagos=pago,
            )

        # 3. Si se hizo un pago real (efectivo, etc.), crear la comisión 'Pagada'
        if monto_real_pagado > 0:
            models.Comision.objects.create(
                idpos=primera_comision.idpos,
                punto_de_venta=primera_comision.punto_de_venta,
                asesor=primera_comision.asesor,
                asesor_identificador=primera_comision.asesor_identificador,
                ruta=primera_comision.ruta,
                mes_pago=mes_liq_ref,
                mes_liquidacion=mes_liq_ref,
                comision_final=monto_real_pagado,  # positivo
                estado='Pagada',
                producto=f"PAGO REGISTRADO #{pago.id}",
                iccid=f"PAGO-{pago.id}",
                pagos=pago,
            )
        
        # 4. Calcular el balance final y crear comisión de saldo si es necesario
        restante = monto_comisiones - total_metodos

        if restante > 0:
            # Saldo faltante -> PENDIENTE positiva
            models.Comision.objects.create(
                idpos=primera_comision.idpos,
                punto_de_venta=primera_comision.punto_de_venta,
                asesor=primera_comision.asesor,
                asesor_identificador=primera_comision.asesor_identificador,
                ruta=primera_comision.ruta,
                mes_pago=mes_liq_ref,
                mes_liquidacion=mes_liq_ref,
                comision_final=restante,  # positivo
                estado='Pendiente',
                producto=f"SALDO PENDIENTE PAGO #{pago.id}",
                iccid=f"SALDO-{pago.id}",
                pagos=pago,
            )
        elif restante < 0:
            # Hubo un sobrepago -> ACUMULADA (crédito a favor) POSITIVA
            sobrante = abs(restante)
            models.Comision.objects.create(
                idpos=primera_comision.idpos,
                punto_de_venta=primera_comision.punto_de_venta,
                asesor=primera_comision.asesor,
                asesor_identificador=primera_comision.asesor_identificador,
                ruta=primera_comision.ruta,
                mes_pago=mes_liq_ref,
                mes_liquidacion=mes_liq_ref,
                comision_final=sobrante,  # positivo
                estado='Acumulada',
                producto=f"AJUSTE POR SOBRANTE PAGO #{pago.id}",
                iccid=f"AJUSTE-{pago.id}",
                pagos=pago,
            )
            
    return Response({"mensaje": "Pago procesado con éxito."}, status=status.HTTP_200_OK)


@api_view(['GET'])
# @permission_classes([IsAuthenticated]) # Descomenta para proteger la vista
def consulta_agrupada_pdv_view(request):
    """
    Devuelve las comisiones agrupadas para un IDPOS específico,
    con filtros opcionales por mes y estado, incluyendo la fecha de pago para los grupos pagados.
    """
    idpos = request.query_params.get('idpos')
    if not idpos:
        return Response({"error": "El parámetro 'idpos' es obligatorio."}, status=status.HTTP_400_BAD_REQUEST)

    # Construir el queryset base
    base_queryset = models.Comision.objects.filter(idpos=idpos).exclude(estado='Consolidada')
    
    # Aplicar filtros opcionales
    mes_filtro = request.query_params.get('mes')
    if mes_filtro:
        try:
            fecha_obj = datetime.strptime(mes_filtro, '%Y-%m')
            base_queryset = base_queryset.filter(
                mes_pago__year=fecha_obj.year, 
                mes_pago__month=fecha_obj.month
            )
        except (ValueError, TypeError):
            pass

    estado_filtro = request.query_params.get('estado')
    if estado_filtro and estado_filtro != 'Todos':
        base_queryset = base_queryset.filter(estado=estado_filtro)

    # Calcular KPIs sobre el queryset filtrado (sin cambios)
    kpis_data = base_queryset.aggregate(
        totalPagado=Sum('comision_final', filter=Q(estado='Pagada'), default=0),
        totalPendiente=Sum('comision_final', filter=Q(estado__in=['Pendiente', 'Acumulada']), default=0)
    )
    kpis_data['totalComisiones'] = (kpis_data.get('totalPagado') or 0) + (kpis_data.get('totalPendiente') or 0)

    # CORRECCIÓN: Agrupar resultados y obtener la fecha de pago más reciente del grupo.
    grouped_results = base_queryset.values(
        'mes_pago', 'asesor_identificador', 'producto', 'estado'
    ).annotate(
        comision_final_total=Sum('comision_final'),
        fecha_pago_reciente=Max('pagos__fecha_pago') # Se anota la fecha de pago del grupo
    ).order_by('-mes_pago', 'asesor_identificador')

    # Formatear la salida
    resultados = []
    for item in grouped_results:
        # Se genera un ID único para el frontend, ya que son registros virtuales
        unique_id = f"agrupado-{item['estado']}-{item['mes_pago']}-{item['asesor_identificador']}-{item['producto']}"
        resultados.append({
            'id': unique_id,
            'asesor_identificador': item['asesor_identificador'],
            'producto': item['producto'],
            'comision_final': item['comision_final_total'],
            'estado': item['estado'],
            'mes_pago': item['mes_pago'],
            'fecha_pago': item['fecha_pago_reciente'], # Se usa la fecha anotada
        })

    data = {
        'kpis': kpis_data,
        'results': resultados
    }
    
    return Response(data)

@api_view(['GET'])
@asesor_permission_required # Descomenta si usas este decorador
def reporte_general_view(request):
    """
    Genera un reporte general de comisiones con filtros dinámicos para el dashboard de administración.
    --- VERSIÓN ACTUALIZADA PARA INCLUIR ESTADO 'VENCIDA' ---
    """
    # 1. Leer los parámetros de la URL
    fecha_inicio_str = request.query_params.get('fecha_inicio')
    fecha_fin_str = request.query_params.get('fecha_fin')
    rutas_filter = request.query_params.getlist('rutas')
    estados_filter = request.query_params.getlist('estados')

    # 2. Construir el queryset base
    base_queryset = models.Comision.objects.exclude(estado='Consolidada')

    # 3. Aplicar filtros dinámicamente
    if fecha_inicio_str and fecha_fin_str:
        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            base_queryset = base_queryset.filter(mes_pago__range=[fecha_inicio, fecha_fin])
        except (ValueError, TypeError):
            pass

    if rutas_filter:
        base_queryset = base_queryset.filter(ruta__in=rutas_filter)

    if estados_filter:
        base_queryset = base_queryset.filter(estado__in=estados_filter)

    # 4. Calcular los KPIs
    kpis_data = base_queryset.aggregate(
        pagado=Sum('comision_final', filter=Q(estado='Pagada'), default=0),
        pendiente=Sum('comision_final', filter=Q(estado__in=['Pendiente', 'Acumulada']), default=0),
        vencido=Sum('comision_final', filter=Q(estado='Vencida'), default=0)
    )
    
    total_comisiones = (kpis_data.get('pagado') or 0) + (kpis_data.get('pendiente') or 0) + (kpis_data.get('vencido') or 0)

    # 5. Preparar datos para las gráficas
    evolucion_mensual = base_queryset.annotate(month=TruncMonth('mes_pago')).values('month').annotate(
        pagado=Sum('comision_final', filter=Q(estado='Pagada'), default=0),
        pendiente=Sum('comision_final', filter=Q(estado__in=['Pendiente', 'Acumulada', 'Vencida']), default=0)
    ).order_by('month')

    evolucion_chart_data = [
        {"mes": item['month'].strftime('%Y-%m') if item['month'] else 'Sin Fecha', "pagado": item['pagado'], "pendiente": item['pendiente']}
        for item in evolucion_mensual
    ]

    distribucion_estado = base_queryset.values('estado').annotate(total=Sum('comision_final')).order_by('estado')

    # Lógica de métodos de pago
    pagos_ids = base_queryset.exclude(pagos__isnull=True).values_list('pagos_id', flat=True).distinct()
    pagos_filtrados = models.PagoComision.objects.filter(id__in=pagos_ids)
    valor_por_metodo = defaultdict(float)
    cantidad_por_metodo = defaultdict(int)

    for pago in pagos_filtrados:
        if isinstance(pago.metodos_pago, dict):
            for metodo, valor in pago.metodos_pago.items():
                valor_por_metodo[metodo] += float(valor)
                cantidad_por_metodo[metodo] += 1
    
    reporte_metodos_pago = [
        {'metodo': metodo, 'total_valor': total_valor, 'total_cantidad': cantidad_por_metodo.get(metodo, 0)}
        for metodo, total_valor in valor_por_metodo.items()
    ]

    # 6. Construir la respuesta final (con la corrección aplicada)
    data = {
        "kpis": {
            "total": total_comisiones,
            "pagado": kpis_data.get('pagado') or 0,
            "pendiente": kpis_data.get('pendiente') or 0,
            "vencido": kpis_data.get('vencido') or 0
        },
        "charts": {
            "evolucion_mensual": evolucion_chart_data,
            "distribucion_estado": list(distribucion_estado),
            # Se pasa 'evolucion_chart_data' directamente, ya que contiene 'pagado'
            "picos_mensuales": evolucion_chart_data,
            "metodos_pago": reporte_metodos_pago
        }
    }
    
    return Response(data)

logger = logging.getLogger(__name__)
@api_view(['GET'])
@asesor_permission_required
def exportar_reporte_excel(request):
    """
    Genera y devuelve un archivo XLSX con el detalle de las comisiones filtradas.
    Esta versión está optimizada para bajo consumo de memoria, creando el archivo
    fila por fila directamente, sin usar pandas.
    """
    try:
        # 1. Lógica de filtrado (sin cambios)
        logger.info("Iniciando la exportación de reporte XLSX optimizado.")
        fecha_inicio_str = request.GET.get('fecha_inicio')
        fecha_fin_str = request.GET.get('fecha_fin')
        rutas_filter = request.GET.getlist('rutas')
        estados_filter = request.GET.getlist('estados')

        base_queryset = models.Comision.objects.exclude(estado='Consolidada').select_related('pagos')

        if fecha_inicio_str and fecha_fin_str:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            base_queryset = base_queryset.filter(mes_pago__range=[fecha_inicio, fecha_fin])
        
        if rutas_filter:
            base_queryset = base_queryset.filter(ruta__in=rutas_filter)
        if estados_filter:
            base_queryset = base_queryset.filter(estado__in=estados_filter)
        
        # 2. Preparación de la respuesta HTTP para XLSX
        filename = f"Reporte_Comisiones_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )
        
        # 3. Creación del Excel en modo "write-only" para bajo consumo de memoria
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Detalle Comisiones")
        
        # Escribimos la fila de encabezados
        column_headers = [
            'Mes Pago', 'Mes Liquidación', 'Fecha de Pago', 'Asesor', 'Ruta', 'ID POS',
            'Punto de Venta', 'Producto', 'ICCID', 'MIN', 'Valor Comisión', 'Estado', 
            'Metodos de Pago', 'Fecha de Carga Original'
        ]
        ws.append(column_headers)

        # Usamos .iterator() para un consumo de memoria mínimo en la base de datos
        comisiones = base_queryset.order_by('pk').iterator()

        # Función auxiliar para convertir datetimes "aware" a "naive"
        def make_naive(value):
            if hasattr(value, 'tzinfo') and value.tzinfo is not None:
                return value.replace(tzinfo=None)
            return value

        for comision in comisiones:
            # Procesamos los métodos de pago si existen
            metodos_pago_str = ''
            if comision.pagos and comision.pagos.metodos_pago and isinstance(comision.pagos.metodos_pago, dict):
                metodos_pago_str = ', '.join([f"{k}: {v}" for k, v in comision.pagos.metodos_pago.items()])

            # Creamos la lista de datos para la fila, asegurando que los datetimes sean "naive"
            row_data = [
                make_naive(comision.mes_pago),
                make_naive(comision.mes_liquidacion),
                make_naive(comision.pagos.fecha_pago if comision.pagos else None),
                comision.asesor_identificador,
                comision.ruta,
                comision.idpos,
                comision.punto_de_venta,
                comision.producto,
                comision.iccid,
                comision.min,
                comision.comision_final,
                comision.estado,
                metodos_pago_str,
                make_naive(comision.fecha_carga)
            ]
            # Escribimos la fila directamente en el archivo
            ws.append(row_data)

        # Guardamos el libro de trabajo virtual directamente en la respuesta HTTP
        wb.save(response)

        logger.info(f"Reporte XLSX '{filename}' generado y enviado exitosamente.")
        return response

    except Exception as e:
        logger.error(f"Error al generar el reporte de Excel: {e}", exc_info=True)
        return JsonResponse(
            {'error': 'Ocurrió un error inesperado al generar el archivo.', 'details': str(e)}, 
            status=500
        )


@api_view(['GET', 'POST'])
@asesor_permission_required# ¡Protege esta vista! Solo los admins deben poder cambiar esto.
def fecha_corte_view(request):
    """
    Obtiene o establece el día del mes para la fecha de corte de comisiones.
    """
    CLAVE_CONFIG = 'FECHA_CORTE_DIA'
    
    if request.method == 'GET':
        # get_or_create asegura que siempre tengamos un valor, creando uno por defecto si no existe.
        config, _ = models.Configuracion.objects.get_or_create(
            clave=CLAVE_CONFIG,
            defaults={'valor': '25'}  # Puedes poner un valor por defecto, como el día 25.
        )
        return Response({'dia': config.valor})

    elif request.method == 'POST':
        nuevo_dia = request.data.get('dia')
        
        # Validación robusta
        if not nuevo_dia or not str(nuevo_dia).isdigit() or not (1 <= int(nuevo_dia) <= 31):
            return Response(
                {'error': 'El valor proporcionado es inválido. Debe ser un número entre 1 y 31.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # update_or_create es eficiente: actualiza el valor si la clave existe, o la crea si no.
        config, _ = models.Configuracion.objects.update_or_create(
            clave=CLAVE_CONFIG,
            defaults={'valor': str(nuevo_dia)}
        )
        
        return Response({'mensaje': f'Fecha de corte actualizada correctamente al día {nuevo_dia} de cada mes.'})


@api_view(['GET'])
@asesor_permission_required
def reporte_asesor_view(request):
    """
    Genera el reporte para el asesor.

    Filtros:
      - mes: YYYY-MM
      - idpos: opcional

    Reglas:
      - Usa la ruta del Perfil del usuario.
      - Excluye comisiones 'Consolidada' (ya consolidadas en pagos).
      - KPIs y gráficas imposibles de negativos (se clampean a >= 0).
    """
    try:
        # 1. Perfil y ruta
        perfil, created = models.Perfil.objects.get_or_create(user=request.user)
        ruta_asesor = perfil.ruta_asignada
        if not ruta_asesor:
            return Response(
                {"error": "No tienes una ruta asignada en tu perfil."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # 2. Query base: por ruta, excluyendo 'Consolidada'
        base_queryset = (
            models.Comision.objects
            .filter(ruta__iexact=ruta_asesor)
            .exclude(estado='Consolidada')
        )

        # 3. Filtros
        idpos_filtro = request.query_params.get('idpos')
        mes_filtro = request.query_params.get('mes')

        queryset_con_filtros = base_queryset

        # Cambiamos a mes_liquidacion como referencia temporal
        if mes_filtro:
            try:
                fecha_obj = datetime.strptime(mes_filtro, '%Y-%m').date()
                queryset_con_filtros = queryset_con_filtros.filter(
                    mes_liquidacion__year=fecha_obj.year,
                    mes_liquidacion__month=fecha_obj.month
                )
            except (ValueError, TypeError):
                pass
        
        if idpos_filtro and idpos_filtro != 'todos':
            queryset_con_filtros = queryset_con_filtros.filter(idpos=idpos_filtro)

        # 4. Agrupación para la tabla
        grouped_results = queryset_con_filtros.values(
            'mes_pago', 'asesor_identificador', 'producto', 'estado'
        ).annotate(
            cantidad=Count('id'),
            comision_final_total=Sum('comision_final'),
            individual_ids=Coalesce(ArrayAgg('id', distinct=True), Value([]))
        ).order_by('-mes_pago', 'asesor_identificador')

        resultados = []
        for item in grouped_results:
            if not item['cantidad']:
                continue

            unique_id = (
                f"agrupado-{item['estado']}-"
                f"{item['mes_pago']}-"
                f"{item['asesor_identificador']}-"
                f"{item['producto']}"
            )

            resultados.append({
                'id': unique_id,
                'agrupado': True,
                'asesor_identificador': item['asesor_identificador'],
                'iccid': f"{item['cantidad']} ventas",
                'producto': item['producto'],
                'comision_final': item['comision_final_total'] or 0,
                'estado': item['estado'],
                'mes_pago': item['mes_pago'],
                'individual_ids': item['individual_ids'],
            })

        paginator = PageNumberPagination()
        paginator.page_size = 20
        paginated_results = paginator.paginate_queryset(resultados, request)
        detalle_final = paginator.get_paginated_response(paginated_results).data

        # 5. KPIs y distribución
        kpis_raw = queryset_con_filtros.aggregate(
            total_pagado=Sum('comision_final', filter=Q(estado='Pagada'), default=0),
            total_pendiente=Sum('comision_final', filter=Q(estado__in=['Pendiente', 'Acumulada']), default=0),
        )

        total_pagado = decimal_or_zero(kpis_raw.get('total_pagado'))
        total_pendiente = decimal_or_zero(kpis_raw.get('total_pendiente'))

        # Evitar negativos por ajustes viejos
        if total_pagado < 0:
            total_pagado = Decimal('0')
        if total_pendiente < 0:
            total_pendiente = Decimal('0')

        total_comisiones = total_pagado + total_pendiente

        distribucion_estado_qs = (
            queryset_con_filtros
            .values('estado')
            .annotate(count=Count('id'))
            .order_by('estado')
        )

        distribucion_estado = list(distribucion_estado_qs)

        # --- Métodos de pago (solo pagos ligados al queryset filtrado) ---
        pago_ids = queryset_con_filtros.filter(
            estado='Pagada',
            pagos__isnull=False
        ).values_list('pagos_id', flat=True).distinct()

        pagos_relevantes = models.PagoComision.objects.filter(id__in=pago_ids)

        aggregated_methods = defaultdict(lambda: {'total_valor': Decimal('0'), 'total_cantidad': 0})

        for pago in pagos_relevantes:
            if isinstance(pago.metodos_pago, dict):
                for metodo, valor in pago.metodos_pago.items():
                    valor_dec = decimal_or_zero(valor)
                    aggregated_methods[metodo]['total_valor'] += valor_dec
                    aggregated_methods[metodo]['total_cantidad'] += 1

        metodos_pago_stats = [
            {
                'metodo': metodo,
                'total_valor': float(max(data['total_valor'], Decimal('0'))),
                'total_cantidad': max(data['total_cantidad'], 0),
            }
            for metodo, data in aggregated_methods.items()
        ]
        metodos_pago_stats.sort(key=lambda x: x['total_valor'], reverse=True)

        # 6. Respuesta final
        data = {
            'kpis': {
                'totalPagado': float(total_pagado),
                'totalPendiente': float(total_pendiente),
                'totalComisiones': float(total_comisiones),
            },
            'detalle': detalle_final,
            'chart_data': {
                'distribucion_estado': distribucion_estado,
                'metodos_pago': metodos_pago_stats,
            }
        }
        return Response(data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response(
            {"error": f"Ha ocurrido un error inesperado: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    
@api_view(['GET'])
@asesor_permission_required
def filtros_reporte_view(request):
    """
    Devuelve los filtros para el dashboard del asesor.
    Automáticamente filtra por la ruta asignada al usuario.
    """
    try:
        # 1. Obtener la ruta asignada al usuario logueado desde su perfil
        ruta_asesor = request.user.perfil.ruta_asignada
        
        # 2. Si el asesor no tiene una ruta asignada en su perfil, no puede ver el dashboard.
        if not ruta_asesor:
            return Response(
                {"error": "No tienes una ruta asignada para ver este reporte."}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        # 3. Obtener los puntos de venta ÚNICAMENTE de esa ruta
        puntos_de_venta = models.Comision.objects.filter(ruta=ruta_asesor).values(
            'idpos', 'punto_de_venta'
        ).distinct().order_by('punto_de_venta')

        # 4. Devolver un objeto que solo contiene los puntos de venta.
        data = {
            'puntos_de_venta': list(puntos_de_venta)
        }
        return Response(data)

    except models.Perfil.DoesNotExist:
         return Response(
            {"error": "Tu usuario no tiene un perfil de permisos configurado."}, 
            status=status.HTTP_403_FORBIDDEN
         )

@api_view(['GET'])
@asesor_permission_required
def pdv_por_ruta_view(request):
    """Devuelve los puntos de venta que existen para una ruta específica."""
    ruta_seleccionada = request.query_params.get('ruta', None)
    queryset = Comision.objects.values('idpos', 'punto_de_venta').distinct()
    if ruta_seleccionada and ruta_seleccionada != 'todas':
        queryset = queryset.filter(ruta=ruta_seleccionada)
    puntos_de_venta = queryset.order_by('punto_de_venta')
    return Response(list(puntos_de_venta))




@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@token_required # The decorator handles authentication and provides request.user
def formulas_prices(request, id=None):
    """
    Manages CRUD operations for Formulas.
    Authentication is handled by the @token_required decorator.
    """
    
    # --- GET Method: Fetch one or all formulas ---
    if request.method == 'GET':
        if id is not None:
            # Fetch a single formula by its ID
            try:
                formula = models.Formula.objects.select_related('price_id').get(id=id)
                response_data = {
                    'id': formula.id, 
                    'name': formula.nombre, 
                    'price': formula.price_id.permiso if formula.price_id else None,
                    'price_id': formula.price_id.id if formula.price_id else None,
                    'formula': formula.formula
                }
                return Response({'data': response_data})
            except models.Formula.DoesNotExist:
                return Response({'error': f'No existe una fórmula con el ID {id}'}, status=404)
        else:
            # Fetch all formulas
            formulas = models.Formula.objects.select_related('price_id').all().order_by('nombre')
            data_list = []
            for item in formulas:
                try:
                    # Safely evaluate the string representation of a list
                    formula_str = ' '.join(ast.literal_eval(item.formula)) if item.formula and item.formula.strip().startswith('[') else item.formula
                except (ValueError, SyntaxError):
                    # If it's not a list-like string, just use it as is
                    formula_str = item.formula

                data_list.append({
                    'id': item.id, 
                    'name': item.nombre, 
                    'price': item.price_id.permiso if item.price_id else None,
                    'price_id': item.price_id.id if item.price_id else None,
                    'formula': formula_str
                })
            return Response({'data': data_list})

    # --- POST Method: Create a new formula ---
    elif request.method == 'POST':
        name = request.data.get('name')
        price_id = request.data.get('price')
        formula_str = request.data.get('formula')

        if not all([name, price_id, formula_str]):
            return Response({'error': 'Los campos "name", "price" y "formula" son requeridos.'}, status=400)

        try:
            price_instance = models.Permisos_precio.objects.get(id=price_id)
            
            # The decorator provides request.user
            new_formula = models.Formula.objects.create(
                nombre=name, 
                price_id=price_instance, 
                formula=formula_str, 
                usuario=request.user
            )
            return Response({'data': 'Creación exitosa', 'id': new_formula.id}, status=201)
        except models.Permisos_precio.DoesNotExist:
            return Response({'error': f'El precio con ID {price_id} no existe.'}, status=400)
        except Exception as e:
            return Response({'error': f'No se pudo crear la fórmula: {str(e)}'}, status=400)

    # --- PUT Method: Update an existing formula ---
    elif request.method == 'PUT':
        if id is None:
            return Response({'error': 'El id es requerido en la URL para actualizar.'}, status=400)

        try:
            instance = models.Formula.objects.get(id=id)
            
            instance.nombre = request.data.get('name', instance.nombre)
            instance.formula = request.data.get('formula', instance.formula)
            
            # Update related price if a new one is provided
            new_price_id = request.data.get('price')
            if new_price_id:
                try:
                    price_instance = models.Permisos_precio.objects.get(id=new_price_id)
                    instance.price_id = price_instance
                except models.Permisos_precio.DoesNotExist:
                    return Response({'error': f'El nuevo precio con ID {new_price_id} no existe.'}, status=400)
            
            instance.save()
            return Response({'data': 'Edición exitosa'})
        except models.Formula.DoesNotExist:
            return Response({'error': f'La fórmula con ID {id} no existe.'}, status=404)
        except Exception as e:
            return Response({'error': f'No se pudo actualizar la fórmula: {str(e)}'}, status=400)

    # --- DELETE Method: Remove a formula ---
    elif request.method == 'DELETE':
        if id is None:
            return Response({'error': 'El id es requerido en la URL para eliminar.'}, status=400)
            
        try:
            formula_to_delete = models.Formula.objects.get(id=id)
            formula_to_delete.delete()
            return Response({'data': f'La fórmula con ID {id} fue eliminada exitosamente.'})
        except models.Formula.DoesNotExist:
            return Response({'error': f'La fórmula con ID {id} no existe.'}, status=404)
        except Exception as e:
            return Response({'error': f'No se pudo eliminar la fórmula: {str(e)}'}, status=400)
    
    


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@asesor_permission_required
def carga_comisiones_view(request):
    """
    Gestiona la subida y validación de archivos Excel para comisiones.
    --- CORREGIDO para manejar meses en español ---
    """
    
    # === SECCIÓN 1: CHEQUEO DE PERMISOS ===
    if not models.Permisos_usuarios.objects.filter(
        user=request.user, 
        permiso__permiso='admin_comisiones', 
        tiene_permiso=True
    ).exists():
        return Response(
            {'error': 'No tienes permiso para realizar esta acción.'}, 
            status=status.HTTP_403_FORBIDDEN
        )

    # === SECCIÓN 2: VALIDACIÓN INICIAL DEL ARCHIVO ===
    archivo = request.FILES.get('file')
    if not archivo:
        return Response({'error': 'No se proporcionó ningún archivo.'}, status=status.HTTP_400_BAD_REQUEST)

    # <--- 2. INICIO DEL BLOQUE DE LOCALE ---
    # Guardamos la configuración de idioma actual para restaurarla después
    current_locale = locale.getlocale(locale.LC_TIME)
    try:
        # Intentamos configurar el idioma a español (para Linux/macOS y Windows)
        try:
            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
        except locale.Error:
            locale.setlocale(locale.LC_TIME, 'Spanish')

        # === SECCIÓN 3: VALIDACIÓN DE CONTENIDO DEL EXCEL ===
        # Todo el bloque de validación de pandas va dentro del try del locale
        try:
            xls = pd.ExcelFile(archivo)

            # REGLA 1: Debe tener exactamente una hoja.
            if len(xls.sheet_names) != 1:
                return Response(
                    {'errores': [f'Archivo rechazado: Debe contener exactamente una hoja, pero se encontraron {len(xls.sheet_names)}.']},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            df = pd.read_excel(xls, sheet_name=0, dtype=str)

            # REGLA 2: La columna 'MES LIQUIDACIÓN' es obligatoria.
            if 'MES LIQUIDACIÓN' not in df.columns:
                return Response(
                    {'errores': ['Archivo rechazado: Falta la columna obligatoria "MES LIQUIDACIÓN".']},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # REGLA 3: Todos los registros deben pertenecer a un único mes.
            # Esta línea ahora funcionará correctamente con meses en español.
            meses = pd.to_datetime(df['MES LIQUIDACIÓN'], format='%B %Y', errors='coerce').dt.to_period('M')
            
            meses_unicos = meses.dropna().nunique()

            if meses_unicos > 1:
                return Response(
                    {'errores': [f'Archivo rechazado: Solo se permite un mes por archivo, pero se encontraron {meses_unicos} meses diferentes.']},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if meses_unicos == 0:
                return Response(
                    {'errores': ['Archivo rechazado: No se encontraron registros con un formato de mes válido (Ej: "octubre 2025").']},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            return Response(
                {'errores': [f'No se pudo leer el archivo. Verifique que sea un formato Excel (.xlsx) válido.']},
                status=status.HTTP_400_BAD_REQUEST
            )

    finally:
        # <--- 3. RESTAURACIÓN DEL LOCALE ---
        # Es crucial restaurar la configuración de idioma original para no afectar otras partes de la app.
        locale.setlocale(locale.LC_TIME, current_locale)
    
    # === SECCIÓN 4: GUARDADO Y EJECUCIÓN DE TAREA ASÍNCRONA ===
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as temp_f:
        archivo.seek(0) 
        for chunk in archivo.chunks():
            temp_f.write(chunk)
        file_path = temp_f.name

    procesar_archivo_comisiones.delay(file_path, request.user.id)

    return Response(
        {'mensaje': 'Archivo validado y aceptado. El procesamiento ha comenzado en segundo plano.'}, 
        status=status.HTTP_202_ACCEPTED
    )

    

@swagger_auto_schema(
    method='get',
    manual_parameters=[
        openapi.Parameter('Authorization', openapi.IN_HEADER, description="Token de autenticación", type=openapi.TYPE_STRING),
        openapi.Parameter('id', openapi.IN_QUERY, description="ID de la acta (opcional)", type=openapi.TYPE_INTEGER)
    ]
)
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def actas_entrega(request, id=None):
    try:
        paginator = PageNumberPagination()
        paginator.page_size = 10

        if request.method == 'GET':
            if id:
                acta = get_object_or_404(
                    ActaEntrega.objects.prefetch_related(
                        Prefetch('actaobjetivo_set'),
                        Prefetch('actaobservacion_set'),
                        Prefetch('actarecibidopor_set'),
                        Prefetch('actaarchivo_set')
                    ), 
                    id=id
                )
                serializer = ActaEntregaSerializer(acta)
                return Response(serializer.data)
            else:
                actas = ActaEntrega.objects.all().order_by('-created_at')
                result_page = paginator.paginate_queryset(actas, request)
                serializer = ActaEntregaSerializer(result_page, many=True)
                return paginator.get_paginated_response(serializer.data)

        elif request.method == 'POST':
            serializer = ActaEntregaSerializer(data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response({'message': 'Acta creada exitosamente', 'data': serializer.data}, status=201)
            return Response({'errors': serializer.errors}, status=400)

        elif request.method == 'PUT':
            if not id:
                return Response({'error': 'ID requerido para actualizar'}, status=400)
            acta = get_object_or_404(ActaEntrega, id=id)
            serializer = ActaEntregaSerializer(acta, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response({'message': 'Acta actualizada correctamente', 'data': serializer.data})
            return Response({'errors': serializer.errors}, status=400)

        elif request.method == 'DELETE':
            if not id:
                return Response({'error': 'ID requerido para eliminar'}, status=400)
            acta = get_object_or_404(ActaEntrega, id=id)
            acta.delete()
            return Response({'message': 'Acta eliminada exitosamente'}, status=204)

    except Exception as e:
        return Response({'error': str(e)}, status=500)

@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@token_required # Apply the decorator to handle authentication
def variables_prices(request, id=None):
    """
    Manages CRUD operations for Variables.
    Authentication is now handled by the @token_required decorator.
    """

    # --- GET Method: Fetch one or all variables ---
    if request.method == 'GET':
        if id is not None:
            try:
                data = models.Variables_prices.objects.select_related('price').get(id=id)
                return Response({
                    'data': {
                        'id': data.id, 
                        'name': data.name, 
                        'price': data.price.permiso if data.price else None,
                        'price_id': data.price.id if data.price else None,
                        'formula': data.formula
                    }
                })
            except models.Variables_prices.DoesNotExist:
                return Response({'error': f'No existe una variable con el ID {id}'}, status=404)
        else:
            data = models.Variables_prices.objects.select_related('price').all().order_by('name')
            data_list = [{
                'id': i.id, 
                'name': i.name, 
                'price': i.price.permiso if i.price else None,
                'price_id': i.price.id if i.price else None,
                'formula': i.formula
            } for i in data]
            return Response({'data': data_list})

    # --- POST Method: Create a new variable ---
    elif request.method == 'POST':
        name = request.data.get('name')
        price_id = request.data.get('price')
        formula = request.data.get('formula')

        if not all([name, price_id, formula]):
             return Response({'error': 'Los campos "name", "price" y "formula" son requeridos.'}, status=400)
        
        try:
            price_instance = models.Permisos_precio.objects.get(id=price_id)
            models.Variables_prices.objects.create(name=name, price=price_instance, formula=formula)
            return Response({'data': 'Variable creada exitosamente'}, status=201)
        except models.Permisos_precio.DoesNotExist:
            return Response({'error': f'El precio con ID {price_id} no existe.'}, status=400)
        except Exception as e:
            return Response({'error': f'Ocurrió un error inesperado: {str(e)}'}, status=400)

    # --- PUT Method: Update an existing variable ---
    elif request.method == 'PUT':
        if id is None:
            return Response({'error': 'El ID de la variable es requerido para actualizar.'}, status=400)
        
        try:
            variable_instance = models.Variables_prices.objects.get(id=id)
            
            variable_instance.name = request.data.get('name', variable_instance.name)
            variable_instance.formula = request.data.get('formula', variable_instance.formula)

            new_price_id = request.data.get('price')
            if new_price_id:
                try:
                    price_instance = models.Permisos_precio.objects.get(id=new_price_id)
                    variable_instance.price = price_instance
                except models.Permisos_precio.DoesNotExist:
                    return Response({'error': f'El precio con ID {new_price_id} no existe.'}, status=400)
            
            variable_instance.save()
            return Response({'data': 'Variable actualizada exitosamente'})

        except models.Variables_prices.DoesNotExist:
            return Response({'error': f'La variable con ID {id} no existe.'}, status=404)
        except Exception as e:
            return Response({'error': f'Ocurrió un error inesperado: {str(e)}'}, status=500)

    # --- DELETE Method: Remove a variable ---
    elif request.method == 'DELETE':
        if id is not None:
            try:
                data = models.Variables_prices.objects.get(id=id)
                data.delete()
                return Response({'data': f'La variable con ID {id} fue eliminada exitosamente.'})
            except models.Variables_prices.DoesNotExist:
                return Response({'error': 'La variable no existe.'}, status=404)
            except Exception as e:
                return Response({'error': f'No se pudo eliminar la variable: {str(e)}'}, status=400)
        else:
            return Response({'error': 'El campo id es requerido en la URL.'}, status=400)

@api_view(['GET', 'POST', 'PUT' ,'DELETE'])
@token_required # <-- APLICA EL NUEVO DECORADOR
def prices(request, id=None):
    # Ya no hay código de autenticación aquí. ¡Más limpio!
    # Si la ejecución llega a este punto, el token es válido y request.user existe.
    
    if request.method == 'GET':
        if id is not None:
            try:
                data = models.Permisos_precio.objects.get(id=id)
                return Response({'data': {'id': data.id, 'name': data.permiso, 'state': data.active}})
            except models.Permisos_precio.DoesNotExist:
                return Response({'error': f'No existe un precio con el ID {id}'}, status=404)
        else:
            data = models.Permisos_precio.objects.all().order_by('permiso')
            data_list = [{'id': i.id, 'name': i.permiso, 'state': i.active} for i in data]
            return Response({'data': data_list})

    elif request.method == 'POST':
        name = request.data.get('name')
        state = request.data.get('state', False)
        
        if not name:
            return Response({'error': 'El campo "name" es requerido'}, status=400)
            
        models.Permisos_precio.objects.create(permiso=name, active=state)
        return Response({'data': 'Creación exitosa'}, status=201)

    elif request.method == 'PUT':
        if id is None:
            return Response({'error': 'El id es requerido en la URL para actualizar'}, status=400)
        
        try:
            instance = models.Permisos_precio.objects.get(id=id)
            instance.permiso = request.data.get('name', instance.permiso)
            
            state_str = str(request.data.get('state', instance.active)).lower()
            instance.active = state_str in ['true', '1']
            
            instance.save()
            return Response({'data': 'Edición exitosa'})
        except models.Permisos_precio.DoesNotExist:
            return Response({'error': 'El precio no existe'}, status=404)

    elif request.method == 'DELETE':
        if id is None:
            return Response({'error': 'El id es requerido en la URL para eliminar'}, status=400)
            
        try:
            data = models.Permisos_precio.objects.get(id=id)
            data.delete()
            return Response({'data': f'El precio con ID {id} fue eliminado exitosamente'})
        except models.Permisos_precio.DoesNotExist:
            return Response({'error': 'El precio no existe'}, status=404)
        
@api_view(['GET'])
@token_required # 2. Aplica el decorador para manejar la autenticación
def get_filtros_precios(request):
    try:
        try:
            locale.setlocale(locale.LC_TIME, 'es_CO.UTF-8')
        except locale.Error:
            locale.setlocale(locale.LC_TIME, 'es')

        # 3. El decorador ya validó el token y nos da el usuario en request.user
        usuario = request.user
        
        # El resto de tu lógica se mantiene, ya que es correcta
        permisos_por_usuario = {
            '33333': ['Precio publico', 'Precio Fintech', 'Precio Addi'],
            '44444': ['Precio sub', 'Precio publico', 'Precio Fintech', 'Precio premium', 'Precio Addi'],
            '11111': ['Precio sub', 'Precio publico', 'Precio Fintech', 'Precio Addi'],
            '22222': ['Precio sub', 'Precio publico', 'Precio Fintech', 'Precio Addi', 'Precio Adelantos Valle']
        }
        
        todas_las_listas_map = {
            "Precio publico": "Precio Público", "Precio sub": "Subdistribuidor", "Precio premium": "Premium",
            "Precio Fintech": "Fintech", "Precio Addi": "Addi", "Precio Flamingo": "Flamingo",
            "Costo": "Costo", "Precio Adelantos Valle": "Adelantos Valle"
        }

        lista_precios_final = []
        marcas = []
        fechas_validas_formateadas = []

        # Usamos el username del usuario que nos dio el decorador
        if usuario.username in permisos_por_usuario:
            listas_permitidas_ids = permisos_por_usuario[usuario.username]
            lista_precios_final = [{'id': id_lista, 'nombre': todas_las_listas_map[id_lista]} for id_lista in listas_permitidas_ids if id_lista in todas_las_listas_map]
        
        else:
            lista_precios_final = [{'id': k, 'nombre': v} for k, v in todas_las_listas_map.items()]
            productos = models.Lista_precio.objects.values_list('producto', flat=True).distinct()
            marcas = sorted(list(set([p.split(' ')[0].upper() for p in productos if p])))
            cargas = models.Carga.objects.all().order_by('-fecha_carga')[:50]
            for carga in cargas:
                fechas_validas_formateadas.append({
                    "valor": carga.id,
                    "texto": carga.fecha_carga.strftime("%d de %B de %Y - %H:%M")
                })

        return Response({
            'listas_precios': lista_precios_final,
            'marcas': marcas,
            'fechas_validas': fechas_validas_formateadas
        })

    except Exception as e:
        return Response({'detail': f'Error interno en get_filtros_precios: {str(e)}'}, status=500)


def motor_de_evaluacion_recursivo(formula_string, price_list_id, context, mapa_variables, cache_variables):
    cache_key = (formula_string, price_list_id)
    if cache_key in cache_variables:
        return cache_variables[cache_key]

    variables_en_formula = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', formula_string)
    contexto_local = context.copy()

    for var_name in set(variables_en_formula):
        if var_name in contexto_local:
            continue

        variables_especificas = mapa_variables.get(price_list_id, {})
        variable_obj = variables_especificas.get(var_name)

        if not variable_obj:
            variables_globales = mapa_variables.get(1, {})
            variable_obj = variables_globales.get(var_name)

        if variable_obj:
            if variable_obj.formula is None:
                valor_variable = Decimal('0')
            else:
                valor_variable = motor_de_evaluacion_recursivo(variable_obj.formula, price_list_id, context, mapa_variables, cache_variables)
            contexto_local[var_name] = valor_variable
        else:
            # LOG de variable faltante
            print(f"⚠️ Variable '{var_name}' no encontrada en contexto ni en mapa_variables para price_list_id={price_list_id}")
            contexto_local[var_name] = Decimal('0')

    try:
        resultado = Decimal(eval(formula_string, {"__builtins__": None}, contexto_local))
        cache_variables[cache_key] = resultado
        return resultado
    except Exception as e:
        print(f"❌ ERROR evaluando la fórmula '{formula_string}' con contexto {contexto_local}: {type(e)}")
        return Decimal('0')


# Función para normalizar cadenas
def normalize_string(s):
    if not isinstance(s, str):
        return ""
    s = re.sub(r'[\s\xa0-]+', ' ', s).strip()
    return s.lower()

@api_view(['GET'])
def get_reportes_por_fecha(request):
    BOGOTA_TZ = pytz.timezone('America/Bogota')
    fecha_str = request.query_params.get('fecha')
    if not fecha_str:
        return Response({"error": "El parámetro 'fecha' es requerido."}, status=400)

    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD."}, status=400)

    reportes = models.Lista_precio.objects.filter(
        dia__date=fecha
    ).values_list('dia', flat=True).distinct().order_by('dia')

    if not reportes:
        return Response([])

    respuesta_formateada = []
    for dt in reportes:
        dt_local = dt.astimezone(BOGOTA_TZ)
        respuesta_formateada.append({
            "id": dt.isoformat(),
            "texto": f"Reporte de las {dt_local.strftime('%I:%M:%S %p')}"
        })

    return Response(respuesta_formateada)


def should_show_kit(list_name, kit_name):
    if not list_name or not kit_name:
        return False
    
    list_lower = list_name.lower()
    kit_lower = kit_name.lower()
    keywords = ['addi', 'sub', 'fintech', 'valle']

    has_keyword = any(kw in kit_lower for kw in keywords)
    if not has_keyword:
        return True

    if 'addi' in kit_lower and 'addi' in list_lower:
        return True
    if 'sub' in kit_lower and 'sub' in list_lower:
        return True
    if 'fintech' in kit_lower and 'fintech' in list_lower:
        return True
    if 'valle' in kit_lower and 'valle' in list_lower:
        return True
        
    return False

def calculate_dynamic_total(equipo_sin_iva, kits):
    if not isinstance(equipo_sin_iva, Decimal):
        equipo_sin_iva = Decimal(str(equipo_sin_iva))
    
    base_iva_excluido = Decimal('1095578')
    valor_sim = Decimal('2000')
    iva_sim = valor_sim * Decimal('0.19')

    iva_equipo = Decimal('0')
    kit_total = Decimal('0')
    
    # Lógica de negocio para IVA y Kits
    if equipo_sin_iva > base_iva_excluido:
        iva_equipo = equipo_sin_iva * Decimal('0.19')
    else:
        kit_premium_valor = next((Decimal(str(k.get('valor', '0'))) for k in kits if k.get('nombre', '').lower() == 'kit premium'), Decimal('0'))
        kit_total = kit_premium_valor
    
    return equipo_sin_iva + iva_equipo + valor_sim + iva_sim + kit_total

def apply_iva_kit_rules(equipo_sin_iva, nombre_lista, kits_list, base_iva_excluido, TASA_IVA):
    """
    Función centralizada para aplicar las reglas de negocio del IVA y los Kits.
    """
    kits_modificados = [dict(k) for k in kits_list] # Crear una copia para no alterar los datos originales
    iva_equipo = Decimal('0')

    if equipo_sin_iva > base_iva_excluido:
        # REGLA 1: Si el equipo supera el umbral del IVA.
        iva_equipo = equipo_sin_iva * TASA_IVA
        kit_iva_nombre = "kit " + nombre_lista.replace("Precio ", "").lower()
        for kit in kits_modificados:
            if kit.get('nombre', '').lower() == kit_iva_nombre:
                kit['valor'] = 0.0 # Anula el kit correspondiente
                break
    else:
        # REGLA 2: Si el equipo NO supera el umbral del IVA.
        if nombre_lista.lower() == 'precio premium':
            # CORRECCIÓN: Para "Precio Premium" bajo el umbral, no se hace ninguna modificación.
            pass
        else:
            # REGLA 2.2 (GENERAL): Para otras listas, el IVA se representa en el "Kit Premium".
            iva_as_kit_premium = equipo_sin_iva * TASA_IVA
            kit_found = False
            for kit in kits_modificados:
                if kit.get('nombre', '').lower() == 'kit premium':
                    kit['valor'] = float(iva_as_kit_premium)
                    kit_found = True
                    break
            if not kit_found:
                kits_modificados.append({'nombre': 'Kit Premium', 'valor': float(iva_as_kit_premium)})
    
    return iva_equipo, kits_modificados


@api_view(['POST'])
# @token_required # Descomenta si usas este decorador
def buscar_precios(request):
    try:
        # --- SECCIÓN DE FILTROS (SIN CAMBIOS) ---
        usuario = request.user
        filtros = request.data.get('filtros', {})
        listas_precios_nombres = filtros.get('listas_precios', [])
        marcas_seleccionadas = filtros.get('marcas', [])
        referencia = filtros.get('referencia', '').strip().lower()
        filtro_variacion = filtros.get('filtro_variacion', '')
        filtro_promo = filtros.get('filtro_promo', False)
        carga_id_actual = filtros.get('fecha_especifica')

        if not listas_precios_nombres:
            return Response({'data': [], 'fecha_actual': 'N/A'})

        # --- SECCIÓN DE CONSULTAS A LA BASE DE DATOS (SIN CAMBIOS) ---
        productos_qs = models.Traducciones.objects.filter(active=True)
        if marcas_seleccionadas:
            productos_qs = productos_qs.filter(stok__iregex=r'(' + '|'.join(marcas_seleccionadas) + r')\s')
        if referencia:
            productos_qs = productos_qs.filter(Q(equipo__icontains=referencia) | Q(stok__icontains=referencia))

        mapa_traducciones = {normalize_string(p.stok): p.equipo for p in productos_qs}
        
        if carga_id_actual == 'todas':
            latest_price_ids_subquery = (
                models.Lista_precio.objects
                .filter(nombre__in=listas_precios_nombres)
                .values('producto', 'nombre')
                .annotate(latest_id=Max('id'))
                .values('latest_id')
            )
            precios_actuales_qs = models.Lista_precio.objects.filter(id__in=latest_price_ids_subquery).select_related('carga').order_by('-carga__fecha_carga', '-id')
            fecha_actual_str = 'Todas (últimos registros)'
        else:
            if not carga_id_actual:
                carga_actual = models.Carga.objects.order_by('-fecha_carga').first()
            else:
                try:
                    carga_actual = models.Carga.objects.get(id=carga_id_actual)
                except models.Carga.DoesNotExist:
                    return Response({'error': 'La carga seleccionada no existe.'}, status=404)
            
            if not carga_actual:
                return Response({'data': [], 'fecha_actual': 'No hay datos cargados'})
            
            precios_actuales_qs = models.Lista_precio.objects.filter(
                carga=carga_actual,
                nombre__in=listas_precios_nombres
            ).select_related('carga')
            fecha_actual_str = carga_actual.fecha_carga.strftime('%d de %B de %Y')
            
        productos_lp_raw = precios_actuales_qs.values_list('producto', flat=True).distinct()
        producto_lp_a_stok = {p_name: normalize_string(p_name) for p_name in productos_lp_raw if normalize_string(p_name) in mapa_traducciones}
        stoks_encontrados_lp = list(producto_lp_a_stok.keys())
        
        if not stoks_encontrados_lp:
            return Response({'data': [], 'fecha_actual': fecha_actual_str})
            
        precios_actuales_qs = precios_actuales_qs.filter(producto__in=stoks_encontrados_lp)

        subquery_precio_anterior = models.Lista_precio.objects.filter(
            producto=OuterRef('producto'),
            nombre=OuterRef('nombre'),
            carga__fecha_carga__lt=OuterRef('carga__fecha_carga')
        ).order_by('-carga__fecha_carga').values('id')[:1]

        precios_actuales_con_anterior = precios_actuales_qs.annotate(
            id_precio_anterior=Subquery(subquery_precio_anterior)
        )

        ids_anteriores_a_buscar = [p.id_precio_anterior for p in precios_actuales_con_anterior if p.id_precio_anterior is not None]
        precios_anteriores_encontrados = models.Lista_precio.objects.filter(id__in=ids_anteriores_a_buscar)
        mapa_precios_anteriores = {p.id: p for p in precios_anteriores_encontrados}

        all_cargas_ids = models.Lista_precio.objects.filter(producto__in=stoks_encontrados_lp).values_list('carga_id', flat=True).distinct()
        
        all_kits_data = models.Lista_precio.objects.filter(carga_id__in=all_cargas_ids, producto__in=stoks_encontrados_lp, nombre__icontains='Kit').exclude(nombre__icontains='Descuento Kit')
        all_costos_data = models.Lista_precio.objects.filter(carga_id__in=all_cargas_ids, producto__in=stoks_encontrados_lp, nombre='Costo')
        all_descuentos_data = models.Lista_precio.objects.filter(carga_id__in=all_cargas_ids, producto__in=stoks_encontrados_lp, nombre='descuento')
        
        mapa_kits = defaultdict(list)
        mapa_costos = {}
        mapa_descuentos = {}

        for kit in all_kits_data:
            key = (normalize_string(kit.producto), kit.carga_id)
            mapa_kits[key].append({'nombre': kit.nombre, 'valor': float(kit.valor)})
        
        for costo in all_costos_data:
            key = (normalize_string(costo.producto), costo.carga_id)
            mapa_costos[key] = costo.valor

        for descuento in all_descuentos_data:
            key = (normalize_string(descuento.producto), descuento.carga_id)
            mapa_descuentos[key] = descuento.valor
            
        # --- PROCESAMIENTO DE DATOS ---
        new_data = []
        base_iva_excluido = Decimal('1095578')
        TASA_IVA = Decimal('0.19')
        
        for precio_actual in precios_actuales_con_anterior:
            prod_raw = precio_actual.producto
            prod_lower = normalize_string(prod_raw)
            nombre_lista = precio_actual.nombre
            carga_id = precio_actual.carga_id
            
            equipo_sin_iva_actual = precio_actual.valor
            kits_actuales_raw = mapa_kits.get((prod_lower, carga_id), [])
            
            # Aplicar reglas al precio actual (necesario para la visualización y el cálculo de variación)
            iva_equipo_actual, kits_data_to_send = apply_iva_kit_rules(equipo_sin_iva_actual, nombre_lista, kits_actuales_raw, base_iva_excluido, TASA_IVA)
            
            valor_anterior_bruto = None
            kits_anteriores_to_send = []
            carga_id_anterior = None
            iva_equipo_anterior = Decimal('0') # Inicializar IVA anterior
            
            precio_anterior_obj = mapa_precios_anteriores.get(precio_actual.id_precio_anterior)

            if precio_anterior_obj:
                carga_id_anterior = precio_anterior_obj.carga_id
                valor_anterior_bruto = precio_anterior_obj.valor
                kits_anteriores_raw = mapa_kits.get((prod_lower, carga_id_anterior), [])
                kits_anteriores_to_send = kits_anteriores_raw
                # Se calcula el IVA del equipo anterior para una comparación justa
                iva_equipo_anterior, _ = apply_iva_kit_rules(valor_anterior_bruto, nombre_lista, kits_anteriores_raw, base_iva_excluido, TASA_IVA)
            
            # --- ZONA DE MODIFICACIÓN ---
            # La variación se calcula comparando el precio del equipo + su IVA respectivo.
            variacion = {'indicador': 'neutral', 'diferencial': 0.0, 'porcentaje': 0.0}
            
            if valor_anterior_bruto is not None:
                # 1. Se define el total a comparar: Precio Base del Equipo + IVA del Equipo
                total_comparable_actual = equipo_sin_iva_actual + iva_equipo_actual
                total_comparable_anterior = valor_anterior_bruto + iva_equipo_anterior
                
                if total_comparable_anterior > 0:
                    # 2. CÁLCULO DEL DIFERENCIAL
                    diferencial = total_comparable_actual - total_comparable_anterior
                    
                    indicador = 'up' if diferencial > 0 else 'down' if diferencial < 0 else 'neutral'
                    
                    # 3. CÁLCULO DEL PORCENTAJE
                    porcentaje = (diferencial / total_comparable_anterior) * 100
                    
                    variacion = {
                        'indicador': indicador, 
                        'diferencial': float(round(diferencial, 0)), # Redondear al entero más cercano
                        'porcentaje': float(round(porcentaje, 0)) # Redondear al entero más cercano (ej: 12.79 -> 13)
                    }
            
            # --- FIN DE LA ZONA DE MODIFICACIÓN ---

            if filtro_variacion and variacion['indicador'] != filtro_variacion:
                continue

            es_promo = Decimal(mapa_descuentos.get((prod_lower, carga_id), Decimal('0'))) > 0
            if filtro_promo and not es_promo:
                continue
            
            total_display = equipo_sin_iva_actual + iva_equipo_actual + Decimal('2000') + (Decimal('2000') * TASA_IVA) + sum(Decimal(str(k.get('valor', '0'))) for k in kits_data_to_send)

            new_data.append({
                'equipo': prod_raw,
                'nombre_lista': nombre_lista,
                'precio simcard': float(Decimal('2000')),
                'IVA simcard': float(Decimal('2000') * TASA_IVA),
                'equipo sin IVA': float(equipo_sin_iva_actual),
                'IVA equipo': float(iva_equipo_actual),
                'kits': kits_data_to_send,
                'indicador': variacion['indicador'],
                'diferencial': variacion['diferencial'], # <-- Este valor ahora será el correcto
                'porcentaje': variacion['porcentaje'], # <-- Y este también
                'costo': float(mapa_costos.get((prod_lower, carga_id), Decimal('0'))),
                'descuento': float(mapa_descuentos.get((prod_lower, carga_id), Decimal('0'))),
                'total_kit_calculado': float(total_display),
                'Promo': es_promo,
                'valor_anterior': float(valor_anterior_bruto) if valor_anterior_bruto is not None else 0,
                'costo_anterior': float(mapa_costos.get((prod_lower, carga_id_anterior), Decimal('0'))) if carga_id_anterior else 0.0,
                'descuento_anterior': float(mapa_descuentos.get((prod_lower, carga_id_anterior), Decimal('0'))) if carga_id_anterior else 0.0,
                'kits_anteriores': [dict(k) for k in kits_anteriores_to_send],
            })

        return Response({'data': new_data, 'fecha_actual': fecha_actual_str})
    except Exception as e:
        # Manejo de errores básico
        print(f"ERROR en /buscar_precios: {str(e)}")
        return Response({'detail': f'Error interno: {str(e)}'}, status=500)




    
@api_view(['GET', 'POST', 'DELETE'])
def black_list(request, id=None):
    if request.method == 'GET':
        data = models.Lista_negra.objects.all()
        data_list = [{'id': i.id, 'product': i.equipo} for i in data]
        data_list = sorted(data_list, key=lambda x: x['product'].lower())
        return Response({"data": data_list})

    if request.method == 'POST':
        token = request.data.get('jwt')
        product = request.data.get('product')

        if not token:
            raise AuthenticationFailed('Debes estar logueado')
        
        if not product:
            return Response({"error": "El campo 'product' es obligatorio."}, status=400)
            
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            usuario = User.objects.get(username=payload['id'])
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Debes estar logueado')

        models.Lista_negra.objects.create(equipo=product)
        return Response({"data": "successful creation"})

    if request.method == 'DELETE':
        if id is not None:
            try:
                item = models.Lista_negra.objects.get(id=id)
                item.delete()
                return Response({"data": f"El producto con ID {id} fue eliminado exitosamente"})
            except models.Lista_negra.DoesNotExist:
                return Response({"error": "El producto no existe"}, status=404)
            except Exception as e:
                return Response({"error": f"No se pudo eliminar el producto: {str(e)}"}, status=400)
        else:
            return Response({"error": "El campo 'id' es obligatorio"}, status=400)

@api_view(['POST'])
@csrf_exempt
@transaction.atomic
def settle_invoice(request):
    try:
        consignacion_ids = request.data.get('ids', [])
        saldar_data = request.data.get('saldar_data', {})
        jwt_token = request.data.get('jwt')
        
        if not all([consignacion_ids, saldar_data, jwt_token]):
            return Response({'detail': 'Faltan datos en la solicitud.'}, status=400)

        payload = jwt.decode(jwt_token, 'secret', algorithms=['HS256'])
        usuario = User.objects.get(username=payload['id'])
        
        consignaciones_a_saldar = models.Corresponsal_consignacion.objects.filter(
            id__in=consignacion_ids, 
            estado='pendiente'
        )

        if len(consignaciones_a_saldar) != len(consignacion_ids):
            return Response({'detail': 'Algunas consignaciones no se encontraron o ya fueron saldadas.'}, status=400)

        # Obtenemos los datos para el nuevo registro 'Conciliado'
        fecha_cierre_conciliado = consignaciones_a_saldar.aggregate(max_fecha=Max('fecha'))['max_fecha']
        detalle_comun = saldar_data['detalle']
        fecha_consignacion_conciliado = datetime.datetime.strptime(saldar_data['fechaConsignacion'], '%Y-%m-%d').date()

        consignaciones_por_sucursal = defaultdict(list)
        for c in consignaciones_a_saldar:
            if c.codigo_incocredito:
                consignaciones_por_sucursal[c.codigo_incocredito].append(c)

        for sucursal_obj, consignaciones_grupo in consignaciones_por_sucursal.items():
            total_grupo = sum(c.valor for c in consignaciones_grupo)
            ids_grupo = [c.id for c in consignaciones_grupo]
            referencias_text = ','.join(map(str, ids_grupo))

            # Creamos el registro 'Conciliado' con la fecha de la operación (septiembre)
            models.Corresponsal_consignacion.objects.create(
                valor=total_grupo,
                banco='Corresponsal Banco de Bogota',
                fecha_consignacion=fecha_consignacion_conciliado,
                fecha=fecha_cierre_conciliado,
                responsable=str(usuario.id),
                estado='Conciliado',
                detalle=detalle_comun,
                url='',
                codigo_incocredito=sucursal_obj,
                detalle_banco=referencias_text,
            )

        # ======================= INICIO DEL CAMBIO =======================
        # Actualizamos los registros a 'saldado' SIN modificar sus fechas originales.
        consignaciones_a_saldar.update(
            estado='saldado',
            detalle=detalle_comun
        )
        # ======================== FIN DEL CAMBIO =========================

        return Response({'detail': 'Consignaciones saldadas correctamente.'}, status=200)

    except User.DoesNotExist:
        return Response({'detail': 'El usuario del token no es válido.'}, status=401)
    except Exception as e:
        print(f"ERROR en settle_invoice: {str(e)}")
        return Response({'detail': f'Ocurrió un error interno: {str(e)}'}, status=500)

@api_view(['POST'])
def assign_responsible(request):
    encargado_data = request.data.get('encargado')
    sucursal = request.data.get('sucursal')

    if not encargado_data or not sucursal:
        return Response(
            {'error': 'Los campos "encargado" y "sucursal" son requeridos.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if isinstance(encargado_data, dict):
        username_str = encargado_data.get('value')
    else:
        username_str = encargado_data

    if not username_str:
        return Response(
            {'error': 'El dato del encargado no contiene un valor válido. Verifique que el objeto enviado tenga una llave "value".'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        username_to_find = username_str.split('-')[0]
        responsable = models.User.objects.get(username=username_to_find)
        sucursal_obj = models.Codigo_oficina.objects.get(terminal=sucursal)

        obj, created = models.Responsable_corresponsal.objects.update_or_create(
            sucursal=sucursal_obj,
            defaults={'user': responsable}
        )
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)

    except models.User.DoesNotExist:
        return Response(
            {'error': f'El usuario con username "{username_to_find}" no existe.'},
            status=status.HTTP_404_NOT_FOUND
        )
    except models.Codigo_oficina.DoesNotExist:
        return Response(
            {'error': f'La sucursal con terminal "{sucursal}" no existe.'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST'])
def get_image_corresponsal(request):
    tenant_id = '69002990-8016-415d-a552-cd21c7ad750c'
    client_id = '46a313cf-1a14-4d9a-8b79-9679cc6caeec'
    client_secret = 'vPc8Q~gCQUBkwdUQ6Ez1FMRiAmpFnuuWsR4wIdt1'

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data2 = {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default'
    }

    response = requests.post(url, headers=headers, data=data2)

    if response.status_code == 200:
        access_token = response.json().get('access_token')
    else:
        raise AuthenticationFailed(f"Error getting access token")
    
    file_name = request.data['url']

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    site_id = 'teamcommunicationsa.sharepoint.com,71134f24-154d-4138-8936-3ef32a41682e,1c13c18c-ec54-4bf0-8715-26331a20a826'
    download_url = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/uploads/{file_name}:/content'

    # Descargar la imagen desde SharePoint
    response = requests.get(download_url, headers=headers)

    if response.status_code == 200:
        # Devolver la imagen al frontend
        encoded_image = base64.b64encode(response.content).decode('utf-8')
        return JsonResponse({'image': encoded_image, 'content_type': response.headers['Content-Type']})
    else:
        return JsonResponse({'error': response.json()}, status=400)


    pass

@api_view(['POST'])
@cajero_permission_required # <-- Se protege la vista
def select_consignaciones_corresponsal_cajero(request):
    try:
        fecha_str = request.data['fecha']
        user = request.user # <-- Obtenemos el usuario del token

        # Se obtiene la sucursal de forma segura desde el usuario
        responsable = models.Responsable_corresponsal.objects.filter(user=user).first()
        if not responsable or not responsable.sucursal:
            return Response({'error': 'Usuario no asignado a una sucursal válida.'}, status=404)
        sucursal = responsable.sucursal.terminal

        # --- LÓGICA DE FECHA ---
        if len(fecha_str) == 7: # Mes completo
            fecha_inicio_naive = pd.to_datetime(fecha_str).to_pydatetime()
            fecha_fin_naive = fecha_inicio_naive + pd.offsets.MonthEnd(1)
        else: # Día específico
            fecha_dia = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            fecha_inicio_naive = datetime.combine(fecha_dia, time.min)
            fecha_fin_naive = datetime.combine(fecha_dia, time.max)
        # --- FIN DE LÓGICA DE FECHA ---

        fecha_inicio = timezone.make_aware(fecha_inicio_naive)
        fecha_fin = timezone.make_aware(fecha_fin_naive)

        # --- CORRECCIÓN IMPORTANTE ---
        # La consulta ahora filtra por 'fecha' (la fecha de cierre/reporte)
        # en lugar de 'fecha_consignacion' (la fecha del recibo).
        transacciones_base = models.Corresponsal_consignacion.objects.filter(
            fecha__range=(fecha_inicio.date(), fecha_fin.date()),
            codigo_incocredito=sucursal
        )
        # --- FIN DE LA CORRECCIÓN ---
        
        total_real = transacciones_base.exclude(
             Q(estado='Conciliado') & ~Q(detalle_banco__in=[None, ''])
        ).aggregate(total=Sum('valor'))['total'] or 0

        detalles = list(transacciones_base.order_by('-id').values(
            'id', 'banco', 'url', 'valor', 'estado'
        ))

        return Response({'total': total_real, 'detalles': detalles})

    except Exception as e:
        import traceback
        print(f"Error en select_consignaciones_corresponsal_cajero: {e}\n{traceback.format_exc()}")
        return Response({'detail': f'Error interno: {str(e)}'}, status=500)




@api_view(['GET'])
@cajero_permission_required
def historico_pendientes_cajero(request):
    try:
        usuario = request.user

        responsable = models.Responsable_corresponsal.objects.filter(user=usuario).first()
        if not responsable or not responsable.sucursal:
            return Response({'error': 'Usuario no asignado a sucursal.'}, status=404)
        
        sucursal_terminal = responsable.sucursal.terminal
        sucursal_obj = models.Codigo_oficina.objects.filter(terminal=sucursal_terminal).first()
        if not sucursal_obj:
            return Response({'error': 'Código de sucursal no encontrado.'}, status=404)

        hoy = timezone.now().date()
        # --- CORRECCIÓN 2: Usa timedelta directamente ---
        inicio_rango = hoy - timedelta(days=45)

        transacciones_diarias = models.Transacciones_sucursal.objects.filter(
            codigo_incocredito=sucursal_obj.codigo,
            fecha__date__range=(inicio_rango, hoy)
        ).annotate(dia=TruncDay('fecha')).values('dia').annotate(total_cajero=Sum('valor')).order_by('dia')
        
        consignaciones_base = models.Corresponsal_consignacion.objects.filter(
            codigo_incocredito=sucursal_terminal,
            fecha__date__range=(inicio_rango, hoy)
        ).exclude(Q(estado='Conciliado') & ~Q(detalle_banco__in=[None, '']))

        consignaciones_diarias = consignaciones_base.annotate(
            dia=TruncDay('fecha')
        ).values('dia').annotate(
            total_consignado=Sum('valor')
        ).order_by('dia')

        df_transacciones = pd.DataFrame(list(transacciones_diarias))
        df_consignaciones = pd.DataFrame(list(consignaciones_diarias))

        if 'dia' in df_transacciones.columns: df_transacciones['dia'] = pd.to_datetime(df_transacciones['dia']).dt.date
        if 'dia' in df_consignaciones.columns: df_consignaciones['dia'] = pd.to_datetime(df_consignaciones['dia']).dt.date

        if df_transacciones.empty and df_consignaciones.empty:
            return Response({'total_general': 0, 'detalles': []})

        if not df_transacciones.empty and not df_consignaciones.empty:
            df_merged = pd.merge(df_transacciones, df_consignaciones, on='dia', how='outer')
        elif not df_transacciones.empty:
            df_merged = df_transacciones
        else:
            df_merged = df_consignaciones

        df_merged.fillna(0, inplace=True)
        
        if 'total_cajero' not in df_merged.columns: df_merged['total_cajero'] = 0
        if 'total_consignado' not in df_merged.columns: df_merged['total_consignado'] = 0
        
        df_merged['pendiente_dia'] = df_merged['total_cajero'] - df_merged['total_consignado']
        
        df_pendientes = df_merged[df_merged['pendiente_dia'] != 0].copy()
        total_general_pendiente = df_pendientes['pendiente_dia'].sum()
        df_pendientes.rename(columns={'dia': 'fecha'}, inplace=True)
        detalles_pendientes = df_pendientes[['fecha', 'pendiente_dia']].to_dict('records')

        return Response({
            'total_general': float(total_general_pendiente),
            'detalles': detalles_pendientes
        })

    except Exception as e:
        import traceback
        print(f"Error en historico_pendientes_cajero: {e}\n{traceback.format_exc()}")
        return Response({'detail': f'Error interno: {str(e)}'}, status=500)
    
def generate_unique_filename(original_name):
    import uuid
    from pathlib import Path
    extension = Path(original_name).suffix
    return f"{uuid.uuid4()}{extension}"



@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@cajero_permission_required
def consignacion_corresponsal(request):
    """
    Registra una consignación de corresponsal:
      - Sube la imagen a SharePoint mediante Microsoft Graph.
      - Persiste la transacción en la BD.
    """
    try:
        usuario = request.user
        image = request.data.get('image')
        sucursal = request.data.get('sucursal')
        consignacion_str = request.data.get('data')
        fecha_reporte_str = request.data.get('fecha')

        # Validación de presencia de datos
        if not all([image, sucursal, consignacion_str, fecha_reporte_str]):
            return Response(
                {'detail': 'Faltan datos en la solicitud (imagen, sucursal, data o fecha).'},
                status=400
            )

        # Parseo del JSON de la consignación
        try:
            consignacion_data = json.loads(consignacion_str)
        except json.JSONDecodeError:
            return Response(
                {'detail': 'El campo "data" no contiene JSON válido.'},
                status=400
            )

        # Parseo de fechas con la importación correcta (from datetime import datetime)
        fecha_reporte = datetime.strptime(fecha_reporte_str, '%Y-%m-%d').date()

        # --- Lógica de SharePoint (Microsoft Graph) ---
        tenant_id = '69002990-8016-415d-a552-cd21c7ad750c'
        client_id = '46a313cf-1a14-4d9a-8b79-9679cc6caeec'
        client_secret = 'vPc8Q~gCQUBkwdUQ6Ez1FMRiAmpFnuuWsR4wIdt1'

        url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data_ms = {
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': 'https://graph.microsoft.com/.default'
        }

        response_ms = requests.post(url, headers=headers, data=data_ms, timeout=30)
        response_ms.raise_for_status()
        access_token = response_ms.json().get('access_token')

        if not access_token:
            return Response({'detail': 'No se pudo obtener el access_token de Microsoft Graph.'}, status=503)

        headers_sp = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/octet-stream'
        }

        site_id = 'teamcommunicationsa.sharepoint.com,71134f24-154d-4138-8936-3ef32a41682e,1c13c18c-ec54-4bf0-8715-26331a20a826'

        # Genera un nombre único para el archivo
        file_name = generate_unique_filename(image.name)

        # Sube el archivo (imagen) a la carpeta /uploads/ del drive raíz del sitio
        upload_url = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/uploads/{file_name}:/content'
        response_upload = requests.put(upload_url, headers=headers_sp, data=image.read(), timeout=120)
        response_upload.raise_for_status()

        # --- Lógica de guardado en la BD ---
        banco_categoria = consignacion_data.get('banco')

        # Estado por categoría
        estado = 'saldado' if banco_categoria in ['Corresponsal Banco de Bogota', 'Reclamaciones'] else 'pendiente'

        # Detalle adicional según banco/categoría
        detalle_banco_valor = None
        if banco_categoria in ['Proveedores', 'Obligaciones financieras']:
            detalle_banco_valor = consignacion_data.get('proveedor')
        elif banco_categoria == 'Otros bancos':
            detalle_banco_valor = consignacion_data.get('bancoDetalle')
        elif banco_categoria == 'Impuestos':
            detalle_banco_valor = consignacion_data.get('impuestoDetalle')

        # Fecha de consignación desde data
        fecha_consignacion = datetime.strptime(consignacion_data.get('fechaConsignacion'), '%Y-%m-%d').date()

        models.Corresponsal_consignacion.objects.create(
            valor=consignacion_data.get('valor'),
            banco=banco_categoria,
            fecha_consignacion=fecha_consignacion,
            fecha=fecha_reporte,
            responsable=usuario.id,
            estado=estado,
            detalle=consignacion_data.get('detalle'),
            url=file_name,  # Guardamos el nombre/ubicación del archivo subido
            codigo_incocredito=sucursal,
            detalle_banco=detalle_banco_valor,
            # Campos específicos solo para "Venta doble proposito"
            min=consignacion_data.get('min') if banco_categoria == 'Venta doble proposito' else None,
            imei=consignacion_data.get('imei') if banco_categoria == 'Venta doble proposito' else None,
            planilla=consignacion_data.get('planilla') if banco_categoria == 'Venta doble proposito' else None,
        )

        return Response({'detail': 'Consignación registrada correctamente'}, status=200)

    except requests.exceptions.RequestException as e:
        return Response({'detail': f'Error de comunicación con Microsoft Graph: {e}'}, status=503)
    except Exception as e:
        # Log detallado del traceback en consola/servidor
        print(f"ERROR en consignacion_corresponsal: {str(e)}")
        import traceback
        traceback.print_exc()
        return Response({'detail': f'Error interno del servidor: {str(e)}'}, status=500)





@api_view(['GET', 'POST', 'PUT'])
def lista_usuarios(request):
    if request.method == 'GET':
        users = User.objects.all()
        users_list = [{'id': i.id, 'document': i.username, 'firstName': i.first_name, 'lastName': i.last_name, 'active': i.is_active } for i in users if i.username != 'sebasmoncada']
        return Response(users_list)
    if request.method == 'POST':
        type_action = request.data['type']
        data = request.data['user']
        user = User.objects.get(username = data['document'])
        if type_action == 'reset':
            user.set_password('Cambiame123')
            user.save()
        elif type_action == 'activate':
            user.is_active = not data['active']
            user.save()
        return Response([])
    if request.method == 'PUT':
        data = request.data
        user = User.objects.create_user(
            password = 'Cambiame123',
            username = data['document'],
            first_name = data['firstName'],
            last_name = data['lastName'],
            email = data['email'],
        )
        user.save()
        return Response([])


@api_view(['POST'])
def encargados_corresponsal(request):
    sucursales = models.Codigo_oficina.objects.values_list('terminal', flat=True).order_by('terminal')
    
    responsables_qs = models.Responsable_corresponsal.objects.select_related('user', 'sucursal').all()
    
    responsables = {
        i.sucursal.terminal: f"{i.user.username}-{i.user.first_name}-{i.user.last_name}"
        for i in responsables_qs
    }
    
    # --- INICIO DE LA MODIFICACIÓN ---
    # Filtramos usando tu sistema de permisos personalizado.
    # 1. Filtramos por el ID del permiso (11 = 'caja')
    # 2. Nos aseguramos de que 'tiene_permiso' sea True
    # 3. Agregamos .distinct() para evitar duplicados si un usuario tiene el permiso varias veces.
    users = User.objects.filter(
        permisos_usuarios__permiso__id=11,
        permisos_usuarios__tiene_permiso=True
    ).values('username', 'first_name', 'last_name').distinct()
    # --- FIN DE LA MODIFICACIÓN ---
    
    users_list = []
    users_options = []
    for i in users:
        user_string = f"{i['username']}-{i['first_name']}-{i['last_name']}"
        users_list.append(user_string)
        if i['username'] != 'sebasmoncada':
            users_options.append({'value': user_string, 'text': user_string})

    data = {
        'sucursales': list(sucursales),
        'users': users_list,
        'users_options': users_options, 
        'responsables': responsables,
    }
    return Response(data)



@api_view(['POST'])
def resumen_corresponsal(request):
    try:
        fecha_str = request.data.get('fecha')
        sucursal_code = request.data.get('sucursal')

        # --- INICIO DEBUG ---
        print("\n================= INICIO DEPURACIÓN ==================")
        print(f"DEBUG: Petición recibida. Fecha: '{fecha_str}', Sucursal: '{sucursal_code}'")
        # --- FIN DEBUG ---

        if not fecha_str:
            return Response({'error': 'Fecha requerida'}, status=400)

        filtro_principal = None
        if len(fecha_str) == 7:
            year, month = map(int, fecha_str.split('-'))
            filtro_principal = Q(fecha_consignacion__year=year, fecha_consignacion__month=month)
            print(f"DEBUG: Estrategia de filtro: MES y AÑO ({year}-{month})")
        else:
            fecha_dia = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            filtro_principal = Q(fecha_consignacion=fecha_dia)
            print(f"DEBUG: Estrategia de filtro: DÍA EXACTO ({fecha_dia})")

        consignaciones_qs = models.Corresponsal_consignacion.objects.filter(
            filtro_principal,
            estado__in=['pendiente', 'saldado', 'Conciliado']
        ).distinct()
        print(f"DEBUG [1]: Registros encontrados por FECHA y ESTADO: {consignaciones_qs.count()}")

        titulo = ''
        if sucursal_code and sucursal_code not in ['0', '-1']:
            sucursal_obj = models.Codigo_oficina.objects.filter(codigo=sucursal_code).first()
            if sucursal_obj:
                print(f"DEBUG: Sucursal encontrada (código): '{sucursal_obj.codigo}'. Se filtrará por el terminal: '{sucursal_obj.terminal}'")
                consignaciones_qs = consignaciones_qs.filter(codigo_incocredito=sucursal_obj.terminal)
                titulo = sucursal_obj.terminal
                print(f"DEBUG [2]: Registros restantes tras filtrar por SUCURSAL: {consignaciones_qs.count()}")
            else:
                titulo = 'Sucursal Desconocida'
                print(f"DEBUG: ADVERTENCIA - No se encontró un objeto Codigo_oficina para el código: {sucursal_code}")
        else:
            titulo = 'Todas las sucursales'
            print("DEBUG: No se aplicó filtro de sucursal (se pidieron todas).")

        consignaciones_para_vista = consignaciones_qs.exclude(
            Q(estado='Conciliado') & ~Q(detalle_banco__in=[None, ''])
        )
        print(f"DEBUG [3]: Registros para la VISTA (excluyendo 'Conciliado' con detalle): {consignaciones_para_vista.count()}")

        # --- INICIO BLOQUE CORREGIDO ---
        # Ahora filtramos Transacciones_sucursal usando la fecha de entrada (fecha_str)
        # en lugar de las fechas de las consignaciones.
        
        print(f"DEBUG [4]: Creando filtro de CAJERO basado en la fecha de entrada: '{fecha_str}'")

        filtro_cajero = Q()
        if len(fecha_str) == 7:
            fecha_inicio_naive = pd.to_datetime(fecha_str).to_pydatetime()
            fecha_fin_naive = fecha_inicio_naive + pd.offsets.MonthEnd(1)
            fecha_inicio = timezone.make_aware(fecha_inicio_naive)
            fecha_fin = timezone.make_aware(fecha_fin_naive)
            filtro_cajero = Q(fecha__range=(fecha_inicio, fecha_fin))
            print(f"DEBUG [5A]: Filtro de CAJERO por RANGO DE MES: {fecha_inicio} a {fecha_fin}")
        else:
            fecha_inicio_naive = datetime.strptime(fecha_str, '%Y-%m-%d')
            fecha_fin_naive = fecha_inicio_naive.replace(hour=23, minute=59, second=59)
            fecha_inicio = timezone.make_aware(fecha_inicio_naive)
            fecha_fin = timezone.make_aware(fecha_fin_naive)
            filtro_cajero = Q(fecha__range=(fecha_inicio, fecha_fin))
            print(f"DEBUG [5A]: Filtro de CAJERO por RANGO DE DÍA: {fecha_inicio} a {fecha_fin}")
            
        transacciones_cajero_qs = models.Transacciones_sucursal.objects.filter(filtro_cajero)
        print(f"DEBUG [5B]: Transacciones de cajero encontradas por FECHA: {transacciones_cajero_qs.count()}")

        if sucursal_code and sucursal_code not in ['0', '-1']:
            transacciones_cajero_qs = transacciones_cajero_qs.filter(codigo_incocredito=sucursal_code)
            print(f"DEBUG [5C]: Transacciones de cajero restantes tras filtrar por SUCURSAL: {transacciones_cajero_qs.count()}")
        # --- FIN BLOQUE CORREGIDO ---


        responsable_ids = consignaciones_qs.values_list('responsable', flat=True).distinct()
        valid_responsable_ids = [int(id) for id in responsable_ids if id and str(id).isdigit()]
        usuarios_dict = {
            user.id: user.username 
            for user in User.objects.filter(id__in=valid_responsable_ids)
        }

        transacciones_data_vista = []
        for t in consignaciones_para_vista.order_by('-id'):
            banco = getattr(t, 'banco', '')
            detalle_categoria = getattr(t, 'detalle_banco', '') or ''
            if banco == 'Venta doble proposito':
                imei = getattr(t, 'imei', '') or ''
                if imei:
                    detalle_categoria = f"IMEI: {imei}"

            responsable_username = 'Desconocido'
            responsable_id = getattr(t, 'responsable', None)
            if responsable_id:
                try:
                    responsable_username = usuarios_dict.get(int(responsable_id), 'Desconocido')
                except (ValueError, TypeError):
                    pass
            
            nueva_transaccion = { 'id': t.id, 'valor': getattr(t, 'valor', 0) or 0, 'banco': banco, 'fecha_consignacion': t.fecha_consignacion, 'fecha': t.fecha, 'responsable': responsable_username, 'estado': getattr(t, 'estado', ''), 'detalle': getattr(t, 'detalle', '') or '', 'sucursal_nombre': getattr(t, 'codigo_incocredito', ''), 'detalle_categoria': detalle_categoria, 'url': getattr(t, 'url', None), 'min': getattr(t, 'min', None), 'imei': getattr(t, 'imei', None), 'planilla': getattr(t, 'planilla', None) }
            transacciones_data_vista.append(nueva_transaccion)

        transacciones_data_excel = []
        for t in consignaciones_qs.order_by('-id'):
            banco = getattr(t, 'banco', '')
            detalle_categoria = getattr(t, 'detalle_banco', '') or ''
            if banco == 'Venta doble proposito':
                imei = getattr(t, 'imei', '') or ''
                if imei:
                    detalle_categoria = f"IMEI: {imei}"

            responsable_username = 'Desconocido'
            responsable_id = getattr(t, 'responsable', None)
            if responsable_id:
                try:
                    responsable_username = usuarios_dict.get(int(responsable_id), 'Desconocido')
                except (ValueError, TypeError):
                    pass
            
            nueva_transaccion = { 'id': t.id, 'valor': getattr(t, 'valor', 0) or 0, 'banco': banco, 'fecha_consignacion': t.fecha_consignacion, 'fecha': t.fecha, 'responsable': responsable_username, 'estado': getattr(t, 'estado', ''), 'detalle': getattr(t, 'detalle', '') or '', 'sucursal_nombre': getattr(t, 'codigo_incocredito', ''), 'detalle_categoria': detalle_categoria, 'url': getattr(t, 'url', None), 'min': getattr(t, 'min', None), 'imei': getattr(t, 'imei', None), 'planilla': getattr(t, 'planilla', None) }
            transacciones_data_excel.append(nueva_transaccion)

        valor_total_cajero = transacciones_cajero_qs.aggregate(Sum('valor'))['valor__sum'] or 0
        total_saldado = consignaciones_para_vista.filter(estado='saldado').aggregate(total=Sum('valor'))['total'] or 0
        total_pendiente = consignaciones_para_vista.filter(estado='pendiente').aggregate(total=Sum('valor'))['total'] or 0
        
        print(f"DEBUG [FINAL]: Totales calculados -> valor_cajero: {valor_total_cajero}, consignacion_saldado: {total_saldado}, pendiente: {total_pendiente}")
        print("================== FIN DEPURACIÓN ===================\n")

        data = {
            'valor': valor_total_cajero,
            'titulo': titulo,
            'consignacion': total_saldado,
            'pendiente': total_pendiente,
            'consignaciones': transacciones_data_vista,
            'consignaciones_excel': transacciones_data_excel
        }
        return Response(data)

    except Exception as e:
        print(f"ERROR FATAL en resumen_corresponsal: {str(e)}\n{traceback.format_exc()}")
        return Response({'error': f'Error interno del servidor: {str(e)}'}, status=500)
    
@api_view(['POST'])
def select_datos_corresponsal(request):
    import datetime
    import pandas as pd
    from django.utils import timezone
    from django.db.models import Sum

    fecha = request.data.get('fecha')
    if not fecha:
        return Response({'error': 'Fecha requerida'}, status=400)

    if len(fecha) == 7:
        fecha_inicio_naive = pd.to_datetime(fecha).to_pydatetime()
        fecha_fin_naive = fecha_inicio_naive + pd.offsets.MonthEnd(1)
    else:
        fecha_inicio_naive = datetime.datetime.strptime(fecha, '%Y-%m-%d')
        fecha_fin_naive = fecha_inicio_naive.replace(hour=23, minute=59, second=59)

    fecha_inicio = timezone.make_aware(fecha_inicio_naive)
    fecha_fin = timezone.make_aware(fecha_fin_naive)

    transacciones = models.Transacciones_sucursal.objects.filter(fecha__range=(fecha_inicio, fecha_fin))
    transacciones_data = list(transacciones.values())

    sucursales = models.Codigo_oficina.objects.all()
    sucursales_dict = [{'value': i.codigo, 'text': i.terminal} for i in sucursales]
    
    if not transacciones_data:
        return Response({
            'consolidado': [],
            'sucursales': sucursales_dict,
            'data': []
        })

    df_transacciones = pd.DataFrame(transacciones_data)
    df_transacciones['valor'] = pd.to_numeric(df_transacciones['valor'], errors='coerce').fillna(0)
    
    cod_sucursales_map = {i.codigo: i.terminal for i in sucursales}
    df_transacciones['codigo_incocredito'] = df_transacciones['codigo_incocredito'].map(cod_sucursales_map)

    df_consolidado = df_transacciones.groupby('codigo_incocredito').agg(
        cuenta=('codigo_incocredito', 'size'),
        valor=('valor', 'sum')
    ).reset_index()

    consignaciones_qs = models.Corresponsal_consignacion.objects.filter(fecha_consignacion__range=(fecha_inicio, fecha_fin))
    
    if consignaciones_qs.exists():
        df_consignaciones = pd.DataFrame(list(consignaciones_qs.values('codigo_incocredito', 'estado', 'valor')))
        df_consignaciones['valor'] = pd.to_numeric(df_consignaciones['valor'], errors='coerce').fillna(0)
        
        df_consignaciones_pivot = df_consignaciones.pivot_table(
            index='codigo_incocredito',
            columns='estado',
            values='valor',
            aggfunc='sum'
        ).reset_index()

        df_consolidado = pd.merge(df_consolidado, df_consignaciones_pivot, on='codigo_incocredito', how='outer').fillna(0)
    else:
        df_consolidado['pendiente'] = 0
        df_consolidado['saldado'] = 0
        df_consolidado['Conciliado'] = 0

    for col in ['pendiente', 'saldado', 'Conciliado']:
        if col not in df_consolidado.columns:
            df_consolidado[col] = 0

    df_consolidado['saldado'] = df_consolidado['saldado'] + df_consolidado['Conciliado']
    df_consolidado['restante'] = df_consolidado['valor'] - df_consolidado['pendiente'] - df_consolidado['saldado']
    
    columnas_finales = ['codigo_incocredito', 'cuenta', 'valor', 'pendiente', 'saldado', 'restante']
    consolidado = df_consolidado[columnas_finales].to_dict(orient='records')
    
    return Response({
        'consolidado': consolidado,
        'sucursales': sucursales_dict,
        'data': transacciones_data
    })




@api_view(['POST'])
@cajero_permission_required  # <--- 1. APLICA EL DECORADOR
def select_datos_corresponsal_cajero(request):
    try:
        # 2. El usuario ya está autenticado y disponible en 'request.user'
        user = request.user
        fecha_str = request.data['fecha']

        responsable = models.Responsable_corresponsal.objects.filter(user=user).first()
        if not responsable or not responsable.sucursal:
            return Response({'error': 'Usuario no asignado a una sucursal válida.'}, status=404)
        
        sucursal_terminal = responsable.sucursal.terminal

        sucursal_obj = models.Codigo_oficina.objects.filter(terminal=sucursal_terminal).first()
        if not sucursal_obj:
            return Response({'error': f'El código para la sucursal {sucursal_terminal} no fue encontrado.'}, status=404)
        
        codigo_sucursal = sucursal_obj.codigo
        
        # Lógica de fechas
        if len(fecha_str) == 7:
            # Para un mes completo (YYYY-MM)
            fecha_inicio_naive = datetime.strptime(fecha_str, '%Y-%m')
            # Usamos pd.offsets para obtener el último día del mes
            fecha_fin_naive = (pd.to_datetime(fecha_str) + pd.offsets.MonthEnd(1)).to_pydatetime()
        else:
            # Para un día específico (YYYY-MM-DD), cubrimos el día completo
            fecha_dia = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            fecha_inicio_naive = datetime.combine(fecha_dia, time.min)
            fecha_fin_naive = datetime.combine(fecha_dia, time.max)

        fecha_inicio = timezone.make_aware(fecha_inicio_naive)
        fecha_fin = timezone.make_aware(fecha_fin_naive)
        
        transacciones_qs = models.Transacciones_sucursal.objects.filter(
            fecha__range=(fecha_inicio, fecha_fin), 
            codigo_incocredito=codigo_sucursal
        )
        
        total_datos = transacciones_qs.aggregate(total=Sum('valor'))['total'] or 0

        return Response({'total': total_datos, 'sucursal': sucursal_terminal})

    # 3. El decorador ya maneja el error 'User.DoesNotExist'
    except Exception as e:
        print(f"Error en select_datos_corresponsal_cajero: {str(e)}")
        return Response({'detail': f'Error interno: {str(e)}'}, status=500)


@api_view(['POST'])
def guardar_datos_corresponsal(request):
    """
    Procesa y/o guarda los datos de transacciones de un corresponsal.
    'action': 'analyze' -> Analiza los datos en busca de duplicados en el archivo y en la base de datos.
    'action': 'save' -> Guarda los registros filtrados en la base de datos.
    """
    action = request.data.get('action', 'analyze') 
    cabecera = request.data['cabecera']
    items = request.data['items']

    df = pd.DataFrame(items, columns=cabecera)
    df.fillna("", inplace=True)

    if action == 'analyze':
        # --- Lógica de Análisis ---
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str).str.strip()
        
        numeric_cols = ['valor', 'nura', 'comision']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        df['fecha_obj'] = pd.to_datetime(df['fecha'], dayfirst=True, errors='coerce').dt.date
        df.dropna(subset=['fecha_obj'], inplace=True) 
        
        if df.empty:
            return Response({'duplicados': [], 'items_filtrados': [], 'cabecera': cabecera})

        fecha_minima = df['fecha_obj'].min()
        fecha_maxima = df['fecha_obj'].max()

        registros_existentes = models.Transacciones_sucursal.objects.filter(
            fecha__range=(fecha_minima, fecha_maxima)
        ).values_list('establecimiento', 'terminal', 'fecha', 'cod_aut')
        
        existentes_set = set(
            (str(r[0]).strip(), str(r[1]).strip(), r[2], str(r[3]).strip()) 
            for r in registros_existentes
        )

        items_filtrados = []
        duplicados_info = []
        filas_vistas = set()

        for index, row in df.iterrows():
            fila_completa = list(row.drop('fecha_obj'))
            fecha_dt = row['fecha_obj']
            if pd.isna(fecha_dt):
                continue
            
            tupla_identificadora = (
                str(row.get('establecimiento', '')).strip(),
                str(row.get('terminal', '')).strip(),
                fecha_dt,
                str(row.get('cod_aut', '')).strip()
            )

            duplicado_encontrado = False
            if tupla_identificadora in filas_vistas:
                duplicados_info.append({'linea': index + 2, 'razon': 'Duplicado en archivo', 'datos': fila_completa})
                duplicado_encontrado = True
            
            if not duplicado_encontrado and tupla_identificadora in existentes_set:
                duplicados_info.append({'linea': index + 2, 'razon': 'Ya existe en BD', 'datos': fila_completa})
                duplicado_encontrado = True
            
            if duplicado_encontrado:
                continue

            filas_vistas.add(tupla_identificadora)
            items_filtrados.append(fila_completa)

        return Response({
            'duplicados': duplicados_info,
            'items_filtrados': items_filtrados,
            'cabecera': cabecera
        })

    elif action == 'save':
        # --- Lógica de Guardado ---
        transacciones_para_crear = []
        for item_row in items:
            row_dict = dict(zip(cabecera, item_row))

            try:
                valor = int(float(row_dict.get('valor', 0)))
                nura = int(float(row_dict.get('nura', 0)))
                comision = int(float(row_dict.get('comision', 0)))
                fecha_str = row_dict.get('fecha', '')
                
                fecha_dt = datetime.strptime(fecha_str, "%d/%m/%Y").date()
                
            except (ValueError, TypeError):
                continue
            
            transacciones_para_crear.append(
                models.Transacciones_sucursal(
                    establecimiento=row_dict.get('establecimiento', ''),
                    codigo_aval=row_dict.get('codigo_aval', ''),
                    codigo_incocredito=row_dict.get('codigo_incocredito', ''),
                    terminal=row_dict.get('terminal', ''),
                    fecha=fecha_dt,
                    hora=row_dict.get('hora', '00:00:00'),
                    nombre_convenio=row_dict.get('nombre_convenio', ''),
                    operacion=row_dict.get('operacion', ''),
                    fact_cta=row_dict.get('fact_cta', ''),
                    cod_aut=row_dict.get('cod_aut', ''),
                    valor= -valor if row_dict.get('operacion') == 'Retiro' else valor,
                    nura=nura,
                    esquema=row_dict.get('esquema', ''),
                    numero_tarjeta=row_dict.get('numero_tarjeta', ''),
                    comision=comision,
                )
            )
        
        if transacciones_para_crear:
            models.Transacciones_sucursal.objects.bulk_create(transacciones_para_crear, ignore_conflicts=True)
            
        return Response({'mensaje': f'{len(transacciones_para_crear)} registros procesados.'}, status=200)
    
    return Response({'error': 'Acción no especificada o inválida.'}, status=400)


@api_view(['POST'])
def calcular_comisiones(request):
    comisiones = models.Porcentaje_comision.objects.all()
    comisiones_dic = {i.nombre:i.valor for i in comisiones}

    def comision_servicios_hfc(row):
        red = row['RED']
        tipo = row['TIPO VENTA']
        convergencia = row['CONVERGENCIA']
        valor =row['TOTAL MENSUALIDAD']

        if red == 'HFC':
            if convergencia == 'Convergente':
                if tipo == 'CROSS SELLING' or tipo == 'NEW':
                    comision_valor = comisiones_dic['hfc new cross selling convergente']
                elif tipo == 'UP SELLING/FO' or tipo == 'UP SELLING':
                    comision_valor = comisiones_dic['hfc up selling convergente']
                else:
                    comision_valor = 0
            else:
                if tipo == 'CROSS SELLING' or tipo == 'NEW':
                    comision_valor = comisiones_dic['hfc new cross selling no convergente']
                elif tipo == 'UP SELLING/FO' or tipo == 'UP SELLING':
                    comision_valor = comisiones_dic['hfc up selling no convergente']
                else:
                    comision_valor = 0
            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_float = 0
        resultado = float(valor) * comision_float
        return resultado
    
    def aceleradores_hfc(row):
        red = row['RED']
        cantidad = row['cantidad']
        convergencia = row['CONVERGENCIA']
        valor =row['TOTAL MENSUALIDAD']
        if red == 'HFC' or red=='DTH':
            if convergencia == 'Convergente':
                if cantidad == 1:
                    comision_valor = comisiones_dic['hfc sencillo red dth convergente']
                elif cantidad == 2:
                    comision_valor = comisiones_dic['hfc doble hfc dth convergente']
                elif cantidad == 3:
                    comision_valor = comisiones_dic['hfc triple hfc dth convergente']
                else:
                    comision_valor = 0
                
            else:
                if cantidad == 1:
                    comision_valor = comisiones_dic['hfc sencillo red dth no convergente']
                elif cantidad == 2:
                    comision_valor = comisiones_dic['hfc doble hfc dth no convergente']
                elif cantidad == 3:
                    comision_valor = comisiones_dic['hfc triple hfc dth no convergente']
                else:
                    comision_valor = 0

            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_float = 0
        resultado = float(valor) * comision_float
        return resultado
    
    def comision_servicios_fo(row):
        red = row['RED']
        convergencia = row['CONVERGENCIA']
        valor =row['TOTAL MENSUALIDAD']

        if red == 'FO':
            if convergencia == 'Convergente':
                comision_valor = comisiones_dic['servicios fo convergente']
            else:
                comision_valor = comisiones_dic['servicios fo no convergente']
            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_float = 0
        resultado = float(valor) * comision_float
        return resultado
    
    def bono_velocidad_internet(row):
        red = row['RED']
        velocidad = row['VELOCIDAD']
        valor =row['TOTAL MENSUALIDAD']

        if red == 'FO':
            if velocidad == 'VEL_2':
                comision_valor = comisiones_dic['servicios fo vel 2']
            elif velocidad == 'VEL_3':
                comision_valor = comisiones_dic['servicios fo vel 3']
            elif velocidad == 'VEL_4':
                comision_valor = comisiones_dic['servicios fo vel 4']
            else:
                comision_valor = 0
            
            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_float = 0
        resultado = float(valor) * comision_float
        return resultado
    
    def bono_duracion_contrato(row):
        red = row['RED']
        duracion = row['DURACION CONTRATO']
        valor =row['TOTAL MENSUALIDAD']
        print(duracion, type(duracion), duracion==24)
        if red == 'FO':
            if duracion == 24:
                print('aca 24')
                comision_valor = comisiones_dic['servicios fo 24 meses']
                print(comision_valor)
            elif duracion == 36:
                print('aca 36')
                comision_valor = comisiones_dic['servicios fo 36 meses']
            elif duracion >= 48:
                print('aca 48')
                comision_valor = comisiones_dic['servicios fo 48 meses']
            else:
                comision_valor = 0
            
            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_valor = 0
            comision_float = 0
        resultado = float(valor) * comision_float
        print(resultado, valor, comision_float, comision_valor)
        return resultado
    
    def servicio_cloud_iaas(row):
        red = row['RED']
        duracion = row['DURACION CONTRATO']
        valor =row['TOTAL MENSUALIDAD']

        if red == 'FO':
            if duracion == 24:
                comision_valor = comisiones_dic['servicios fo 24 meses']
            elif duracion == 36:
                comision_valor = comisiones_dic['servicios fo 36 meses']
            elif duracion >= 48:
                comision_valor = comisiones_dic['servicios fo 48 meses']
            else:
                comision_valor = 0
            
            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_float = 0
        resultado = float(valor) * comision_float
        return resultado

    
    print('activado calcular comisiones')
    items = request.data['data']
    df = pd.DataFrame(items)
    df['comision servicios hfc'] = df.apply(comision_servicios_hfc, axis=1)
    df['guia_llave'] = df['LLAVE'].str[:17]
    paquetes = df.copy()
    paquetes['LLAVE2'] = paquetes['LLAVE'].str[:17]
    paquetes['cantidad'] = paquetes['LLAVE2']
    paquetes = paquetes[['LLAVE2', 'cantidad']].groupby(['LLAVE2']).count().reset_index()
    df = pd.merge(df, paquetes, left_on='guia_llave', right_on='LLAVE2', how='left')
    df['aceleradores hfc'] = df.apply(aceleradores_hfc, axis=1)
    df['comision servicios fo'] = df.apply(comision_servicios_fo, axis=1)
    df['bono velocidad internet'] = df.apply(bono_velocidad_internet, axis=1)
    df['bono duracion contrato'] = df.apply(bono_duracion_contrato, axis=1)

    print(paquetes)


    # for valorT in items:
    #     for clave in valorT:
    #         valor = valorT[clave]   
    #         if not isinstance(valor, float) or valor == float('inf') or valor == float('-inf') or valor != valor:
    #             print('este es el valor', valor)

    agregados =[
        'comision servicios hfc',
        'aceleradores hfc',
        'comision servicios fo',
        'bono velocidad internet',
        'bono duracion contrato',
    ]
    df['Total'] = df[agregados].sum(axis=1)
    df['TOTAL MENSUALIDAD'] = pd.to_numeric(df['TOTAL MENSUALIDAD'], errors='coerce')
    df['Porcentaje total'] = df['Total'] / df['TOTAL MENSUALIDAD'] * 100
    df['Porcentaje total'] = df['Porcentaje total'].astype(str) + '%'

    agregados.append('Total')
    agregados.append('Porcentaje total')

    df = df.drop(['guia_llave','LLAVE2','cantidad'], axis=1)
    df.fillna(0, inplace=True)
    df = df.astype(str)
    lista_df = df.to_dict(orient='records')

    return Response({'data': lista_df, 'agregados': agregados})

@api_view(['GET', 'POST'])
def porcentajes_comisiones(request):
    porcentajes = [
        'hfc new cross selling no convergente',
        'hfc new cross selling convergente',
        'hfc up selling no convergente',
        'hfc up selling convergente',
        'hfc sencillo red dth no convergente',
        'hfc sencillo red dth convergente',
        'hfc doble hfc dth no convergente',
        'hfc doble hfc dth convergente',
        'hfc triple hfc dth no convergente',
        'hfc triple hfc dth convergente',
        'total fijo 100-104,99% 1',
        'total fijo 105-109,99% 1',
        'total fijo 110-124,99% 1',
        'total fijo 125% 1',
        'total fijo 100-104,99% 2',
        'total fijo 105-109,99% 2',
        'total fijo 110-124,99% 2',
        'total fijo 125% 2',
        'total movil 80-89,99% 1',
        'total movil 90-109,99% 1',
        'total movil 110-124,99% 1',
        'total movil 125% 1',
        'total movil 80-89,99% 2',
        'total movil 90-109,99% 2',
        'total movil 110-124,99% 2',
        'total movil 125% 2',
        'servicios fo no convergente',
        'servicios fo convergente',
        'servicios fo vel 2',
        'servicios fo vel 3',
        'servicios fo vel 4',
        'servicios fo 24 meses',
        'servicios fo 36 meses',
        'servicios fo 48 meses',
        'servicios fo 0-49,9%',
        'servicios fo 50-79,9%',
        'servicios fo 80-99,9%',
        'servicios fo 100-104,9%',
        'servicios fo 105-109,9%',
        'servicios fo 110%',
        'iaas no convergente mes 1',
        'iaas convergente mes 1',
        'iaas no convergente mes 2',
        'iaas convergente mes 2',
        'iaas no convergente mes 3',
        'iaas convergente mes 3',
        'iaas no convergente mes 4',
        'iaas convergente mes 4',
        'saas no convergente mes 1',
        'saas convergente mes 1',
        'saas no convergente mes 2',
        'saas convergente mes 2',
        'saas no convergente mes 3',
        'saas convergente mes 3',
        'saas no convergente mes 4',
        'saas convergente mes 4',
    ]
    data_consulta = models.Porcentaje_comision.objects.all()
    df = list(data_consulta.values())
    diccionario = {i['nombre']:i['valor'] for i in df}
    
    if request.method == 'GET':
        data =[diccionario[i] for i in porcentajes]
        return Response({'comisiones':data})
    
    if request.method == 'POST':
        data_request = request.data
        save_data = [{'nombre':porcentajes[i], 'valor': data_request[i]} for i in range(len(porcentajes)) if data_request[i] != diccionario[porcentajes[i]]]
        print(save_data)
        for i in save_data:
            porcentaje = models.Porcentaje_comision.objects.get(nombre=i['nombre'])
            porcentaje.valor = i['valor']
            porcentaje.save()
        return Response({'respuesta':'data guardada'})

@api_view(['POST'])
def excel_precios(request):
    sin_data = '999999999.00'
    titulos = [
        'Producto',
        'Costo Actual',
        'Precio Publico Sin Iva',
        'Subdistribuidor Sin Iva',
        'Addi',
        'Cliente 0 A 5 Meses Sin Iva',
        'Cliente 6 A 23 Meses Sin Iva',
        'Cliente Mayor A 24 Meses Sin Iva',
        'Cliente Descuento Kit Prepago Sin Iva',
        'Sistecredito Sin Iva',
        'Premium Sin Iva',
        'Tramitar Sin Iva',
        'People Sin Iva',
        'Flamingo Sin Iva',
        'Fintech Oficinas Team Y Externos Sin Iva',
        'Fintech Zonificacion Subdistribuidores Y Externos Sin Iva',
        'Oficina Movil Sin Iva',
        'Cenestel',
        ]
    titulos_diccionario = {
        'Producto': 'Equipo',
        'Costo Actual': 'Costo',
        'Precio Publico Sin Iva': 'Precio publico',
        'Subdistribuidor Sin Iva': 'Precio sub',
        'Addi': 'Precio Addi',
        'Cliente 0 A 5 Meses Sin Iva': None,
        'Cliente 6 A 23 Meses Sin Iva': None,
        'Cliente Mayor A 24 Meses Sin Iva': None,
        'Cliente Descuento Kit Prepago Sin Iva': 'Descuento Kit',
        'Sistecredito Sin Iva': None,
        'Premium Sin Iva': 'Precio premium',
        'Tramitar Sin Iva': None,
        'People Sin Iva': None,
        'Flamingo Sin Iva': 'Precio Flamingo',
        'Fintech Oficinas Team Y Externos Sin Iva': 'Precio Fintech',
        'Fintech Zonificacion Subdistribuidores Y Externos Sin Iva': None,
        'Oficina Movil Sin Iva': None,
        'Cenestel': None,
    }
    cabecera = request.data['cabecera']
    for key, value in titulos_diccionario.items():
        for i in cabecera:
            if i['text'] == 'Precio Adelantos Valle' or i['text'] == 'Kit Valle':
                continue
            if value == i['text']:
                titulos_diccionario[key] = i['value']
                print('....................................1')
                print(value, key, i['value'])
                print('....................................1')

    data = [titulos]

    items = request.data['items']
    for precio in items:
        temp_fila = []
        for titulo in titulos:
            if titulos_diccionario[titulo] is None:
                temp_fila.append(sin_data)
            else:
                print('---------------------------------------------------------')
                print(titulos_diccionario)
                print(titulo)
                print(precio)
                print('--------------------------------')
                temp_fila.append(precio[int(titulos_diccionario[titulo])])
        data.append(temp_fila)
    
    return Response({'excel':data})

@api_view(['POST'])
def guardar_precios(request):
    cabecera = request.data['cabecera']
    items = request.data['items']
    
    if not items:
        return Response({'error': 'No hay items para guardar.'}, status=400)

    nueva_carga = models.Carga.objects.create()
    
    lista_de_precios_para_crear = []
    
    # Creamos un diccionario para mapear los nombres de la cabecera a sus índices
    header_map = {item['text']: i for i, item in enumerate(cabecera)}

    # Identificamos el índice de la columna del producto
    product_name_index = header_map.get('Equipo')

    for precio_row in items:
        # Extraemos el nombre del producto de su columna correcta
        if product_name_index is not None and product_name_index < len(precio_row):
            producto = precio_row[product_name_index]
        else:
            # Si no se encuentra el nombre del producto, omitimos esta fila
            continue

        # Iteramos sobre todos los campos de la cabecera, excepto el del producto
        for nombre_campo, index in header_map.items():
            if nombre_campo == 'Equipo':
                continue # Omitimos la columna del producto

            if index < len(precio_row):
                valor_raw = precio_row[index]
                
                # Validamos que el valor sea un número antes de intentar guardarlo
                if valor_raw is not None:
                    try:
                        # Limpiamos el valor de comas (,) y lo convertimos a un decimal
                        valor = decimal.Decimal(str(valor_raw).replace(',', ''))
                    except (decimal.InvalidOperation, ValueError):
                        # Si la conversión falla, mostramos un mensaje en la consola y saltamos este registro
                        print(f"Omitiendo valor inválido '{valor_raw}' para el producto '{producto}' en el campo '{nombre_campo}'")
                        continue
                        
                    lista_de_precios_para_crear.append(
                        models.Lista_precio(
                            producto=producto,
                            nombre=nombre_campo,
                            valor=valor,
                            carga=nueva_carga
                        )
                    )
    
    if lista_de_precios_para_crear:
        models.Lista_precio.objects.bulk_create(lista_de_precios_para_crear)
    
    return Response({'data': 'Datos guardados exitosamente'})


@api_view(['POST'])
def consultar_formula(request):
    nombre = request.data['nombre']
    print(nombre)
    consulta = models.Formula.objects.filter(nombre=nombre).first()
    formula = consulta.formula
    formula_lista = ast.literal_eval(formula)
    print(consulta.formula)
    # formula_lista = []
    return Response({'formula':formula_lista})




@api_view(['POST'])
def guardar_formula(request):
    formula = request.data['funtion']
    nombre = request.data['nombre']
    texto = str(formula)
    token = request.data['jwt']
    try:
        payload = jwt.decode(token, 'secret', algorithms='HS256')
        usuario = User.objects.get(username=payload['id'])
    except:
        raise AuthenticationFailed('Error con usuario')
    formula_obj, created = models.Formula.objects.get_or_create(
        nombre=nombre,
        defaults={
            'formula': texto,
            'usuario': usuario,
        }
    )

    if not created:
        # El objeto ya existía, actualiza los campos necesarios
        formula_obj.formula = formula
        formula_obj.usuario = usuario
        formula_obj.save()

    return Response({'data':''})


@api_view(['POST'])
def prueba_formula(request):
    formula = request.data['funtion']
    diccionario = request.data['dic']
    nombre = request.data['price']
    if isinstance(formula, list):
        formula = ' '.join(formula)
    else:
        formula = ' '.join(formula.split())
    variables = {k: float(v) for k, v in diccionario.items()}
    variables2 = models.Variables_prices.objects.filter(price=nombre['id'])
    variables2 = {variable.name : ' '.join(variable.formula.split()) for variable in variables2}
    variables3 = models.Variables_prices.objects.filter(price=1)
    variables3 = {variable.name : ' '.join(variable.formula.split()) for variable in variables3}
    variables2 = variables2 | variables3
    consulta = models.Formula.objects.filter(nombre='Precio publico').first()
    formula_publico = consulta.formula
    formula_lista = ast.literal_eval(formula_publico)
    formula2 = ' '.join(formula_lista)
    variables2 = variables2 | {'precioPublico': formula2, 'PrecioPublico': formula2}
    for i in range(10):
        for key, value in variables2.items():
            formula = formula.replace(key,value)    
    # formula = formula.replace('=','==')
    # formula = formula.replace('> ==','>=')
    # formula = formula.replace('< ==','<=')
    resultado = eval(formula, variables)
    print(formula)
    print(diccionario)
    print(resultado)
    print(nombre)
    return Response({'data':resultado})

@api_view(['POST'])
def contactanos(request):
    nombre = request.data['nombre']
    correo = request.data['correo']
    asunto = request.data['asunto']
    mensaje = request.data['mensaje']
    models.Contactanos.objects.create(
        nombre = nombre,
        correo = correo,
        asunto = asunto,
        mensaje = mensaje,
    )
    return Response({'data':'data'})

@api_view(['POST'])
def informes(request):
    start = request.data['start']
    end = request.data['end']
    arrowup='\u25B2'
    arrowdown = '\u25BC'
    fecha_inicio_2023 = datetime.datetime(int(start[0:4]), int(start[5:7]), int(start[8:10]))
    fecha_fin_2023 = datetime.datetime(int(end[0:4]), int(end[5:7]), int(end[8:10]), 23, 59, 59)
    fecha_inicio_2023_sql = fecha_inicio_2023.strftime('%Y-%m-%d %H:%M:%S')
    fecha_fin_2023_sql = fecha_fin_2023.strftime('%Y-%m-%d %H:%M:%S')
    query = (
        f"SELECT Fac.Numero, Fac.Fecha, Ter.Identificacion,  "
        f"ValorBruto, ValorIva, ValorDescuento, ValorFlete, "
        f"ReteFuente, ReteIca, ReteIva, OtroImp1, OtroImp2, "
        f"ValorNeto, Ubi.Nombre "
        f"FROM dbo.Facturas Fac "
        f"JOIN dbo.Terceros Ter ON Fac.Tercero = Ter.Codigo "
        f"JOIN dbo.Ubicaciones Ubi ON Fac.Ubicacion = Ubi.Codigo "
        f"WHERE Fecha >= '{fecha_inicio_2023_sql}' AND Fecha <= '{fecha_fin_2023_sql}'"
    )
    conexion = Sql_conexion(query)
    rows = conexion.get_data()
    columns = [column[0] for column in conexion.description]
    print(columns)
    columns[len(columns)-1] = 'Ubicacion'
    # columns.append('Ubicacion')
    df = pd.DataFrame.from_records(rows, columns=columns)
    periodo = 'mes' if (fecha_fin_2023 - fecha_inicio_2023).days > 31 else 'dia'
    if periodo == 'mes':
        df['Fecha'] = df['Fecha'].dt.strftime('%Y-%m')
    if periodo == 'dia':
        df['Fecha'] = df['Fecha'].dt.strftime('%Y-%m-%d')
    ventasPeriodo = df[['ValorNeto', 'Fecha']].groupby('Fecha').sum().reset_index()
    print(fecha_inicio_2023_sql)
    print(fecha_fin_2023_sql)
    median = ventasPeriodo['ValorNeto'][:-1].median()
    ultimoValor = float(ventasPeriodo['ValorNeto'].iloc[-1])
    periodo = (ventasPeriodo['Fecha'].iloc[-1])
    delta = round((ultimoValor- median) / median * 100, 2)
    if delta > 0:
        arrow = arrowup
        color = '#c0ca33'
    else:
        arrow = arrowdown
        delta = delta * -1
        color = '#f4511e'
    delta = f'{arrow}{delta}%'
    ultimoValor = f'${formating_numbers(ultimoValor)}'
    label = ventasPeriodo['Fecha'].tolist()
    values = ventasPeriodo['ValorNeto'].tolist()

    ubicaciones = df[['ValorNeto', 'Ubicacion']].groupby('Ubicacion').sum().reset_index()
    labelPie = ubicaciones['Ubicacion'].tolist()
    valuesPie = ubicaciones['ValorNeto'].tolist()
    cantidadPie = len(ubicaciones)

    query2 =(
        f"SELECT Pro.Nombre, Df.Cantidad, Df.PrecioVenta "
        f"FROM dbo.DetallesXFacturas Df "
        f"JOIN dbo.Facturas Fac ON Df.Factura = Fac.Codigo "
        f"JOIN dbo.Productos Pro ON Df.Producto = Pro.Codigo "
        f"WHERE Fac.Fecha >= '{fecha_inicio_2023_sql}' AND Fac.Fecha <= '{fecha_fin_2023_sql}'"
    )

    conexion = Sql_conexion(query2)
    columns = [column[0] for column in conexion.description]
    rows = conexion.get_data()
    df = pd.DataFrame.from_records(rows, columns=columns)
    productos = df[['Nombre', 'Cantidad', 'PrecioVenta']].groupby('Nombre').sum().reset_index()
    productos = productos.sort_values(by='Cantidad', ascending=False)
    productos = productos.head(5)
    productos['PrecioVenta'] = productos['PrecioVenta'].astype(float)
    listaProductos = productos.to_dict(orient='records')


    data = {
        'median': str(median),
        'ultimoValor': str(ultimoValor),
        'delta': str(delta),
        'periodo': periodo,
        'color': color,
        'label': label,
        'values': values,
        'productos': listaProductos,
        'labelPie': labelPie,
        'valuesPie' : valuesPie,
        'cantidadPie': cantidadPie,
    }
    print(data)

    return Response(data)

@api_view(['GET'])
def tienda(request):
    plan = models.Imagenes.objects.all()
    data = []
    for i in plan:
        print(i.id)
        data.append({
            'id':i.id, 
            'img':i.url, 
            'titulo':i.titulo, 
            'detalle':i.detalle, 
            'precio':i.precio,
            'marca':i.marca,
            })
    return Response({'data':data})

@api_view(['GET'])
def productos(request):
    plan = models.Imagenes.objects.filter(carpeta='productos')
    data = []
    for i in plan:
        print(i.id)
        data.append({'id':i.id, 'img':i.url, 'titulo':i.titulo, 'detalle':i.detalle, 'precio':i.precio})
    return Response({'data':data})

@api_view(['GET'])
def planes(request):
    plan = models.Imagenes.objects.filter(carpeta='planes')
    data = []
    for i in plan:
        print(i.id)
        data.append({'id':i.id, 'img':i.url, 'titulo':i.titulo, 'detalle':i.detalle, 'precio':i.precio})
    return Response({'data':data})

@api_view(['POST'])
def cargarImagen(request):
    nombre = str(uuid.uuid4()) +'.png'
    titulo = request.POST.get('titulo')
    detalle = request.POST.get('detalle')
    precio = request.POST.get('valor')
    imagen = request.FILES.get('imagen')
    carpeta = request.POST.get('carpeta')
    print(type(imagen))
    ruta_carpeta_destino = ''
    ruta_carpeta_destino2 = ruta + '\\'+carpeta+'\\'
    if not default_storage.exists(ruta_carpeta_destino):
        default_storage.makedirs(ruta_carpeta_destino)
    nueva_ruta_imagen = default_storage.path(os.path.join(ruta_carpeta_destino, nombre))
    with default_storage.open(nueva_ruta_imagen, 'wb') as destino:
        destino.write(imagen.read())
    ruta_carpeta_destino = os.path.join(ruta_carpeta_destino, nombre)
    shutil.move(ruta_carpeta_destino, ruta_carpeta_destino2)
    models.Imagenes.objects.create(
        url = nombre,
        titulo = titulo,
        detalle = detalle,
        precio = precio,
        carpeta = carpeta,
    )

    return Response({'data':'d'})

@api_view(['POST'])
def deleteImagen(request):
    id = request.data['id']
    objeto = models.Imagenes.objects.get(id=id)
    nombre = objeto.url
    carpeta = request.data['carpeta']
    ruta_carpeta_destino = ruta + '\\'+carpeta+'\\'
    objeto.delete()
    ruta_eliminar = os.path.join(ruta_carpeta_destino, nombre)
    os.remove(ruta_eliminar)
    return Response({'data':'d'})


def shopify_token(request):
    api_key = 'd37d57aff7101337661ae6594f0f38d5'	#Set Partner app api key
    api_secret = '3ec5b155828a868687ef85444f88601f' #Set Partner app api secret
    scopes = 'write_products,read_content,read_discounts,read_locales'
    redirect_uri = 'https://api.teamcomunicaciones.com.co/api/v1.0/shopify-return'
    shop = 'quickstart-06207d6f.myshopify.com'
    nonce = random.random() 
    url = "https://{}/admin/oauth/authorize?client_id={}&scope={}&redirect_uri={}&state={}&grant_options[]=offline-access".format(shop, api_key,  scopes, redirect_uri, nonce)
    return redirect(url)

@api_view(['GET'])
def shopify_return(request):
    api_key = 'd37d57aff7101337661ae6594f0f38d5'	#Set Partner app api key
    api_secret = '3ec5b155828a868687ef85444f88601f' #Set Partner app api secret
    code = request.GET.get('code', '')
    shop = request.GET.get('shop', '')
    url = 'https://{}/admin/oauth/access_token'.format(shop)
    myobj = {'client_id': api_key,'client_secret': api_secret,'code': code}

    x = requests.post(url, data = myobj)
    respuesta = x.json()['access_token']
    return Response({"message":respuesta, "code": code})
    

@api_view(['POST'])
def login(request):
    email = request.data.get('email')
    password = request.data.get('password')

    if not email or not password:
        raise AuthenticationFailed('El email y la contraseña son requeridos.')

    user = authenticate(request, username=email, password=password)

    if user is not None:
        payload = {
            'id': user.id,
            # 👇 ESTA ES LA FORMA CORRECTA con "from datetime import datetime"
            'exp': datetime.utcnow() + timedelta(minutes=60),
            'iat': datetime.utcnow(),
            'change': True if password == 'Cambiame123' else False
        }

        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
        print("="*20)
        print("TOKEN CREADO EN LOGIN:")
        print(token)
        print("="*20)
        response = Response()
        response.set_cookie(key='jwt', value=token, httponly=True)
        response.data = {
            'jwt': token
        }
        return response
    else:
        raise AuthenticationFailed('Usuario o contraseña incorrectos.')

@api_view(['GET', 'POST', 'OPTIONS'])
def create_user(request):
    if request.method == 'POST':
        user = request.data['email']
        password = request.data['password']

    
    raise AuthenticationFailed('Solo metodo POST')

@api_view(['POST'])
def user_validate(request):
    # Esta vista parece que solo valida si el token es correcto.
    # La forma de obtener el token del cuerpo de la solicitud es un poco inusual,
    # generalmente se envía en la cabecera 'Authorization', como en la otra vista.

    try:
        token = request.data.get('jwt') # Es más seguro usar .get()
        if not token:
            raise AuthenticationFailed('Token no proporcionado.')

        # SOLUCIÓN 1: Usar la SECRET_KEY de Django
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])

        # Aquí podrías verificar si el usuario del token aún existe
        user = User.objects.filter(id=payload['id']).first()
        if not user:
             raise AuthenticationFailed('El usuario del token ya no existe.')

    except jwt.InvalidSignatureError:
        raise AuthenticationFailed('Firma del token inválida.')
    except jwt.ExpiredSignatureError:
        raise AuthenticationFailed('El token ha expirado.')
    except Exception: # Captura cualquier otro error
        raise AuthenticationFailed('Token inválido.')

    # Si todo sale bien, retornas una respuesta exitosa.
    return Response({"detail": "Token validado correctamente."})

@api_view(['GET'])
def user_permissions(request):
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return Response({'detail': 'Token no proporcionado.'}, status=401)

        token = auth_header.split(' ')[1]
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        
        # --- LÍNEA CORREGIDA ---
        # Buscamos al usuario por su ID, no por su username
        usuario = User.objects.get(id=payload['id'])

        if getattr(usuario, 'force_password_change', False):
            return Response({"cambioClave": True})

        permisos_dict = {
            'superadmin': usuario.is_superuser,
            'administrador': {'main': False}, 'informes': {'main': False},
            'control_interno': {'main': False}, 'gestion_humana': {'main': False},
            'contabilidad': {'main': False}, 'comisiones': {'main': False},
            'soporte': {'main': False}, 'auditoria': {'main': False},
            'comercial': {'main': False}, 'corresponsal': {'main': False},
            'caja': {'main': False},
        }

        permisos_usuario = models.Permisos_usuarios.objects.filter(user=usuario).select_related('permiso')

        for p_usuario in permisos_usuario:
            permiso_name = p_usuario.permiso.permiso.lower()
            if permiso_name in permisos_dict:
                if permiso_name == 'superadmin':
                    permisos_dict[permiso_name] = p_usuario.tiene_permiso
                else:
                    permisos_dict[permiso_name]['main'] = p_usuario.tiene_permiso
        
        return Response({
            "permisos": permisos_dict,
            "usuario": usuario.username,
            "cambioClave": False
        })

    except jwt.InvalidSignatureError:
        return Response({'detail': 'Firma del token inválida.'}, status=401)
    except jwt.ExpiredSignatureError:
        return Response({'detail': 'Token ha expirado.'}, status=401)
    except User.DoesNotExist:
        return Response({'detail': 'Usuario del token no es válido.'}, status=401)
    except Exception as e:
        return Response({'detail': f'Error interno: {str(e)}'}, status=500)

@api_view(['POST'])
def cambio_clave(request):
    print('d')
    if request.method == 'POST':
        contraseña = request.data['password']
        contraseña2 = request.data['retrypassword']
        token = request.data['jwt']
        if contraseña == contraseña2:
            print(contraseña, contraseña2, token)
            if not token:
                raise AuthenticationFailed('Debes estar logueado')
            try:
                payload = jwt.decode(token, 'secret', algorithms='HS256')
                usuario = User.objects.get(username=payload['id'])
            except jwt.ExpiredSignatureError:
                raise AuthenticationFailed('Debes estar logueado')
            
            usuario.set_password(contraseña)
            usuario.save()
            return Response({"usuarios": ''})
        else:
            raise AuthenticationFailed('Las contraseñas deben ser iguales')

@api_view(['GET'])
def permissions_matrix(request):
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise AuthenticationFailed('Token de autorización faltante o con formato incorrecto.')
        
        token = auth_header.split(' ')[1]
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        
        # --- LÍNEA CORREGIDA ---
        # Busca por 'id' en lugar de 'username'
        solicitante = User.objects.get(id=payload['id']) 
        
        if not solicitante.is_superuser:
            raise AuthenticationFailed('Solo los superusuarios pueden ver los permisos.')

        todos_los_permisos = list(models.Permisos.objects.all())
        todos_los_usuarios = list(User.objects.all())
        permisos_asignados = models.Permisos_usuarios.objects.filter(tiene_permiso=True).values('user_id', 'permiso__permiso')

        roles_disponibles = [
            {"name": p.permiso, "label": p.permiso.replace('_', ' ').capitalize()}
            for p in todos_los_permisos
        ]
        
        permisos_por_usuario = {}
        for p_asignado in permisos_asignados:
            user_id = p_asignado['user_id']
            permiso_name = p_asignado['permiso__permiso']
            if user_id not in permisos_por_usuario:
                permisos_por_usuario[user_id] = set()
            permisos_por_usuario[user_id].add(permiso_name)

        usuarios_con_permisos = []
        for usuario in todos_los_usuarios:
            # Corrección potencial: Asegurarse de que el usuario.id exista en el dict
            roles = {rol['name']: usuario.id in permisos_por_usuario and rol['name'] in permisos_por_usuario[usuario.id] 
                     for rol in roles_disponibles}
            usuarios_con_permisos.append({
                'user_id': usuario.id,
                'username': usuario.username,
                'roles': roles
            })
        
        return Response({
            "roles": roles_disponibles,
            "users_permissions": usuarios_con_permisos
        })

    except (AuthenticationFailed, User.DoesNotExist, jwt.ExpiredSignatureError, jwt.DecodeError) as e:
        # User.DoesNotExist será capturado aquí si el ID del token no es válido
        return Response({'detail': str(e)}, status=401)
    except Exception as e:
        return Response({'detail': f'Error inesperado: {str(e)}'}, status=500)


@api_view(['POST'])
def permissions_edit(request):
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise AuthenticationFailed('Token de autorización faltante o con formato incorrecto.')
        
        token = auth_header.split(' ')[1]
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        
        # --- LÍNEA CORREGIDA ---
        solicitante = User.objects.get(id=payload['id']) # <-- Aquí está el cambio
        
        if not solicitante.is_superuser:
            raise AuthenticationFailed('Solo los superusuarios pueden editar permisos.')

        with transaction.atomic():
            data_a_guardar = request.data.get('data', [])
            
            user_ids = [item['user_id'] for item in data_a_guardar]
            # Es más seguro filtrar por el user_id del solicitante
            # pero asumimos que un superuser puede editar a todos.
            models.Permisos_usuarios.objects.filter(user_id__in=user_ids).delete()

            permisos_a_crear = []
            # Traer solo los permisos necesarios es más eficiente
            todos_los_permisos_map = {p.permiso: p for p in models.Permisos.objects.all()}
            
            for item_usuario in data_a_guardar:
                user_id = item_usuario['user_id']
                for permiso_name, tiene_permiso in item_usuario['roles'].items():
                    if tiene_permiso:
                        permiso_obj = todos_los_permisos_map.get(permiso_name)
                        if permiso_obj:
                            permisos_a_crear.append(
                                models.Permisos_usuarios(
                                    user_id=user_id,
                                    permiso=permiso_obj,
                                    tiene_permiso=True
                                )
                            )
            
            models.Permisos_usuarios.objects.bulk_create(permisos_a_crear)

        return Response({"detail": "Permisos guardados con éxito"})

    except (AuthenticationFailed, User.DoesNotExist, jwt.ExpiredSignatureError, jwt.DecodeError) as e:
        return Response({'detail': str(e)}, status=401)
    except Exception as e:
        return Response({'detail': f'Error inesperado al guardar: {str(e)}'}, status=500)
    
    
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.exceptions import AuthenticationFailed
import json
from . import models
from django.db.utils import IntegrityError

@api_view(['GET', 'POST'])
def translate_products_prepago(request):
    if request.method == 'GET':
        productos_en_lista_negra = models.Lista_negra.objects.values_list('equipo', flat=True)
        traducciones = models.Traducciones.objects.filter(tipo='prepago').exclude(equipo__in=productos_en_lista_negra)
        
        data = []
        for i in traducciones:
            subdata = {
                'producto': i.equipo,
                'stok': i.stok,
                'iva': i.iva,
                'active': i.active,
            }
            data.append(subdata)
        
        data = sorted(data, key=lambda x: x['producto'].lower())
        return Response(data)
    
    if request.method == 'POST':
        try:
            data = request.body
            data = json.loads(data)
            equipo = data['equipo']
            stok = data['stok']
            iva = data['iva']
            active = data['active']
            tipo = 'prepago'
            
            query = (
                "SELECT TOP(1000) P.Nombre, lPre.nombre, ValorBruto "
                "FROM dbo.ldpProductosXAsociaciones lProd "
                "JOIN dbo.ldpListadePrecios lPre ON lProd.ListaDePrecios = lPre.Codigo "
                "JOIN dbo.Productos P ON lProd.Producto = P.Codigo "
                "JOIN dbo.TiposDeProducto TP ON P.TipoDeProducto = TP.Codigo "
                f"WHERE TP.Nombre = 'Prepagos' and P.Visible = 1 and P.Nombre = '{stok}';"
            )
            conexion = Sql_conexion(query)
            data2 = conexion.get_data()
            if len(data2) == 0:
                raise AuthenticationFailed('Producto inexistente en Stok')

            listaStok = []
            for dato in data2:
                nombreStok = dato[0]
                if nombreStok not in listaStok:
                    listaStok.append(nombreStok)
            for nstok in listaStok:
                validacion = nstok == stok
                if not validacion:
                    raise AuthenticationFailed(f'intente usar {nstok} y no {stok}')

            traduccion, created = models.Traducciones.objects.update_or_create(
                equipo=equipo,
                defaults={
                    'stok': stok,
                    'iva': iva,
                    'active': active,
                    'tipo': tipo
                }
            )
            
            if created:
                return Response({'message': 'Equipo creado con exito'}, status=201)
            else:
                return Response({'message': 'Equipo actualizado con exito'}, status=200)

        except KeyError:
            return Response({'error': 'Faltan campos obligatorios'}, status=400)
        except IntegrityError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            return Response({'error': str(e)}, status=400)

@api_view(['DELETE'])
def delete_translate_product_admin(request):
    try:
        equipo_a_inactivar = request.data.get('equipo')
        if not equipo_a_inactivar:
            return Response(
                {'error': 'El campo "equipo" es requerido.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        traduccion = models.Traducciones.objects.filter(equipo=equipo_a_inactivar).first()

        if traduccion:
            traduccion.active = '0'
            traduccion.save()
            return Response(
                {'message': f'El producto "{equipo_a_inactivar}" fue enviado a la lista negra (inactivado).'},
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {'error': 'El producto no fue encontrado.'},
                status=status.HTTP_404_NOT_FOUND
            )
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Helper function to clean currency values
def limpiar_valor_moneda(valor):
    if valor is None:
        return Decimal('0')
    try:
        # If it's already a number, convert to Decimal and return
        return Decimal(valor)
    except InvalidOperation:
        # If it's a string, clean it
        if isinstance(valor, str):
            # Remove '$', '.', and spaces, then convert
            valor_limpio = valor.replace('$', '').replace('.', '').strip()
            if valor_limpio:
                return Decimal(valor_limpio)
    return Decimal('0')

def debug_precio_publico(request):
    try:
        # 1. Obtenemos la lista de stoks de tus traducciones activas.
        stoks_con_traduccion = list(models.Traducciones.objects.filter(active=True).values_list('stok', flat=True))

        # 2. Hacemos la consulta EXACTA que está fallando:
        # Buscamos en Lista_precio productos que estén en nuestra lista de stoks Y que el nombre sea 'Precio Publico' (ignorando mayúsculas).
        resultados = models.Lista_precio.objects.filter(
            producto__in=stoks_con_traduccion,
            nombre__iexact='Precio Publico'  # Búsqueda insensible a mayúsculas
        )

        # 3. Preparamos una respuesta clara para ver qué encontró Django.
        datos_encontrados = list(resultados.values('producto', 'nombre', 'valor'))
        sql_query = str(resultados.query)

        respuesta = {
            "MENSAJE": "Resultados del diagnóstico directo a la base de datos.",
            "PASO_1_STOKS_EN_TRADUCCIONES": {
                "total_stoks_activos_encontrados": len(stoks_con_traduccion),
                "ejemplo_de_stoks": stoks_con_traduccion[:10]
            },
            "PASO_2_RESULTADOS_DE_LA_CONSULTA": {
                "total_precios_encontrados": len(datos_encontrados),
                "ejemplo_de_precios": datos_encontrados[:10]
            },
            "SQL_EXACTO_EJECUTADO": sql_query
        }
        
        return JsonResponse(respuesta, safe=False, json_dumps_params={'indent': 4})

    except Exception as e:
        return JsonResponse({"ERROR": str(e)})

@api_view(['POST'])
def translate_prepago(requests):
    if requests.method == 'POST':
        iva = 1095578
        
        translates = models.Traducciones.objects.filter(tipo='prepago').values('equipo', 'stok', 'iva', 'active', 'tipo')
        df_translates = pd.DataFrame(translates)
        
        black_list = models.Lista_negra.objects.all().values_list('equipo', flat=True)
        
        data = requests.data
        df_equipos = pd.DataFrame(data)
        df_equipos = df_equipos[~df_equipos[0].isin(black_list)]
        df_equipos.columns = ['equipo', 'valor', 'descuento', 'costo']
        
        precios = models.Formula.objects.all().order_by('id')
        
        all_variables_prices = models.Variables_prices.objects.all().values()
        variables_by_price = {}
        for var in all_variables_prices:
            price_id = var['price_id']
            if price_id not in variables_by_price:
                variables_by_price[price_id] = {}
            variables_by_price[price_id][var['name']] = ' '.join(var['formula'].split())

        equipos_origen = df_equipos['equipo']
        equipos_translate = df_translates['equipo']
        equipos_no_encontrados = equipos_origen[~equipos_origen.isin(equipos_translate)]

        if len(equipos_no_encontrados) > 0:
            validate = False
            data_response = equipos_no_encontrados.to_list()
            cabecera = []
        else:
            validate = True
            nuevo_df = df_equipos.merge(df_translates, on='equipo', how='left')
            nuevo_df = nuevo_df.drop_duplicates()
            
            data_response = []
            cabecera = [{'text': 'Equipo', 'value': '0'}]
            
            contador = 1
            for precio in precios:
                cabecera.append({'text': precio.nombre, 'value': str(contador)})
                contador += 1
                if 'Precio Fintech' in precio.nombre:
                    cabecera.append({'text': 'Kit Fintech', 'value': str(contador)})
                    contador += 1
                elif 'Precio Addi' in precio.nombre:
                    cabecera.append({'text': 'Kit Addi', 'value': str(contador)})
                    contador += 1
                elif 'Precio premium' in precio.nombre:
                    cabecera.append({'text': 'Kit Premium', 'value': str(contador)})
                    contador += 1
                elif 'Precio sub' in precio.nombre:
                    cabecera.append({'text': 'Kit Sub', 'value': str(contador)})
                    contador += 1
                elif 'Precio Adelantos Valle' in precio.nombre:
                    cabecera.append({'text': 'Kit Valle', 'value': str(contador)})
                    contador += 1
            
            cabecera.append({'text': 'descuento', 'value': str(contador)})
            
            lista_produtos = set()
            formula_publico_obj = models.Formula.objects.filter(nombre='Precio publico').first()
            formula2 = ' '.join(ast.literal_eval(formula_publico_obj.formula)) if formula_publico_obj else ''

            for _, row in nuevo_df.iterrows():
                if row['stok'] in lista_produtos:
                    continue
                lista_produtos.add(row['stok'])
                
                temp_data = [row['stok']]
                for precio in precios:
                    variables2 = variables_by_price.get(precio.price_id_id, {})
                    if precio.price_id_id != 1:
                        variables1 = variables_by_price.get(1, {})
                        variables2 = {**variables1, **variables2}
                    
                    dict_formula = ast.literal_eval(precio.formula)
                    formula = ' '.join(dict_formula)
                    
                    if precio.id < 9:
                        formula = formula.replace('=','==')
                        formula = formula.replace('> ==','>=')
                        formula = formula.replace('< ==','<=')
                        formula = formula.replace('costo','Costo')
                        formula = formula.replace('valor','Valor')
                        formula = formula.replace('descuento','Descuento')
                    
                    formula = formula.replace('precioPublico', formula2)
                    variables2 = {**variables2, 'precioPublico': formula2, 'PrecioPublico': formula2, 'Sub': '', 'Premium': '', 'Fintech': '', 'Addi': '', 'Valle': ''}

                    for i in range(10):
                        for key, value in variables2.items():
                            formula = formula.replace(key, value)
                    
                    variables = {
                        'Valor': row['valor'],
                        'Costo': row['costo'],
                        'Descuento': row['descuento'],
                        'iva': iva
                    }
                    
                    kit = 0
                    kit_comprobante = False
                    
                    try:
                        resultado = eval(formula, variables)
                    except NameError:
                        resultado = 0 

                    if 'Precio Fintech' in precio.nombre or 'Precio Addi' in precio.nombre or 'Precio Adelantos Valle' in precio.nombre:
                        kit_comprobante = True
                        if resultado + 2380 >= iva and row['valor'] < iva:
                            kit = resultado - iva + 2380
                            resultado = iva - 2380
                    elif 'Precio premium' in precio.nombre:
                        kit_comprobante = True
                        if row['valor'] >= iva:
                           kit = resultado * 0.19
                    elif 'Precio sub' in precio.nombre:
                        kit_comprobante = True
                        if row['valor'] >= iva:
                            kit = resultado * 0.19
                    
                    temp_data.append(resultado)
                    if kit_comprobante:
                        temp_data.append(kit)
                
                temp_data.append(row['descuento'])
                data_response.append(temp_data)

        return Response({'validate': validate, 'data': data_response, 'crediminuto': [], 'cabecera': cabecera})

from rest_framework.views import APIView

class ListaProductosPrepagoEquipo(APIView):
    def post(self, request, format=None):
        try:
            precio = request.data['precio']
            equipo = request.data['equipo']
            
            qs = models.Lista_precio.objects.filter(
                producto=equipo, 
                nombre=precio
            ).order_by('-carga__fecha_carga')
            
            if not qs.exists():
                return Response({'data': []})
            
            df = pd.DataFrame(list(qs.values('producto', 'valor', 'carga__fecha_carga')))
            df.rename(columns={'valor': 'valor_actual', 'carga__fecha_carga': 'fecha'}, inplace=True)
            df['valor_anterior'] = df['valor_actual'].shift(-1)
            df.fillna({'valor_anterior': 0}, inplace=True)
            df['variation'] = df.apply(calcular_variacion, axis=1)

            sim = Decimal('2000')
            base = Decimal('1095578')
            new_data = []

            for _, row in df.iterrows():
                variacion_data = row.get('variation')
                valor_actual = Decimal(row.get('valor_actual', 0))
                iva = valor_actual * Decimal('0.19') if valor_actual >= base else Decimal('0')

                tem_data = {
                    'equipo': row.get('producto'),
                    'fecha': row.get('fecha'),
                    'equipo sin IVA': float(valor_actual),
                    'valor_anterior': float(row.get('valor_anterior', 0)),
                    'precio simcard': float(sim),
                    'IVA simcard': float(sim * Decimal('0.19')),
                    'IVA equipo': float(iva),
                    'total': float(sim * Decimal('1.19') + valor_actual + iva),
                    'indicador': variacion_data.get('indicador'),
                    'diferencial': variacion_data.get('diferencial'),
                    'porcentaje': variacion_data.get('porcentaje'),
                }
                new_data.append(tem_data)
            
            return Response({'data': new_data})
        except Exception as e:
            print(f"ERROR en /lista-productos-prepago-equipo: {str(e)}")
            return Response({'detail': f'Error interno: {str(e)}'}, status=500)

def calcular_variacion(row):
    valor_anterior_raw = row.get('valor_anterior')

    if pd.isna(valor_anterior_raw):
        return {'indicador': 'neutral', 'diferencial': 0, 'porcentaje': 0}

    valor_actual = float(row.get('valor_actual', 0))
    valor_anterior = float(valor_anterior_raw)

    if valor_actual == valor_anterior:
        return {'indicador': 'neutral', 'diferencial': 0, 'porcentaje': 0}

    elif valor_actual > valor_anterior:
        dif = valor_actual - valor_anterior
        percentage = (dif / valor_anterior) * 100 if valor_anterior > 0 else 100.0
        return {'indicador': 'up', 'diferencial': dif, 'porcentaje': round(percentage, 2)}

    elif valor_actual < valor_anterior:
        dif = valor_anterior - valor_actual
        percentage = (dif / valor_anterior) * 100 if valor_anterior > 0 else 0
        return {'indicador': 'down', 'diferencial': dif, 'porcentaje': round(percentage, 2)}
# views.py 

@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
# @permission_classes([IsAuthenticated]) # Deberías proteger esta vista
def upload_sales_report(request):
    """
    Recibe un archivo excel en 'report_file' y lo procesa.
    """
    report_file = request.FILES.get('report_file')
    if not report_file:
        return Response({'detail': 'No se proporcionó ningún archivo.'}, status=status.HTTP_400_BAD_REQUEST)

    if not report_file.name.endswith(('.xlsx', '.xls')):
        return Response({'detail': 'Formato de archivo no válido. Se requiere .xlsx o .xls.'}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        result = process_sales_report_file(report_file)
        if result['status'] == 'error':
            return Response({'detail': result['message']}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            'detail': 'Archivo procesado correctamente.',
            'nuevos_registros': result['creados'],
            'registros_omitidos_por_duplicado': result['existentes']
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({'detail': f'Ocurrió un error interno inesperado: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- VISTA PARA OBTENER DATOS DEL DASHBOARD ---
@api_view(['GET'])
# @permission_classes([IsAuthenticated]) # También proteger esta
def get_sales_dashboard_data(request):
    """
    Devuelve datos agregados para el dashboard, con filtros opcionales.
    Filtros posibles: fecha_inicio, fecha_fin, sucursal, clasificacion_venta
    """
    queryset = ReporteDetalleVenta.objects.all()

    # Aplicar filtros desde los query params
    fecha_inicio = request.query_params.get('fecha_inicio')
    fecha_fin = request.query_params.get('fecha_fin')
    sucursal = request.query_params.get('sucursal')
    clasificacion = request.query_params.get('clasificacion_venta')

    if fecha_inicio:
        queryset = queryset.filter(fecha__gte=fecha_inicio)
    if fecha_fin:
        queryset = queryset.filter(fecha__lte=fecha_fin)
    if sucursal:
        queryset = queryset.filter(sucursal__iexact=sucursal)
    if clasificacion:
        queryset = queryset.filter(clasificacion_venta__iexact=clasificacion)

    try:
        # Realizar agregaciones en la base de datos
        summary = queryset.aggregate(
            total_ventas=Count('id'),
            total_costo=Sum('costo_equipo'),
            total_incentivos=Sum('incentivo')
        )
        
        # Agrupar por clasificación para un gráfico
        ventas_por_clasificacion = list(
            queryset.values('clasificacion_venta')
                    .annotate(cantidad=Count('id'))
                    .order_by('-cantidad')
        )

        # Agrupar por sucursal para otro gráfico
        ventas_por_sucursal = list(
            queryset.values('sucursal')
                    .annotate(cantidad=Count('id'))
                    .order_by('-cantidad')[:10] # Top 10 sucursales
        )
        
        # Obtener listas de filtros para los dropdowns del frontend
        opciones_filtros = {
            'sucursales': sorted(list(ReporteDetalleVenta.objects.values_list('sucursal', flat=True).distinct())),
            'clasificaciones': sorted(list(ReporteDetalleVenta.objects.values_list('clasificacion_venta', flat=True).distinct()))
        }

        data = {
            'summary': summary,
            'ventas_por_clasificacion': ventas_por_clasificacion,
            'ventas_por_sucursal': ventas_por_sucursal,
            'opciones_filtros': opciones_filtros
        }

        return Response(data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({'detail': f'Error al consultar los datos: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# En tu archivo views.py
@api_view(['GET', 'POST'])
def lista_productos_prepago(request):
    if request.method == 'GET':
        # La parte GET no necesita cambios, se mantiene como está
        try:
            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                return Response({'detail': 'Token no proporcionado.'}, status=401)
            token = auth_header.split(' ')[1]
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            usuario = User.objects.get(username=payload.get('id'))
            permisos_por_usuario = {
                '33333': ['Precio publico', 'Precio Fintech', 'Precio Addi'],
                '44444': ['Precio sub', 'Precio publico', 'Precio Fintech', 'Precio premium', 'Precio Addi'],
                '11111': ['Precio sub', 'Precio publico', 'Precio Fintech', 'Precio Addi'],
                '22222': ['Precio sub', 'Precio publico', 'Precio Fintech', 'Precio Addi', 'Precio Adelantos Valle']
            }
            todas_las_listas = [
                {"id": "Precio publico", "nombre": "Precio Público"}, {"id": "Precio sub", "nombre": "Subdistribuidor"},
                {"id": "Precio premium", "nombre": "Premium"}, {"id": "Precio Fintech", "nombre": "Fintech"},
                {"id": "Precio Addi", "nombre": "Addi"}, {"id": "Precio Flamingo", "nombre": "Flamingo"},
                {"id": "Costo", "nombre": "Costo"}, {"id": "Precio Adelantos Valle", "nombre": "Adelantos Valle"},
                {"id": "Descuento Kit", "nombre": "Descuento Kit"}
            ]
            if usuario.username in permisos_por_usuario:
                listas_permitidas = permisos_por_usuario[usuario.username]
                lista_precios_final = [lista for lista in todas_las_listas if lista['id'] in listas_permitidas]
            else:
                lista_precios_final = todas_las_listas
            return Response({'data': lista_precios_final})
        except Exception as e:
            return Response({'detail': f'Error en GET: {str(e)}'}, status=500)

    elif request.method == 'POST':
        try:
            precio_nombre = request.data.get('precio')
            if not precio_nombre:
                return Response({'error': 'El campo "precio" es obligatorio'}, status=400)

            todos_los_precios = models.Lista_precio.objects.filter(nombre=precio_nombre).order_by('producto', '-dia')
            df = pd.DataFrame(list(todos_los_precios.values()))

            if df.empty:
                return Response({'data': [], 'fecha_actual': 'N/A'})

            df['valor_anterior'] = df.groupby('producto')['valor'].shift(-1)
            df.fillna({'valor_anterior': 0}, inplace=True)
            
            df_final = df.drop_duplicates('producto', keep='first').copy()
            df_final.rename(columns={'valor': 'valor_actual'}, inplace=True)

            df_descuentos = pd.DataFrame(list(models.Lista_precio.objects.filter(nombre='descuento').order_by('producto', '-dia').values()))
            if not df_descuentos.empty:
                df_descuentos = df_descuentos.drop_duplicates('producto', keep='first')[['producto', 'valor']].rename(columns={'valor': 'descuento'})
                df_final = pd.merge(df_final, df_descuentos, on='producto', how='left')
            df_final.fillna({'descuento': 0}, inplace=True)
            
            df_final['variation'] = df_final.apply(calcular_variacion, axis=1)

            sim = Decimal('2000')
            base = Decimal('1095578')
            new_data = []

            for _, row in df_final.iterrows():
                variacion_data = row.get('variation')
                valor_actual = Decimal(row.get('valor_actual', 0))
                iva = valor_actual * Decimal('0.19') if valor_actual >= base else Decimal('0')
                
                tem_data = {
                    'equipo': row.get('producto'),
                    'precio simcard': float(sim),
                    'IVA simcard': float(sim * Decimal('0.19')),
                    'equipo sin IVA': float(valor_actual),
                    'IVA equipo': float(iva),
                    'total': float(sim * Decimal('1.19') + valor_actual + iva),
                    'valor_anterior': float(row.get('valor_anterior', 0)),
                    'indicador': variacion_data.get('indicador'),
                    'diferencial': variacion_data.get('diferencial'),
                    'porcentaje': variacion_data.get('porcentaje'),
                }
                if precio_nombre == 'Precio publico' and row.get('descuento', 0) > 0:
                    tem_data['Promo'] = 'PROMO'
                
                new_data.append(tem_data)
            
            fecha_carga = df_final['dia'].max()
            fecha_formateada = fecha_carga.strftime('%d de %B de %Y') if fecha_carga else "N/A"
            
            return Response({'data': new_data, 'fecha_actual': fecha_formateada})

        except Exception as e:
            traceback.print_exc()
            return Response({'error': f'Error interno: {str(e)}'}, status=500)
        
class UpdatePrices:

    def __init__(
        self, 
        producto,
        precioConIva,
        descuentoClaroPagoContado,
        valorSinIvaConDescuento,
        valorPagarDescuentoContado,
        descuentoAlDistribuidor,
        precioVtaDistribuidorSinIva,
        precioVtaDistribuidorConIva,
        iva
        ):
        

        self.producto = producto
        self.precioConIva = precioConIva
        self.descuentoClaroPagoContado = descuentoClaroPagoContado
        self.valorSinIvaConDescuento = valorSinIvaConDescuento
        self.valorPagarDescuentoContado = valorPagarDescuentoContado
        self.descuentoAlDistribuidor = descuentoAlDistribuidor
        self.precioVtaDistribuidorSinIva = precioVtaDistribuidorSinIva
        self.precioVtaDistribuidorConIva = precioVtaDistribuidorConIva
        self.iva = iva
        self.costoActual = '999999999.00'
        self.precioPubicoSinIva = '999999999.00'
        self.subdistribuidorSinIva = '999999999.00'
        self.freeMobileStore = '999999999.00'
        self.cliente0A5MesesSinIva = '999999999.00'
        self.cliente6A23MesesSinIva = '999999999.00'
        self.clienteMayorA24MesesSinIva = '999999999.00'
        self.clienteDescuentoKitPrepagoSinIva = '999999999.00'
        self.distritadosSinIva = '999999999.00'
        self.premiumSinIva = '999999999.00'
        self.tramitarSinIva = '999999999.00'
        self.peopleSinIva = '999999999.00'
        self.cooservunalSinIva = '999999999.00'
        self.fintechOficinasTeamSinIva = '999999999.00'
        self.fintechZonificacionSinIva = '999999999.00'
        self.oficinaMovilSinIva = '999999999.00'
        self.elianaRodas = '999999999.00'
        self.newcostoActual()
        self.newprecioPubicoSinIva()
        self.newsubdistribuidorSinIva()
        self.newfreeMobileStore()
        self.newcliente0A5MesesSinIva()
        self.newcliente6A23MesesSinIva()
        self.newclienteMayorA24MesesSinIva()
        self.newclienteDescuentoKitPrepagoSinIva()
        self.newdistritadosSinIva()
        self.newpremiumSinIva()
        self.newtramitarSinIva()
        self.newpeopleSinIva()
        self.newcooservunalSinIva()
        self.newfintechOficinasTeamSinIva()
        self.newfintechZonificacionSinIva()
        self.newoficinaMovilSinIva()
        self.newelianaRodas()

    def newcostoActual(self):
        self.costoActual = self.precioVtaDistribuidorSinIva - 2000

    def newprecioPubicoSinIva(self):
        if self.descuentoClaroPagoContado >0:
            descuento = 2000
        else:
            descuento = 0
        self.precioPubicoConIva= self.valorPagarDescuentoContado + descuento
        if self.iva == '1':
            self.precioPubicoSinIva = (self.precioPubicoConIva - 2380) / 1.19
        else:
            self.precioPubicoSinIva = (self.precioPubicoConIva - 2380)

    def newsubdistribuidorSinIva(self):
        precioSimEquipoSinIva = self.precioPubicoSinIva + 2000
        psqsi = precioSimEquipoSinIva
        self.psqsi = psqsi
        # Sub Descuento

        if psqsi > 702000:
            subDescuento = 38127
        elif psqsi > 520000:
            subDescuento = 35360
        elif psqsi > 442000:
            subDescuento = 31200
        elif psqsi > 299000:
            subDescuento = 27727
        elif psqsi > 130000:
            subDescuento = 24274
        elif psqsi > 104000:
            subDescuento = 17327
        elif psqsi > 91000:
            subDescuento = 13874
        elif psqsi > 78000:
            subDescuento = 10400
        elif psqsi > 51948:
            subDescuento = 7280
        elif psqsi > 18200:
            subDescuento = 4160
        else:
            subDescuento = 0

        # Descuento Adicional Sub
        if psqsi > 2500000:
            descuentoAdicionalSub = 25410
        elif psqsi > 1500000:
            descuentoAdicionalSub = 20510
        elif psqsi > 702001:
            descuentoAdicionalSub = 28210
        elif psqsi > 522001:
            descuentoAdicionalSub = 14560
        elif psqsi > 442001:
            descuentoAdicionalSub = 12600
        elif psqsi > 299001:
            descuentoAdicionalSub = 10780
        elif psqsi > 130001:
            descuentoAdicionalSub = 1890
        else:
            descuentoAdicionalSub = 0
        
        self.descuentoAdicionalsub = descuentoAdicionalSub
        
        if self.iva == '1':
            totalDecuentos = subDescuento + (descuentoAdicionalSub/1.19)
            subPrecioSinIva = psqsi - totalDecuentos +500
            subPrecioConIva = subPrecioSinIva * 1.19
            self.subdistribuidorSinIva = (subPrecioConIva-2380) / 1.19
        else:
            totalDecuentos = subDescuento + descuentoAdicionalSub
            subPrecioSinIva = psqsi - totalDecuentos +500
            subPrecioConIva = subPrecioSinIva + 380
            self.subdistribuidorSinIva = (subPrecioConIva - 2380)
        

    def newfreeMobileStore(self):
        # Ya no se utiliza, alianza vieja
        pass

    def newcliente0A5MesesSinIva(self):
        # Para postpago
        pass

    def newcliente6A23MesesSinIva(self):
        # Para postpago
        pass

    def newclienteMayorA24MesesSinIva(self):
        # Para postpago
        pass

    def newclienteDescuentoKitPrepagoSinIva(self):
        if self.descuentoClaroPagoContado > 0:
            if self.iva == '1':
                self.clienteDescuentoKitPrepagoSinIva = (self.precioConIva / 1.19) + 1680
            else:
                self.clienteDescuentoKitPrepagoSinIva =self.precioConIva - 2380 +2000
        else:
            self.clienteDescuentoKitPrepagoSinIva = self.precioPubicoSinIva

    def newdistritadosSinIva(self):
        # Ya no se utiliza, alianza vieja
        pass

    def newpremiumSinIva(self):

        # Descuento Premium

        if self.psqsi > 702000:
            descuentoPremium = 40040
        elif self.psqsi > 522000:
            descuentoPremium = 37655
        elif self.psqsi > 442000:
            descuentoPremium = 34069
        elif self.psqsi > 299000:
            descuentoPremium = 31075
        elif self.psqsi > 130000:
            descuentoPremium = 28098
        elif self.psqsi > 104000:
            descuentoPremium = 21658
        elif self.psqsi > 91000:
            descuentoPremium = 17342
        elif self.psqsi > 78000:
            descuentoPremium = 13000
        elif self.psqsi > 51948:
            descuentoPremium = 9100
        elif self.psqsi > 18200:
            descuentoPremium = 5200
        else:
            descuentoPremium = 0
        
        if self.iva == '1':
            totalDescuento = descuentoPremium + (self.descuentoAdicionalsub/1.19)
            elianaPrecioSinIva = self.psqsi - totalDescuento
            elianaPrecioConIVa = elianaPrecioSinIva * 1.19
            self.premiumSinIva = (elianaPrecioConIVa - 2380) / 1.19

        else:
            totalDescuento = descuentoPremium + self.descuentoAdicionalsub
            elianaPrecioConIVa = self.precioPubicoSinIva + 2000 - totalDescuento +380
            self.premiumSinIva = elianaPrecioConIVa - 2380
        
    def newtramitarSinIva(self):
        if self.psqsi > 702000:
            descuentoTramitar = 38127
        elif self.psqsi > 522000:
            descuentoTramitar = 35360
        elif self.psqsi > 442000:
            descuentoTramitar = 31200
        elif self.psqsi > 299000:
            descuentoTramitar = 27727
        elif self.psqsi > 130000:
            descuentoTramitar = 24274
        elif self.psqsi > 104000:
            descuentoTramitar = 17327
        elif self.psqsi > 91000:
            descuentoTramitar = 13874
        elif self.psqsi > 78000:
            descuentoTramitar = 10400
        elif self.psqsi > 51948:
            descuentoTramitar = 7280
        elif self.psqsi > 18200:
            descuentoTramitar = 4160
        else:
            descuentoTramitar = 0
        
        

        if self.iva == '1':
            tramitarSinIva = self.psqsi - descuentoTramitar
            tramitarConIVa = tramitarSinIva * 1.19
            self.tramitarSinIva = (tramitarConIVa - 2380) / 1.19 + 4201.68
        else:
            tramitarConIVa = self.psqsi - descuentoTramitar +380
            self.tramitarSinIva = (tramitarConIVa - 2380) + 5000

    def newpeopleSinIva(self):
        if self.iva == '1':
            peopleConIVa = self.precioPubicoConIva * 1.05
            self.peopleSinIva = (peopleConIVa - 2380) / 1.19

        else:
            peopleConIVa = self.precioPubicoSinIva * 1.05
            # 933064 es la base del iva, cualquier cambio en base mover aca
            baseIva = 933064

            if peopleConIVa > baseIva:
                self.peopleSinIva = baseIva
            else:
                self.peopleSinIva = peopleConIVa

    def newcooservunalSinIva(self):
        # Ya no se utiliza, alianza vieja
        pass

    def newfintechOficinasTeamSinIva(self):
        if self.iva == '1':
            self.fintechOficinasTeamSinIva = (self.precioPubicoConIva + 60000 - 2380) / 1.19
            self.fintechOficinasTeamConIva = (self.fintechOficinasTeamSinIva * 1.19) + 2380 + 20000
        else:
            # 933064 es la base del iva, cualquier cambio en base mover aca
            baseIva = 933064
            self.fintechOficinasTeamSinIva = (self.precioPubicoConIva + 60000 - 2380)
            self.fintechOficinasTeamConIva = (self.fintechOficinasTeamSinIva) + 2380 + 20000
            if self.fintechOficinasTeamSinIva > baseIva:
                self.fintechOficinasTeamSinIva = baseIva

    def newfintechZonificacionSinIva(self):
        if self.iva == '1':
            self.fintechZonificacionSinIva = (self.precioPubicoConIva + 80000 - 2380) / 1.19
        else:
            # 933064 es la base del iva, cualquier cambio en base mover aca
            baseIva = 933064 
            self.fintechZonificacionSinIva = (self.precioPubicoConIva + 80000 - 2380)
            if self.fintechZonificacionSinIva > baseIva:
                self.fintechZonificacionSinIva = baseIva

    def newoficinaMovilSinIva(self):
        if self.descuentoClaroPagoContado > 0:
            self.oficinaMovilSinIva = self.precioPubicoSinIva
        else:
            self.oficinaMovilSinIva = self.subdistribuidorSinIva

    def newelianaRodas(self):
        # Ya no se utiliza, alianza vieja
        pass

    def formatoData(self):
        if (type(self.producto)) == float : self.producto  = round(self.producto ,2)
        if (type(self.costoActual)) == float : self.costoActual  = round(self.costoActual ,2)
        if (type(self.precioPubicoSinIva)) == float : self.precioPubicoSinIva  = round(self.precioPubicoSinIva ,2)
        if (type(self.subdistribuidorSinIva)) == float : self.subdistribuidorSinIva  = round(self.subdistribuidorSinIva ,2)
        if (type(self.freeMobileStore)) == float : self.freeMobileStore  = round(self.freeMobileStore ,2)
        if (type(self.cliente0A5MesesSinIva)) == float : self.cliente0A5MesesSinIva  = round(self.cliente0A5MesesSinIva ,2)
        if (type(self.cliente6A23MesesSinIva)) == float : self.cliente6A23MesesSinIva  = round(self.cliente6A23MesesSinIva ,2)
        if (type(self.clienteMayorA24MesesSinIva)) == float : self.clienteMayorA24MesesSinIva  = round(self.clienteMayorA24MesesSinIva ,2)
        if (type(self.clienteDescuentoKitPrepagoSinIva)) == float : self.clienteDescuentoKitPrepagoSinIva  = round(self.clienteDescuentoKitPrepagoSinIva ,2)
        if (type(self.distritadosSinIva)) == float : self.distritadosSinIva  = round(self.distritadosSinIva ,2)
        if (type(self.premiumSinIva)) == float : self.premiumSinIva  = round(self.premiumSinIva ,2)
        if (type(self.tramitarSinIva)) == float : self.tramitarSinIva = round(self.tramitarSinIva,2)
        if (type(self.peopleSinIva)) == float : self.peopleSinIva  = round(self.peopleSinIva ,2)
        if (type(self.cooservunalSinIva)) == float : self.cooservunalSinIva  = round(self.cooservunalSinIva ,2)
        if (type(self.fintechOficinasTeamSinIva)) == float : self.fintechOficinasTeamSinIva  = round(self.fintechOficinasTeamSinIva ,2)
        if (type(self.fintechZonificacionSinIva)) == float : self.fintechZonificacionSinIva  = round(self.fintechZonificacionSinIva ,2)
        if (type(self.oficinaMovilSinIva)) == float : self.oficinaMovilSinIva  = round(self.oficinaMovilSinIva ,2)
        if (type(self.elianaRodas)) == float : self.elianaRodas  = round(self.elianaRodas ,2)
        if (type(self.fintechOficinasTeamConIva)) == float : self.fintechOficinasTeamConIva  = round(self.fintechOficinasTeamConIva ,0)
    
    def returnData(self):
        self.formatoData()
        return [
           [ 
                str(self.producto),
                str(self.costoActual),
                str(self.precioPubicoSinIva),
                str(self.subdistribuidorSinIva),
                str(self.freeMobileStore),
                str(self.cliente0A5MesesSinIva),
                str(self.cliente6A23MesesSinIva),
                str(self.clienteMayorA24MesesSinIva),
                str(self.clienteDescuentoKitPrepagoSinIva),
                str(self.distritadosSinIva),
                str(self.premiumSinIva),
                str(self.tramitarSinIva),
                str(self.peopleSinIva),
                str(self.cooservunalSinIva),
                str(self.fintechOficinasTeamSinIva),
                str(self.fintechZonificacionSinIva),
                str(self.oficinaMovilSinIva),
                str(self.elianaRodas),
            ],
            self.fintechOficinasTeamConIva,
        ]

def formating_numbers(number, type_value=''):
    if type_value != 'Money':
        if number >= 1000000000:
            formated_number = str(round(number/1000000000, 2)) + 'B'
        elif number >= 1000000:
            formated_number = str(round(number/1000000, 2)) + 'M'
        elif number >= 1000:
            formated_number = str(round(number/1000, 2)) + 'K'
        else:
            formated_number = str(round(number, 2))
    else:
        formated_number = str(f'{number:,.2f}')
    return formated_number

# def restablecerContraseña(id):
#     usuario = User.objects.get(username=id)
#     usuario.set_password('Cambiame123')
#     usuario.save()


def generate_unique_filename(filename):
            # Obtener la extensión del archivo
            file_extension = filename.split('.')[-1]
            # Obtener la fecha y hora actual
            current_time = datetime.now().strftime('%Y%m%d%H%M%S')
            # Generar una cadena aleatoria de 6 caracteres
            random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
            # Combinar para crear un nombre único
            unique_filename = f"{current_time}_{random_string}.{file_extension}"
            return unique_filename
        
@api_view(['GET'])
def obtener_imagen_login(request):
    try:
        imagen = ImagenLogin.objects.latest('fecha')
        serializer = ImagenLoginSerializer(imagen)
        return Response(serializer.data)
    except ImagenLogin.DoesNotExist:
        return Response({'url': '/img-example.jpg'}, status=200)

@api_view(['POST'])
def actualizar_imagen_login(request):
    url = request.data.get('url')
    if not url:
        return Response({'error': 'URL requerida'}, status=400)
    
    # Puedes eliminar las anteriores si solo quieres una
    ImagenLogin.objects.all().delete()
    
    imagen = ImagenLogin.objects.create(url=url)
    return Response({'mensaje': 'Imagen actualizada'})  