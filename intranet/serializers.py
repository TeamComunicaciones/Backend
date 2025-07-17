from rest_framework import serializers
from .models import ActaEntrega, ActaObjetivos, ActaObservaciones, ActaRecibidoPor, ActaArchivos, Proyecto, ImagenLogin

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