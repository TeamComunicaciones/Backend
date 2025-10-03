from rest_framework import serializers
from .models import (
    ActaEntrega, ActaObjetivos, ActaObservaciones, ActaRecibidoPor, ActaArchivos, 
    Proyecto, ImagenLogin, Permisos_usuarios, Comision
)
from django.contrib.auth.models import User
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

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