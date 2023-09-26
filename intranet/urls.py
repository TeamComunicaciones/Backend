from django.urls import path, include
from rest_framework import routers
from . import viewsets
from . import views

router = routers.SimpleRouter()



urlpatterns = [
    path('', include(router.urls)),
    path('login', views.login),
    path('user-validate', views.user_validate),
    path('create-user', views.login),
    path('translate-products-prepago', views.translate_products_prepago),
    path('translate-prepago', views.translate_prepago),
]