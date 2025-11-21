from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from django.utils import timezone

class Perfil(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    ruta_asignada = models.CharField(
        max_length=100, 
        blank=True,
        null=True,
        default=None,
        help_text="Ruta asignada al usuario si tiene el rol de asesor."
    )
    def __str__(self):
        return f'Perfil de {self.user.username}'

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

class Carga(models.Model):
    fecha_carga = models.DateTimeField(auto_now_add=True)
    descripcion = models.CharField(max_length=255, blank=True, null=True)
    def __str__(self):
        return f"Carga del {self.fecha_carga.strftime('%Y-%m-%d %H:%M:%S')}"

class Lista_precio(models.Model):
    carga = models.ForeignKey(Carga, on_delete=models.CASCADE, related_name='precios')
    producto = models.CharField(max_length=100, null=True)
    nombre = models.CharField(max_length=100, null=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)

class Permisos_precio(models.Model):
    permiso = models.CharField(max_length=255, unique=True)
    active = models.BooleanField()

class Formula(models.Model):
    price_id = models.ForeignKey(Permisos_precio, on_delete=models.CASCADE, null=True)
    nombre = models.CharField(max_length=255, unique=True)
    formula = models.TextField(null=True)
    fecha = models.DateTimeField(auto_now=True)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE) 
    def __str__(self):
        return self.nombre
    
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
    valor = models.DecimalField(max_digits=15, decimal_places=2)
    banco = models.CharField(max_length=100)
    fecha_consignacion = models.DateField()
    fecha = models.DateTimeField()
    responsable = models.CharField(max_length=100)
    estado = models.CharField(max_length=20)
    detalle = models.TextField()
    url = models.URLField(blank=True, null=True)
    codigo_incocredito = models.CharField(max_length=100, null=True)
    detalle_banco = models.TextField(null=True)
    min = models.CharField(max_length=20, blank=True, null=True)
    imei = models.CharField(max_length=30, blank=True, null=True)
    planilla = models.CharField(max_length=50, blank=True, null=True)

class Lista_negra(models.Model):
    equipo = models.CharField(max_length=255, unique=True)
    def __str__(self) -> str:
        return self.equipo
    
class ReporteDetalleVenta(models.Model):
    fecha = models.DateField()
    imei = models.CharField(max_length=50, unique=True)
    modelo_equipo = models.CharField(max_length=255)
    sucursal = models.CharField(max_length=100)
    tipo_producto = models.CharField(max_length=100, null=True, blank=True)
    tipo_venta_original = models.CharField(max_length=100)
    asesor = models.CharField(max_length=150, null=True, blank=True)
    canal = models.CharField(max_length=100, null=True, blank=True)
    tiket_venta = models.CharField(max_length=100, null=True, blank=True)
    costo_equipo = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    incentivo = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    clasificacion_venta = models.CharField(max_length=50)
    tipo_vendedor = models.CharField(max_length=50, null=True, blank=True)
    fecha_carga = models.DateTimeField(auto_now_add=True)
    class Meta:
        verbose_name = "Detalle de Venta para Reporte"
        verbose_name_plural = "Detalles de Venta para Reportes"
        ordering = ['-fecha']
    def __str__(self):
        return f"{self.modelo_equipo} ({self.imei}) - {self.fecha}"

class Proyecto(models.Model):
    nombre = models.CharField(max_length=255)
    area = models.CharField(max_length=255)
    detalle = models.TextField()
    def __str__(self):
        return self.nombre

class ActaEntrega(models.Model):
    ESTADO_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Aprobado', 'Aprobado'),
        ('Rechazado', 'Rechazado'),
    ]
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE)
    fecha_entrega = models.DateField()
    version_software = models.CharField(max_length=50)
    responsable = models.CharField(max_length=100)
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Acta #{self.id} - {self.proyecto.nombre}"

class ActaObjetivos(models.Model):
    acta = models.ForeignKey(ActaEntrega, on_delete=models.CASCADE)
    descripcion = models.TextField()

class ActaObservaciones(models.Model):
    acta = models.ForeignKey(ActaEntrega, on_delete=models.CASCADE)
    descripcion = models.TextField()

class ActaRecibidoPor(models.Model):
    acta = models.ForeignKey(ActaEntrega, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    cargo = models.CharField(max_length=100, null=True, blank=True)

class ActaArchivos(models.Model):
    acta = models.ForeignKey(ActaEntrega, on_delete=models.CASCADE)
    nombre_archivo = models.CharField(max_length=255)
    ruta_archivo = models.CharField(max_length=500)
    
class ImagenLogin(models.Model):
    url = models.URLField()
    fecha = models.DateTimeField(auto_now=True)
    
class PagoComision(models.Model):
    idpos = models.CharField(max_length=100, db_index=True)
    punto_de_venta = models.CharField(max_length=200, null=True, blank=True)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='pagos_realizados')
    
    # Se usa default=timezone.now para que sea editable
    fecha_pago = models.DateTimeField(default=timezone.now) 

    monto_total_pagado = models.DecimalField(max_digits=12, decimal_places=2)
    monto_comisiones = models.DecimalField(max_digits=12, decimal_places=2)
    metodos_pago = models.JSONField()

    # Nuevo campo para observaciones
    observacion = models.TextField(blank=True, null=True)

    # 🔴 NUEVO: nombre del archivo del comprobante en SharePoint
    comprobante_url = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Nombre del archivo del comprobante almacenado en SharePoint"
    )

    def __str__(self):
        usuario = self.creado_por.username if self.creado_por else "Usuario Desconocido"
        return f"Pago por {usuario} de {self.monto_total_pagado} el {self.fecha_pago.strftime('%Y-%m-%d')}"

class Configuracion(models.Model):
    """Guarda pares clave-valor para ajustes generales del sistema."""
    clave = models.CharField(max_length=50, unique=True, primary_key=True)
    valor = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.clave}: {self.valor}"
    
class Comision(models.Model):
    asesor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='comisiones',
        help_text="Vínculo al usuario de Django si se encuentra una coincidencia."
    )
    asesor_identificador = models.CharField(
        max_length=250, 
        db_index=True,
        help_text="Nombre del asesor, tal como viene en el archivo Excel."
    )
    iccid = models.CharField(max_length=22, db_index=True)
    distribuidor = models.CharField(max_length=150, blank=True, null=True)
    producto = models.CharField(max_length=100, null=True, blank=True)  
    co_id = models.CharField(max_length=50, blank=True, null=True)
    prim_llamada_activacion = models.DateField(null=True, blank=True)
    min = models.CharField(max_length=50, blank=True, null=True)
    idpos = models.CharField(max_length=50, db_index=True)
    punto_de_venta = models.CharField(max_length=200)
    ruta = models.CharField(max_length=100, blank=True, null=True)
    comision_final = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    pago = models.CharField(max_length=100, blank=True, null=True)
    pagos = models.ForeignKey(PagoComision, on_delete=models.SET_NULL, null=True, blank=True, related_name='comisiones_pagadas')

    
    # --- CAMBIOS CLAVE ---
    mes_liquidacion = models.DateField(null=True, blank=True)
    mes_pago = models.DateField(null=True, blank=True)

    ESTADO_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Acumulada', 'Acumulada'),
        ('Pagada', 'Pagada'),
        ('Consolidada', 'Consolidada'),
        ('Vencida', 'Vencida'),
    ]
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Pendiente', db_index=True)
    fecha_carga = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comisión para {self.asesor_identificador} - ICCID: {self.iccid}"
    

    class Meta:
        verbose_name = "Comisión"
        verbose_name_plural = "Comisiones"
        ordering = ['-prim_llamada_activacion']