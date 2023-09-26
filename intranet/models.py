from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User

class Traducciones(models.Model):
    equipo = models.CharField(max_length=255, unique=True)
    stok = models.CharField(max_length=255)
    iva = models.BooleanField()
    active = models.BooleanField()
    tipo = models.CharField(max_length=255)