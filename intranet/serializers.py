from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.utils import timezone
from django.db import transaction
from django.contrib.auth.models import User

from .models import (
    ActaEntrega,
    ActaObjetivos,
    ActaObservaciones,
    ActaRecibidoPor,
    ActaArchivos,
    Proyecto,
    ImagenLogin,
    Permisos_usuarios,
    Comision,
    PagoComision,
    Perfil,
    Permisos,
    RutaAsignada,
)

# ----------------- ROLES (COMISIONES) -----------------

ROL_ASESOR = 'asesor_comisiones'
ROL_SUPERVISOR = 'supervisor_comisiones'


# ----------------- PAGO COMISION (ADMIN) -----------------

class PagoComisionAdminSerializer(serializers.ModelSerializer):
    """
    Serializador para la vista de admin que maneja las
    inconsistencias entre el frontend y el backend.
    """
    asesor_username = serializers.CharField(source='creado_por.username', read_only=True)
    monto = serializers.DecimalField(
        source='monto_total_pagado',
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    metodo_pago = serializers.SerializerMethodField()
    comision = serializers.SerializerMethodField()

    # Convierte DateTime a Date (zona horaria local)
    fecha_pago = serializers.SerializerMethodField()

    observacion = serializers.CharField(required=False, allow_blank=True)
    idpos = serializers.CharField(read_only=True)

    class Meta:
        model = PagoComision
        fields = [
            'id',
            'idpos',
            'asesor_username',
            'comision',
            'monto',
            'fecha_pago',
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

    def get_fecha_pago(self, obj):
        if obj.fecha_pago:
            return timezone.localtime(obj.fecha_pago).date()
        return None


# ----------------- PROYECTOS / ACTAS / LOGIN -----------------

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


# ----------------- AUTH / USUARIOS -----------------

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


# ----------------- COMISION (GENERAL) -----------------

class ComisionSerializer(serializers.ModelSerializer):
    asesor_username = serializers.CharField(source='asesor.username', read_only=True)

    class Meta:
        model = Comision
        fields = '__all__'


# ----------------- COMISIONES PENDIENTES (ADMIN) -----------------

class ComisionPendienteAdminSerializer(serializers.ModelSerializer):
    """
    Serializer para la pestaña 'Comisiones Pendientes' del panel admin.
    Coincide con lo que espera el front:
      - id
      - idpos
      - asesor_username
      - ruta
      - mes_pago
      - fecha_referencia (fallback)
      - valor_comision (comision_final)
      - estado
      - observacion
    """
    asesor_username = serializers.CharField(source='asesor.username', read_only=True)

    valor_comision = serializers.DecimalField(
        source='comision_final',
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True
    )

    fecha_referencia = serializers.SerializerMethodField()

    class Meta:
        model = Comision
        fields = [
            'id',
            'idpos',
            'asesor_username',
            'ruta',
            'mes_pago',
            'fecha_referencia',
            'valor_comision',
            'estado',
            'observacion',
        ]

    def get_fecha_referencia(self, obj):
        """
        Campo de respaldo para cuando mes_pago está vacío.
        Usamos mes_liquidacion y, si no, la prim_llamada_activacion.
        """
        return obj.mes_liquidacion or obj.prim_llamada_activacion


# ----------------- ASESORES (ADMIN COMISIONES) -----------------

class AsesorSerializer(serializers.ModelSerializer):
    """
    Serializador para gestionar usuarios Asesores / Supervisores de comisiones.
    Expuesto al front:
      - id, username, email, is_active
      - rol: 'asesor_comisiones' | 'supervisor_comisiones'
      - rutas_asignadas: ['RUTA 1', 'RUTA 2', ...]
    """

    rol = serializers.CharField()
    rutas_asignadas = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
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
            'rol',
            'rutas_asignadas',
            'password',
        )
        read_only_fields = ('id', 'is_active')

    # ---------- REPRESENTACIÓN (GET) ----------
    def to_representation(self, instance):
        data = {
            'id': instance.id,
            'username': instance.username,
            'email': instance.email,
            'is_active': instance.is_active,
        }

        # Rol:
        rol_actual = self._get_rol_actual(instance)
        data['rol'] = rol_actual

        # Rutas:
        rutas = list(instance.rutas_comisiones.values_list('ruta', flat=True))

        # Si no hay rutas en RutaAsignada, usamos la del Perfil (dato “viejo”)
        if not rutas:
            try:
                perfil = instance.perfil
                if perfil.ruta_asignada:
                    rutas = [perfil.ruta_asignada]
            except Perfil.DoesNotExist:
                pass

        data['rutas_asignadas'] = rutas
        return data

    # ---------- VALIDACIÓN ----------
    def validate(self, attrs):
        """
        Regla:
        - Si el rol final es asesor_comisiones:
            - Solo puede tener 1 ruta
            - Cada ruta solo puede tener 1 asesor activo.
        """

        instance = self.instance
        rol_en_payload = attrs.get('rol')
        rol_actual = self._get_rol_actual(instance) if instance else None
        rol_final = rol_en_payload if rol_en_payload is not None else (rol_actual or ROL_ASESOR)

        rutas_en_payload = attrs.get('rutas_asignadas', None)

        if rutas_en_payload is not None:
            rutas_finales = rutas_en_payload
        else:
            if instance:
                rutas_finales = list(instance.rutas_comisiones.values_list('ruta', flat=True))
                if not rutas_finales:
                    try:
                        perfil = instance.perfil
                        if perfil.ruta_asignada:
                            rutas_finales = [perfil.ruta_asignada]
                        else:
                            rutas_finales = []
                    except Perfil.DoesNotExist:
                        rutas_finales = []
            else:
                rutas_finales = []

        if rol_final not in [ROL_ASESOR, ROL_SUPERVISOR]:
            raise serializers.ValidationError({
                'rol': 'Rol inválido. Debe ser asesor_comisiones o supervisor_comisiones.'
            })

        if rol_final == ROL_ASESOR and rutas_finales and len(rutas_finales) > 1:
            raise serializers.ValidationError({
                'rutas_asignadas': 'Un asesor solo puede tener una ruta asignada.'
            })

        if rol_final == ROL_ASESOR and rutas_finales:
            MAX_ASESORES_POR_RUTA = 1

            for ruta in rutas_finales:
                qs = RutaAsignada.objects.filter(
                    ruta=ruta,
                    user__is_active=True,  # solo contamos usuarios activos
                    user__permisos_usuarios__permiso__permiso=ROL_ASESOR,
                    user__permisos_usuarios__tiene_permiso=True,
                    user__permisos_usuarios__permiso__active=True,
                ).distinct()

                if instance:
                    qs = qs.exclude(user=instance)

                count = qs.count()

                if count >= MAX_ASESORES_POR_RUTA:
                    raise serializers.ValidationError({
                        'rutas_asignadas': [
                            f'La ruta "{ruta}" ya tiene un asesor asignado.'
                        ]
                    })

        attrs['rol'] = rol_final
        attrs['rutas_asignadas'] = rutas_finales

        return attrs

    # ---------- CREATE (POST) ----------
    @transaction.atomic
    def create(self, validated_data):
        rol = validated_data.pop('rol', ROL_ASESOR)
        rutas = validated_data.pop('rutas_asignadas', [])
        password = validated_data.pop('password', None)

        if not password:
            raise serializers.ValidationError("La contraseña es obligatoria para crear un usuario.")

        user = User(
            username=validated_data['username'],
            email=validated_data.get('email', '')
        )
        user.is_active = True
        user.set_password(password)
        user.save()

        perfil, _ = Perfil.objects.get_or_create(user=user)
        if rol == ROL_ASESOR and rutas:
            perfil.ruta_asignada = rutas[0]
        else:
            perfil.ruta_asignada = None
        perfil.save()

        RutaAsignada.objects.filter(user=user).delete()
        for ruta in rutas:
            RutaAsignada.objects.get_or_create(user=user, ruta=ruta)

        self._set_rol_permisos(user, rol)

        return user

    # ---------- UPDATE (PUT) ----------
    @transaction.atomic
    def update(self, instance, validated_data):
        rol = validated_data.pop('rol', None)
        rutas = validated_data.pop('rutas_asignadas', None)
        password = validated_data.pop('password', None)

        instance.username = validated_data.get('username', instance.username)
        instance.email = validated_data.get('email', instance.email)

        if password:
            instance.set_password(password)

        instance.save()

        if rutas is not None:
            RutaAsignada.objects.filter(user=instance).delete()
            for ruta in rutas:
                RutaAsignada.objects.get_or_create(user=instance, ruta=ruta)

            perfil, _ = Perfil.objects.get_or_create(user=instance)
            rol_final = rol or self._get_rol_actual(instance)
            if rol_final == ROL_ASESOR and rutas:
                perfil.ruta_asignada = rutas[0]
            elif rol_final == ROL_ASESOR:
                perfil.ruta_asignada = None
            perfil.save()

        if rol is not None:
            self._set_rol_permisos(instance, rol)

        return instance

    # ---------- HELPERS ----------
    def _get_rol_actual(self, user):
        if not user:
            return None

        permisos_qs = Permisos_usuarios.objects.filter(
            user=user,
            tiene_permiso=True,
            permiso__active=True,
            permiso__permiso__in=[ROL_ASESOR, ROL_SUPERVISOR]
        )
        if permisos_qs.filter(permiso__permiso=ROL_ASESOR).exists():
            return ROL_ASESOR
        if permisos_qs.filter(permiso__permiso=ROL_SUPERVISOR).exists():
            return ROL_SUPERVISOR
        return None

    def _set_rol_permisos(self, user, rol):
        """
        Asigna el permiso asesor_comisiones o supervisor_comisiones
        y desactiva el otro.
        """
        try:
            permiso_obj = Permisos.objects.get(permiso=rol, active=True)
        except Permisos.DoesNotExist:
            raise serializers.ValidationError(
                f"El permiso '{rol}' no existe o está inactivo en la tabla Permisos."
            )

        Permisos_usuarios.objects.update_or_create(
            user=user,
            permiso=permiso_obj,
            defaults={'tiene_permiso': True}
        )

        otro_rol = ROL_SUPERVISOR if rol == ROL_ASESOR else ROL_ASESOR
        Permisos_usuarios.objects.filter(
            user=user,
            permiso__permiso=otro_rol
        ).update(tiene_permiso=False)
