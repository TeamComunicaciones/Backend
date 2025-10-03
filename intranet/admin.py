from django.contrib import admin
from . import models

# Registros que ya tenías
admin.site.register(models.Permisos_precio)
admin.site.register(models.Permisos_usuarios_precio)
admin.site.register(models.Porcentaje_comision)
admin.site.register(models.Permisos)
admin.site.register(models.Codigo_oficina)

# --- Definición mejorada para Permisos_usuarios ---

# 1. Creamos una clase de configuración para el modelo
class PermisosUsuariosAdmin(admin.ModelAdmin):
    list_display = ('user', 'permiso', 'tiene_permiso')
    list_filter = ('tiene_permiso', 'permiso__permiso', 'user__username')
    search_fields = ('user__username', 'user__email', 'permiso__permiso')
    list_per_page = 50

# 2. Registramos el modelo usando la clase de configuración que acabamos de crear
admin.site.register(models.Permisos_usuarios, PermisosUsuariosAdmin)