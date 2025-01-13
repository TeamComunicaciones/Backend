from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User

class Traducciones(models.Model):
    equipo = models.CharField(max_length=255, unique=True)
    stok = models.CharField(max_length=255)
    iva = models.BooleanField()
    active = models.BooleanField()
    tipo = models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.equipo
    
class Permisos(models.Model):
    permiso = models.CharField(max_length=255, unique=True)
    active = models.BooleanField()

class Permisos_usuarios(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    permiso = models.ForeignKey(Permisos, on_delete=models.CASCADE)
    tiene_permiso = models.BooleanField()

    class Meta:
        unique_together = ('user', 'permiso')

class Imagenes(models.Model):
    url = models.CharField(max_length=255, unique=True, null=True)
    titulo = models.CharField(max_length=255, null=True)
    detalle = models.CharField(max_length=255, null=True)
    precio = models.CharField(max_length=255, null=True)
    carpeta = models.CharField(max_length=255, null=True)
    marca = models.CharField(max_length=255, null=True)

class Contactanos(models.Model):
    nombre = models.CharField(max_length=255, null=True)
    correo = models.CharField(max_length=255, null=True)
    asunto = models.CharField(max_length=255, null=True)
    mensaje = models.TextField(null=True)

class Formula(models.Model):
    nombre = models.CharField(max_length=255, unique=True)
    formula = models.TextField(null=True)
    fecha = models.DateTimeField(auto_now=True)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE) 

    def __str__(self):
        return self.nombre

class Lista_precio(models.Model):
    producto = models.CharField(max_length=100, null=True)  # Ajusta la longitud según tus necesidades
    nombre = models.CharField(max_length=100, null=True)    # Ajusta la longitud según tus necesidades
    valor = models.DecimalField(max_digits=10, decimal_places=2)  # Ajusta según tus necesidades
    dia = models.DateTimeField(auto_now_add=True, null=True)

class Permisos_precio(models.Model):
    permiso = models.CharField(max_length=255, unique=True)
    active = models.BooleanField()

class Variables_prices(models.Model):
    price = models.ForeignKey(Permisos_precio, on_delete=models.CASCADE)
    name = models.CharField(max_length=20)
    formula = models.TextField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['price', 'name'], name='unique_price_name')
        ]

class Permisos_usuarios_precio(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    permiso = models.ForeignKey(Permisos_precio, on_delete=models.CASCADE)
    tiene_permiso = models.BooleanField()

    class Meta:
        unique_together = ('user', 'permiso')


class Porcentaje_comision(models.Model):
    nombre = models.CharField(max_length=255, unique=True)
    valor = models.CharField(max_length=255)
    def __str__(self):
        return self.nombre

class Transacciones_sucursal(models.Model):
    establecimiento = models.CharField(max_length=100)
    codigo_aval = models.CharField(max_length=100)
    codigo_incocredito = models.CharField(max_length=100)
    terminal = models.CharField(max_length=100)
    fecha = models.DateTimeField()
    hora = models.CharField(max_length=100)
    nombre_convenio = models.CharField(max_length=100)
    operacion = models.CharField(max_length=100)
    fact_cta = models.CharField(max_length=100)
    cod_aut = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    nura = models.DecimalField(max_digits=10, decimal_places=2)
    esquema = models.CharField(max_length=100)
    numero_tarjeta = models.CharField(max_length=100)
    comision = models.DecimalField(max_digits=10, decimal_places=2)

class Codigo_oficina(models.Model):
    codigo = models.CharField(max_length=100, unique=True)
    terminal = models.CharField(max_length=100)
    def __str__(self):
        return f'{self.codigo}-{self.terminal}'

class Responsable_corresponsal(models.Model):
    sucursal = models.ForeignKey(Codigo_oficina, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

class Corresponsal_consignacion(models.Model):
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    banco = models.CharField(max_length=100)
    fecha_consignacion = models.DateField()
    fecha = models.DateTimeField()
    responsable = models.CharField(max_length=100)
    estado = models.CharField(max_length=20)
    detalle = models.TextField()
    url = models.URLField(blank=True, null=True)
    codigo_incocredito = models.CharField(max_length=100, null=True)
    detalle_banco = models.CharField(max_length=100, null=True)

class Lista_negra(models.Model):
    equipo = models.CharField(max_length=255, unique=True)
    def __str__(self) -> str:
        return self.equipo

