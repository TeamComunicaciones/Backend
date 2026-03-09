from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError

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
    
class ComisionCarga(models.Model):  
    ESTADO_CHOICES = [
        ("processing", "Procesando"),
        ("success", "Exitosa"),
        ("error", "Error"),
        ("rolled_back", "Revertida"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="cargas_comisiones",
    )

    file_name = models.CharField(max_length=255, blank=True, null=True)
    mes_detectado = models.DateField(null=True, blank=True)

    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default="processing",
        db_index=True,
    )

    registros_creados = models.PositiveIntegerField(default=0)
    detalle = models.TextField(blank=True, null=True)

    rolled_back_at = models.DateTimeField(null=True, blank=True)
    rolled_back_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rollbacks_comisiones",
    )

    def __str__(self):
        return f"Carga #{self.id} - {self.file_name or 'sin_nombre'} - {self.estado}"

class Comision(models.Model):
    carga = models.ForeignKey(
        "ComisionCarga",                 # <-- string para evitar problemas de orden
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comisiones",
        db_index=True
    )

    asesor = models.ForeignKey(
        settings.AUTH_USER_MODEL,        # <-- recomendado
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

    comision_final = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    pago = models.CharField(max_length=100, blank=True, null=True)

    pagos = models.ForeignKey(
        "PagoComision",                  # <-- string por si PagoComision está debajo
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='comisiones_pagadas'
    )

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

    # Este campo ya no es “tan necesario” porque la carga tiene created_at,
    # pero lo puedes dejar si te sirve para auditoría rápida.
    fecha_carga = models.DateTimeField(auto_now_add=True)

    observacion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Comisión para {self.asesor_identificador} - ICCID: {self.iccid}"

    class Meta:
        verbose_name = "Comisión"
        verbose_name_plural = "Comisiones"
        ordering = ['-prim_llamada_activacion']
        
# ---------------- ROLES PARA COMISIONES ----------------

# Nombres EXACTOS como están en la tabla Permisos.permiso
PERMISO_ASESOR_COMISIONES = "asesor_comisiones"
PERMISO_SUPERVISOR_COMISIONES = "supervisor_comisiones"
PERMISO_ADMIN_COMISIONES = "admin_comisiones"


def user_tiene_permiso_comisiones(user, permiso_name: str) -> bool:
    """
    Verifica si el usuario tiene un permiso activo en Permisos_usuarios
    con el nombre indicado en Permisos.permiso.
    """
    if not user or not user.is_authenticated:
        return False

    return Permisos_usuarios.objects.filter(
        user=user,
        permiso__permiso=permiso_name,
        permiso__active=True,
        tiene_permiso=True
    ).exists()


def user_tiene_algun_permiso_comisiones(user, permiso_names: list[str]) -> bool:
    """
    True si el usuario tiene al menos uno de los permisos indicados.
    """
    if not user or not user.is_authenticated:
        return False

    return Permisos_usuarios.objects.filter(
        user=user,
        permiso__permiso__in=permiso_names,
        permiso__active=True,
        tiene_permiso=True
    ).exists()


def user_es_asesor_comisiones(user) -> bool:
    return user_tiene_permiso_comisiones(user, PERMISO_ASESOR_COMISIONES)


def user_es_supervisor_comisiones(user) -> bool:
    return user_tiene_permiso_comisiones(user, PERMISO_SUPERVISOR_COMISIONES)


def user_es_admin_comisiones(user) -> bool:
    return user_tiene_permiso_comisiones(user, PERMISO_ADMIN_COMISIONES)


class RutaAsignada(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='rutas_comisiones'
    )
    ruta = models.CharField(max_length=100)

    class Meta:
        unique_together = ('user', 'ruta')

    def __str__(self):
        return f'{self.user.username} - {self.ruta}'
    
class IvaExcepcion(models.Model):
    producto = models.CharField(max_length=255, unique=True)
    tipo = models.CharField(max_length=50, default='prepago')  # por si luego usas pospago, etc.

    def __str__(self):
        return f"{self.producto} ({self.tipo})"
class TransparencyReport(models.Model):
    REPORT_TYPES = [
        ("corruption", "Corrupción / Corruption"),
        ("transnational_bribery", "Soborno transnacional / Transnational bribery"),
        ("fraud", "Fraude / Fraud"),
        ("misuse_resources", "Uso inadecuado de recursos / Misuse of resources"),
        (
            "regulatory_irregularities",
            "Irregularidades en el cumplimiento de normas / Regulatory irregularities",
        ),
        ("money_laundering", "Lavado de activos / Money laundering"),
        ("terrorism_financing", "Financiación del terrorismo / Terrorism financing"),
        (
            "wmd_financing",
            "Financiamiento de armas de destrucción masiva / WMD financing",
        ),
        ("other", "Otros / Other"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)

    report_type = models.CharField(
        max_length=64,
        choices=REPORT_TYPES,
        default="other",
    )
    description = models.TextField()
    event_date = models.DateField(null=True, blank=True)

    country = models.CharField(max_length=100, blank=True)
    state = models.CharField("Departamento / Estado", max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)

    people_involved = models.TextField(blank=True)
    supports_text = models.TextField(blank=True)

    wants_identification = models.BooleanField(default=False)
    is_anonymous = models.BooleanField(default=True)

    full_name = models.CharField(max_length=255, blank=True)
    id_number = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)

    locale = models.CharField(max_length=10, blank=True)  # "es" o "en"
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    attachments_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_report_type_display()} - {self.created_at:%Y-%m-%d %H:%M}"
    
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError


class PersonaTurnos(models.Model):
    """
    Personas que agregas manualmente para el planificador (NO son usuarios).
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="personas_turnos"
    )
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["orden", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "nombre"], name="unique_owner_nombre_persona_turnos")
        ]

    def __str__(self):
        return self.nombre


class TurnoPlanner(models.Model):
    """
    Turno por persona y fecha. Soporta turno partido (2 tramos) y almuerzo.
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="turnos_planner"
    )
    persona = models.ForeignKey(
        PersonaTurnos,
        on_delete=models.CASCADE,
        related_name="turnos"
    )
    fecha = models.DateField(db_index=True)

    # Tramo 1
    entrada_1 = models.TimeField()
    salida_1 = models.TimeField()

    # Tramo 2 (opcional)
    entrada_2 = models.TimeField(null=True, blank=True)
    salida_2 = models.TimeField(null=True, blank=True)

    # Almuerzo (opcional)
    almuerzo_inicio = models.TimeField(null=True, blank=True)
    almuerzo_fin = models.TimeField(null=True, blank=True)

    nota = models.CharField(max_length=255, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "persona_id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "persona", "fecha"], name="unique_owner_persona_fecha_turnoplanner")
        ]

    def __str__(self):
        return f"{self.persona.nombre} - {self.fecha}"

    @staticmethod
    def _t2m(t):
        return t.hour * 60 + t.minute

    @staticmethod
    def _subtract_interval(base_start, base_end, sub_start, sub_end):
        if sub_end <= base_start or sub_start >= base_end:
            return [(base_start, base_end)]
        if sub_start <= base_start and sub_end >= base_end:
            return []
        if sub_start <= base_start < sub_end < base_end:
            return [(sub_end, base_end)]
        if base_start < sub_start < base_end <= sub_end:
            return [(base_start, sub_start)]
        if base_start < sub_start and sub_end < base_end:
            return [(base_start, sub_start), (sub_end, base_end)]
        return [(base_start, base_end)]

    def clean(self):
        if self.entrada_1 >= self.salida_1:
            raise ValidationError("En tramo 1, entrada_1 debe ser menor que salida_1.")

        tramo2_parcial = (self.entrada_2 is None) ^ (self.salida_2 is None)
        if tramo2_parcial:
            raise ValidationError("Si usas tramo 2, debes enviar entrada_2 y salida_2.")
        if self.entrada_2 and self.salida_2 and self.entrada_2 >= self.salida_2:
            raise ValidationError("En tramo 2, entrada_2 debe ser menor que salida_2.")

        almuerzo_parcial = (self.almuerzo_inicio is None) ^ (self.almuerzo_fin is None)
        if almuerzo_parcial:
            raise ValidationError("Si usas almuerzo, debes enviar almuerzo_inicio y almuerzo_fin.")
        if self.almuerzo_inicio and self.almuerzo_fin and self.almuerzo_inicio >= self.almuerzo_fin:
            raise ValidationError("almuerzo_inicio debe ser menor que almuerzo_fin.")

    def work_intervals_minutes(self):
        intervals = [(self._t2m(self.entrada_1), self._t2m(self.salida_1))]
        if self.entrada_2 and self.salida_2:
            intervals.append((self._t2m(self.entrada_2), self._t2m(self.salida_2)))

        if self.almuerzo_inicio and self.almuerzo_fin:
            ls, le = self._t2m(self.almuerzo_inicio), self._t2m(self.almuerzo_fin)
            new_intervals = []
            for bs, be in intervals:
                new_intervals.extend(self._subtract_interval(bs, be, ls, le))
            intervals = new_intervals

        return intervals

    @property
    def total_minutes(self):
        return sum(max(0, e - s) for s, e in self.work_intervals_minutes())

    @property
    def total_hours(self):
        return self.total_minutes / 60.0

class Turno(models.Model):
    """
    Turno por persona y fecha.
    Soporta turno partido (dos tramos) y almuerzo (intervalo opcional).
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="turnos")
    fecha = models.DateField(db_index=True)

    # Tramo 1
    entrada_1 = models.TimeField()
    salida_1 = models.TimeField()

    # Tramo 2 (opcional)
    entrada_2 = models.TimeField(null=True, blank=True)
    salida_2 = models.TimeField(null=True, blank=True)

    # Almuerzo (opcional)
    almuerzo_inicio = models.TimeField(null=True, blank=True)
    almuerzo_fin = models.TimeField(null=True, blank=True)

    nota = models.CharField(max_length=255, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)