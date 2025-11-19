# utils_reporting.py
from decimal import Decimal

from django.db.models import Sum, Count
from django.db.models.functions import Coalesce

from .models import Comision, PagoComision


def decimal_or_zero(value):
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal('0')


def aggregate_sum(qs, field_name):
    return decimal_or_zero(
        qs.aggregate(total=Coalesce(Sum(field_name), 0))['total']
    )


def build_kpis_for_comisiones(qs):
    """
    KPIs calculados SOLO a partir de Comision,
    usando SIEMPRE el mismo queryset base (mismos filtros).
    Así evitamos descuadres y valores negativos.
    """
    total_comisiones = aggregate_sum(qs, 'comision_final')
    total_pagado = aggregate_sum(qs.filter(estado='Pagada'), 'comision_final')
    total_pendiente = aggregate_sum(
        qs.filter(estado__in=['Pendiente', 'Acumulada']),
        'comision_final'
    )

    # Seguridad extra: nunca negativos
    total_comisiones = max(total_comisiones, Decimal('0'))
    total_pagado = max(total_pagado, Decimal('0'))
    total_pendiente = max(total_pendiente, Decimal('0'))

    return {
        'totalComisiones': total_comisiones,
        'totalPagado': total_pagado,
        'totalPendiente': total_pendiente,
    }


def build_estado_chart(qs):
    """
    Distribución por estado: cuenta de comisiones por estado.
    """
    data = (
        qs.values('estado')
          .annotate(count=Count('id'))
          .order_by('estado')
    )
    return [
        {'estado': item['estado'], 'count': item['count']}
        for item in data
    ]


def build_metodos_pago_chart(qs):
    """
    Agrega métodos de pago SOLO para pagos que estén vinculados
    a comisiones del queryset.
    Nota: si un PagoComision contiene comisiones de varios meses,
    aparecerá en varios filtros, pero es consistente con el uso actual.
    """
    pagos_qs = (
        PagoComision.objects
        .filter(comisiones_pagadas__in=qs)
        .distinct()
    )

    metodos_totales = {}  # { 'Nequi': {'total_valor': Decimal, 'total_cantidad': int}, ... }

    for pago in pagos_qs:
        metodos = pago.metodos_pago or {}
        for metodo, valor in metodos.items():
            valor_dec = decimal_or_zero(valor)
            if metodo not in metodos_totales:
                metodos_totales[metodo] = {
                    'total_valor': Decimal('0'),
                    'total_cantidad': 0,
                }
            metodos_totales[metodo]['total_valor'] += valor_dec
            metodos_totales[metodo]['total_cantidad'] += 1

    result = []
    for metodo, info in metodos_totales.items():
        total_valor = max(info['total_valor'], Decimal('0'))
        total_cantidad = max(info['total_cantidad'], 0)
        result.append({
            'metodo': metodo,
            'total_valor': total_valor,
            'total_cantidad': total_cantidad,
        })
    return result
