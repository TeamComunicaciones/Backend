from rest_framework import serializers
from .models import (
    ActaEntrega, ActaObjetivos, ActaObservaciones, ActaRecibidoPor, ActaArchivos, 
    Proyecto, ImagenLogin, Permisos_usuarios, Comision
)

from .models import PagoComision
from django.utils import timezone

from django.contrib.auth.models import User
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework import serializers
from django.db import transaction
# Importamos los modelos correctos de tu archivo
from django.contrib.auth.models import User
from .models import Perfil, Permisos, Permisos_usuarios

class PagoComisionAdminSerializer(serializers.ModelSerializer):
    """
    Serializador para la vista de admin que maneja las
    inconsistencias entre el frontend y el backend.
    """
    asesor_username = serializers.CharField(source='creado_por.username', read_only=True)
    monto = serializers.DecimalField(source='monto_total_pagado', max_digits=12, decimal_places=2, read_only=True)
    metodo_pago = serializers.SerializerMethodField()
    comision = serializers.SerializerMethodField()
    
    # --- LA CORRECCIÓN DEFINITIVA ---
    # Usamos un SerializerMethodField para convertir explícitamente
    # el DateTime a un Date en la zona horaria local.
    fecha_pago = serializers.SerializerMethodField()
    
    observacion = serializers.CharField(required=False, allow_blank=True)

    # El campo 'idpos' ya existe en el modelo, así que solo lo añadimos a 'fields'
    idpos = serializers.CharField(read_only=True)

    class Meta:
        model = PagoComision
        fields = [
            'id',
            'idpos', # <-- ¡AÑADIDO!
            'asesor_username',
            'comision',
            'monto',
            'fecha_pago',       # <- Ahora usa el método
            'metodo_pago',
            'observacion',
        ]

    def get_metodo_pago(self, obj):
        if obj.metodos_pago and isinstance(obj.metodos_pago, dict):
            return next(iter(obj.metodos_pago.keys()), None)
        return None

    def get_comision(self, obj):
        first_comision = obj.comisiones_pagadas.first()
        if first_comision:
            return first_comision.id
        return None

    # --- MÉTODO AÑADIDO PARA LA CORRECCIÓN ---
    def get_fecha_pago(self, obj):
        """
        Convierte el DateTime (posiblemente en UTC) a un objeto Date
        en la zona horaria local del servidor.
        """
        if obj.fecha_pago:
            # timezone.localtime() lo convierte a la zona horaria
            # de tu settings.py y .date() extrae solo la fecha.
            return timezone.localtime(obj.fecha_pago).date()
        return None

class ProyectoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proyecto
        fields = '__all__'

class ActaEntregaSerializer(serializers.ModelSerializer):
    proyecto_nombre = serializers.CharField(source='proyecto.nombre', read_only=True)
    class Meta:
        model = ActaEntrega
        fields = '__all__'

class ActaObjetivosSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActaObjetivos
        fields = '__all__'

class ActaObservacionesSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActaObservaciones
        fields = '__all__'

class ActaRecibidoPorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActaRecibidoPor
        fields = '__all__'

class ActaArchivosSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActaArchivos
        fields = '__all__'
        
class ImagenLoginSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImagenLogin
        fields = ['id', 'url', 'fecha']

class UserDataSerializer(serializers.ModelSerializer):
    permisos = serializers.SerializerMethodField()
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'permisos')
    def get_permisos(self, user_obj):
        permisos_activos = Permisos_usuarios.objects.filter(user=user_obj, tiene_permiso=True)
        return [p.permiso.permiso for p in permisos_activos]

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    pass

class ComisionSerializer(serializers.ModelSerializer):
    asesor_username = serializers.CharField(source='asesor.username', read_only=True)
    class Meta:
        model = Comision
        fields = '__all__'

class AsesorSerializer(serializers.ModelSerializer):
    """
    Serializador para gestionar usuarios Asesores.
    Maneja el modelo User, el Perfil y los Permisos.
    """
    
    # Apuntamos al campo 'ruta_asignada' en el 'perfil'
    ruta_asignada = serializers.CharField(
        source='perfil.ruta_asignada', # CORREGIDO
        allow_null=True, 
        required=False
    )
    
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = (
            'id', 
            'username', 
            'email', 
            'is_active', 
            'ruta_asignada',  # Campo del perfil
            'password'        # Campo de solo escritura
        )
        read_only_fields = ('id', 'is_active')

    @transaction.atomic
    def create(self, validated_data):
        # 1. Obtenemos el permiso 'asesor_comisiones'
        try:
            permiso_asesor = Permisos.objects.get(permiso='asesor_comisiones')
        except Permisos.DoesNotExist:
            raise serializers.ValidationError("El permiso 'asesor_comisiones' no existe en la base de datos.")

        # 2. Sacamos los datos del perfil y la contraseña
        perfil_data = validated_data.pop('perfil', {}) # CORREGIDO
        ruta_data = perfil_data.get('ruta_asignada')  # CORREGIDO
        password = validated_data.pop('password', None)

        if not password:
             raise serializers.ValidationError("La contraseña es obligatoria para crear un usuario.")

        # 3. Creamos el User
        user = User.objects.create_user(**validated_data, password=password)

        # 4. Creamos el Perfil del usuario
        Perfil.objects.create(user=user, ruta_asignada=ruta_data) # CORREGIDO

        # 5. Asignamos el permiso de asesor
        Permisos_usuarios.objects.create(
            user=user, 
            permiso=permiso_asesor, 
            tiene_permiso=True
        )

        return user

    @transaction.atomic
    def update(self, instance, validated_data):
        # 1. Sacamos los datos del perfil
        perfil_data = validated_data.pop('perfil', None) # CORREGIDO

        # 2. Actualizamos los campos del User (username, email)
        instance.username = validated_data.get('username', instance.username)
        instance.email = validated_data.get('email', instance.email)
        instance.save()

        # 3. Actualizamos el Perfil (ruta)
        if perfil_data is not None:
            ruta_data = perfil_data.get('ruta_asignada') # CORREGIDO
            
            # Usamos get_or_create por si acaso el perfil no existe
            perfil_inst, created = Perfil.objects.get_or_create(user=instance) # CORREGIDO
            perfil_inst.ruta_asignada = ruta_data # CORREGIDO
            perfil_inst.save() # CORREGIDO

        return instance