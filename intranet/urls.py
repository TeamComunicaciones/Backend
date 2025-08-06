from django.urls import path, include
from rest_framework import routers
from . import viewsets
from . import views
from .views import actas_entrega

router = routers.SimpleRouter()



urlpatterns = [
    path('', include(router.urls)),
    path('shopify-return', views.shopify_return),
    path('shopify', views.shopify_token),
    path('login', views.login),
    path('user-validate', views.user_validate),
    path('user-permissions', views.user_permissions),
    path('permissions-matrix', views.permissions_matrix),
    path('permissions-edit', views.permissions_edit),
    path('create-user', views.login),
    path('translate-products-prepago', views.translate_products_prepago),
    path('translate-prepago', views.translate_prepago),
    path('lista-productos-prepago', views.lista_productos_prepago),
    path('lista-productos-prepago-equipo/', views.ListaProductosPrepagoEquipo.as_view(), name='lista_productos_prepago_equipo'),
    path('planes', views.planes),
    path('productos', views.productos),
    path('tienda', views.tienda),
    path('guardarImagen', views.cargarImagen),
    path('deleteImagen', views.deleteImagen),
    path('informes', views.informes),
    path('contactanos', views.contactanos),
    path('prueba-formula', views.prueba_formula),
    path('guardar-formula', views.guardar_formula),
    path('consultar-formula', views.consultar_formula),
    path('guardar-precios', views.guardar_precios),
    path('excel-precios', views.excel_precios),
    path('cambio-clave', views.cambio_clave),
    path('porcentajes-comisiones', views.porcentajes_comisiones),
    path('calcular-comisiones', views.calcular_comisiones),
    path('guardar-datos-corresponsal', views.guardar_datos_corresponsal),
    path('select-datos-corresponsal', views.select_datos_corresponsal),
    path('select-datos-corresponsal-cajero', views.select_datos_corresponsal_cajero),
    path('select-consignaciones-corresponsal-cajero', views.select_consignaciones_corresponsal_cajero),
    path('resumen-corresponsal', views.resumen_corresponsal),
    path('encargados-corresponsal', views.encargados_corresponsal),
    path('lista-usuarios', views.lista_usuarios),
    path('consignacion-corresponsal', views.consignacion_corresponsal),
    path('get-imagen-corresponsal', views.get_image_corresponsal),
    path('assign-responsible', views.assign_responsible),
    path('settle-invoice', views.settle_invoice),
    path('black-list', views.black_list),
    path('black-list/<int:id>/', views.black_list),
    path('prices', views.prices),
    path('prices/<int:id>/', views.prices),
    path('variables', views.variables_prices),
    path('variables/<int:id>/', views.variables_prices),
    path('formulas', views.formulas_prices),
    path('formulas/<int:id>/', views.formulas_prices),
    path('actas/', actas_entrega, name='actas_entrega'),  # Para GET y POST
    path('actas/<int:id>/', actas_entrega, name='actas_entrega_id'),  # Para GET, PUT, DELETE con id
    path('api/imagen-login/', views.obtener_imagen_login),
    path('api/imagen-login/actualizar/', views.actualizar_imagen_login),
    path('historico-pendientes-cajero/', views.historico_pendientes_cajero, name='historico_pendientes_cajero'),
    path('get_filtros_precios/', views.get_filtros_precios, name='get_filtros_precios'),
    path('buscar-precios/', views.buscar_precios, name='buscar_precios'),   
    path('get_reportes_por_fecha/', views.get_reportes_por_fecha, name='get-reportes-por-fecha'),
    path('translate-products-prepago/admin', views.delete_translate_product_admin),





]