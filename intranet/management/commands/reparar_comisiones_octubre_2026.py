"""
Reparación única de las comisiones con mes de pago octubre 2026.

Corrige dos incidentes:
  - El Excel de octubre se cargó dos veces por la carga normal (la segunda,
    con rutas corregidas), lo que duplicó las comisiones del mes.
  - Un cambio del día de corte disparó el vencimiento del ciclo antes de
    tiempo; además de vencer, reemplazó el producto por "Vencida por no visita".

Pasos, en una sola transacción:
  1. Toma de la carga duplicada la ruta corregida de cada IDPOS.
  2. Corrige los pagos registrados sobre copias duplicadas:
       - si la original está libre, el pago pasa a la original;
       - si la original ya está en el mismo pago o en otro, la copia sobra: el
         total de comisiones del pago baja a lo real y el saldo pendiente se
         recalcula (nunca negativo; lo pagado de más va a un informe aparte).
     Lo pagado (monto_total_pagado) no se toca. Un pago que no se puede
     corregir con certeza no se toca y queda en el informe para revisión.
  3. Borra la carga duplicada, salvo las filas de los pagos en revisión.
  4. Deshace el vencimiento: estado según la regla de la carga y producto
     original desde el Excel de octubre.
  5. Aplica las rutas corregidas a todas las comisiones de octubre.

Sin --aplicar todo corre igual, pero la transacción se revierte al final.
"""
import csv
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from intranet.models import Comision, PagoComision

ANIO, MES = 2026, 10
INICIO_CARGA_ORIGINAL = datetime(2026, 10, 5, 15, 43, tzinfo=dt_timezone.utc)
INICIO_CARGA_DUPLICADA = datetime(2026, 10, 13, 22, 58, tzinfo=dt_timezone.utc)
FIN_CARGA_DUPLICADA = datetime(2026, 10, 13, 23, 10, tzinfo=dt_timezone.utc)
PRODUCTO_NO_VISITA = 'Vencida por no visita'
HORA_COLOMBIA = dt_timezone(timedelta(hours=-5))

MOVER = 'mover'
MISMO_PAGO = 'la original está en el mismo pago'
OTRO_PAGO = 'la original ya está pagada en otro pago'
SIN_ORIGINAL = 'sin comisión original'

Q_MES = Q(mes_pago__year=ANIO, mes_pago__month=MES)
Q_LEDGER = (
    Q(iccid__startswith='PAGO-') | Q(iccid__startswith='SALDO-')
    | Q(iccid__startswith='ACUM-') | Q(iccid__startswith='AJUSTE-')
)
# Filas que crea pagar_comisiones_view: prefijo de iccid -> (estado, producto)
LEDGER = {
    'SALDO-': ('Pendiente', 'SALDO PENDIENTE PAGO #{}'),
    'AJUSTE-': ('Acumulada', 'AJUSTE POR SOBRANTE PAGO #{}'),
    'ACUM-': ('Acumulada', 'USO DE SALDO EN PAGO #{}'),
}
# Campos del Excel que no cambian con pagos, rutas ni vencimientos
CLAVE = ('iccid', 'idpos', 'comision_final', 'co_id', 'min',
         'prim_llamada_activacion', 'mes_liquidacion')
LOTE = 2000


class Command(BaseCommand):
    help = 'Repara la carga duplicada y el vencimiento anticipado de las comisiones de octubre 2026.'

    def add_arguments(self, parser):
        parser.add_argument('--excel', required=True,
                            help='Excel original de comisiones de octubre (para recuperar el producto).')
        parser.add_argument('--informe', required=True,
                            help='Carpeta donde se escriben los CSV del informe.')
        parser.add_argument('--aplicar', action='store_true',
                            help='Guarda los cambios. Sin esta opción es una simulación.')

    def handle(self, *args, excel, informe, aplicar, **options):
        productos = _productos_desde_excel(excel)
        os.makedirs(informe, exist_ok=True)

        with transaction.atomic():
            resumen = _reparar(productos, informe)
            if not aplicar:
                transaction.set_rollback(True)

        modo = 'APLICADO' if aplicar else 'SIMULACIÓN (no se guardó nada)'
        self.stdout.write(f'== {modo}')
        for clave, valor in resumen.items():
            self.stdout.write(f'{clave}: {valor}')
        self.stdout.write(f'Informe en: {informe}')


def _productos_desde_excel(ruta):
    try:
        hojas = pd.read_excel(ruta, sheet_name=None, dtype=str)
    except Exception as e:
        raise CommandError(f'No se pudo leer el Excel: {e}')

    productos = defaultdict(set)
    for df in hojas.values():
        faltantes = {'ICCID', 'PRODUCTO', 'MES PAGO'} - set(df.columns)
        if faltantes:
            raise CommandError(f'Al Excel le faltan columnas: {sorted(faltantes)}')
        meses = set(df['MES PAGO'].dropna().astype(str).str.strip().str.lower())
        if meses != {'octubre 2026'}:
            raise CommandError(f'El Excel no es de octubre 2026: {sorted(meses)}')
        for iccid, producto in zip(df['ICCID'], df['PRODUCTO']):
            iccid = str(iccid).strip() if pd.notna(iccid) else ''
            producto = str(producto).strip() if pd.notna(producto) else ''
            if iccid and producto:
                productos[iccid].add(producto)
    # Un ICCID con dos productos distintos no se puede recuperar sin adivinar
    return {iccid: p.pop() for iccid, p in productos.items() if len(p) == 1}


def _reparar(productos, informe):
    resumen = {}
    duplicadas = Comision.objects.filter(
        Q_MES,
        fecha_carga__gte=INICIO_CARGA_DUPLICADA,
        fecha_carga__lte=FIN_CARGA_DUPLICADA,
    ).exclude(Q_LEDGER)
    originales = Comision.objects.filter(
        Q_MES, fecha_carga__lt=INICIO_CARGA_DUPLICADA
    ).exclude(Q_LEDGER)
    resumen['filas carga duplicada'] = duplicadas.count()
    resumen['filas carga original'] = originales.count()

    ruta_por_idpos, conflictos_ruta = _rutas_corregidas(duplicadas)
    resumen['IDPOS con ruta corregida'] = len(ruta_por_idpos)
    resumen['IDPOS con dos rutas en la carga duplicada (no se tocan)'] = len(conflictos_ruta)

    en_revision = _corregir_pagos(duplicadas, originales, informe, resumen)

    resumen['filas duplicadas borradas'] = duplicadas.exclude(id__in=en_revision).delete()[0]
    resumen['filas duplicadas que quedan (pagos en revisión)'] = len(en_revision)

    _deshacer_vencimiento(productos, informe, resumen)

    actualizadas = 0
    idpos_por_ruta = defaultdict(list)
    for idpos, ruta in ruta_por_idpos.items():
        idpos_por_ruta[ruta].append(idpos)
    for ruta, idpos in idpos_por_ruta.items():
        for i in range(0, len(idpos), LOTE):
            actualizadas += (
                Comision.objects.filter(Q_MES, idpos__in=idpos[i:i + LOTE])
                .exclude(ruta=ruta).update(ruta=ruta)
            )
    resumen['filas de octubre con ruta actualizada'] = actualizadas

    _escribir_csv(informe, 'idpos_con_dos_rutas.csv', ['idpos', 'rutas'],
                  [[i, ' | '.join(sorted(r))] for i, r in sorted(conflictos_ruta.items())])
    return resumen


def _rutas_corregidas(duplicadas):
    rutas = defaultdict(set)
    for idpos, ruta in duplicadas.values_list('idpos', 'ruta'):
        if idpos and ruta and str(ruta).strip():
            rutas[idpos].add(ruta)
    unicas = {i: r.pop() for i, r in rutas.items() if len(r) == 1}
    conflictos = {i: r for i, r in rutas.items() if len(r) > 1}
    return unicas, conflictos


def _corregir_pagos(duplicadas, originales, informe, resumen):
    """
    Corrige los pagos hechos sobre copias duplicadas. Devuelve los ids de las
    copias que deben quedarse porque su pago va a revisión.
    """
    pagadas = list(duplicadas.filter(pagos__isnull=False).values('id', 'pagos_id', *CLAVE))
    candidatas = defaultdict(list)
    for c in originales.filter(
        iccid__in={p['iccid'] for p in pagadas},
        idpos__in={p['idpos'] for p in pagadas},
    ).values('id', 'pagos_id', 'estado', *CLAVE):
        candidatas[tuple(c[k] for k in CLAVE)].append(c)

    por_pago = defaultdict(list)
    for fila in pagadas:
        por_pago[fila['pagos_id']].append(fila)
    pagos = PagoComision.objects.select_related('creado_por').in_bulk(list(por_pago))

    usadas = set()
    movidas = 0
    en_revision = set()
    filas_revision, corregidos, de_mas = [], [], []
    for pago_id, filas in sorted(por_pago.items()):
        pago = pagos[pago_id]
        decisiones = []
        for fila in filas:
            opciones = [c for c in candidatas[tuple(fila[k] for k in CLAVE)] if c['id'] not in usadas]
            misma = next((c for c in opciones if c['pagos_id'] == pago_id), None)
            libre = next((c for c in opciones
                          if c['pagos_id'] is None and c['estado'] != 'Consolidada'), None)
            if misma:
                motivo, original = MISMO_PAGO, misma
            elif libre:
                motivo, original = MOVER, libre
            elif opciones:
                motivo, original = OTRO_PAGO, opciones[0]
            else:
                motivo, original = SIN_ORIGINAL, None
            if original:
                usadas.add(original['id'])
            decisiones.append((fila, motivo, original))

        exceso = sum((f['comision_final'] or Decimal('0')
                      for f, motivo, _ in decisiones if motivo in (MISMO_PAGO, OTRO_PAGO)), Decimal('0'))
        correcto = pago.monto_comisiones - exceso
        restante = correcto - pago.monto_total_pagado
        saldos = list(Comision.objects.filter(iccid=f'SALDO-{pago_id}'))
        saldo = saldos[0] if saldos else None

        if any(motivo == SIN_ORIGINAL for _, motivo, _ in decisiones):
            revision = 'hay copias sin comisión original'
        elif len(saldos) > 1:
            revision = 'el pago tiene más de un saldo pendiente'
        elif exceso and saldo and saldo.pagos_id != pago_id:
            revision = 'el saldo pendiente de este pago ya se cobró en otro pago'
        elif exceso and restante > 0 and not saldo:
            revision = 'falta el saldo pendiente que habría que corregir'
        elif exceso and Comision.objects.filter(iccid=f'AJUSTE-{pago_id}').exists():
            revision = 'el pago ya tiene un ajuste por sobrante'
        elif correcto < 0:
            revision = 'el total corregido queda negativo'
        else:
            revision = None

        if revision:
            en_revision.update(f['id'] for f, _, _ in decisiones)
            filas_revision.extend(
                [pago_id, f['id'], f['iccid'], f['idpos'], f['comision_final'], motivo,
                 original['id'] if original else '', original['pagos_id'] if original else '', revision]
                for f, motivo, original in decisiones
            )
            continue

        for _, motivo, original in decisiones:
            if motivo == MOVER:
                Comision.objects.filter(id=original['id']).update(estado='Consolidada', pagos_id=pago_id)
                movidas += 1
        if not exceso:
            continue

        saldo_antes = saldo.comision_final if saldo else Decimal('0')
        total_antes = pago.monto_comisiones
        pago.monto_comisiones = correcto
        pago.save(update_fields=['monto_comisiones'])
        if restante > 0:
            saldo.comision_final = restante
            saldo.save(update_fields=['comision_final'])
        elif saldo:
            saldo.delete()

        datos = [pago_id, _hora_colombia(pago.fecha_pago),
                 pago.creado_por.username if pago.creado_por else '', pago.idpos, pago.punto_de_venta]
        pagado_de_mas = max(-restante, Decimal('0'))
        corregidos.append(datos + [total_antes, correcto, pago.monto_total_pagado,
                                   saldo_antes, max(restante, Decimal('0')), pagado_de_mas])
        if pagado_de_mas:
            otros = sorted({o['pagos_id'] for _, m, o in decisiones if m == OTRO_PAGO})
            detalle = []
            if any(m == MISMO_PAGO for _, m, _ in decisiones):
                detalle.append('se seleccionaron la comisión original y su copia')
            if otros:
                detalle.append('comisiones ya pagadas en el pago ' + ', '.join(map(str, otros)))
            de_mas.append(datos + [correcto, pago.monto_total_pagado, pagado_de_mas, '; '.join(detalle)])

    resumen['pagos sobre filas duplicadas'] = len(por_pago)
    resumen['filas de pago pasadas a la original'] = movidas
    resumen['pagos corregidos'] = len(corregidos)
    resumen['pagos con pago de más'] = len(de_mas)
    resumen['total pagado de más'] = sum((f[7] for f in de_mas), Decimal('0'))
    resumen['pagos en revisión (no se tocan)'] = len({f[0] for f in filas_revision})

    encabezado = ['pago_id', 'fecha_pago_hora_colombia', 'registrado_por', 'idpos', 'punto_de_venta']
    _escribir_csv(informe, 'pagos_corregidos.csv',
                  encabezado + ['total_registrado_antes', 'total_correcto', 'se_pago',
                                'saldo_pendiente_antes', 'saldo_pendiente_despues', 'pagado_de_mas'],
                  corregidos)
    _escribir_csv(informe, 'pagos_pagados_de_mas.csv',
                  encabezado + ['se_debia', 'se_pago', 'pagado_de_mas', 'detalle'], de_mas)
    _escribir_csv(informe, 'filas_en_revision.csv',
                  ['pago_id', 'comision_duplicada_id', 'iccid', 'idpos', 'comision_final',
                   'motivo', 'comision_original_id', 'pago_de_la_original', 'por_que_no_se_corrige'],
                  filas_revision)
    return en_revision


def _hora_colombia(fecha):
    return fecha.astimezone(HORA_COLOMBIA).strftime('%Y-%m-%d %H:%M') if fecha else ''


def _deshacer_vencimiento(productos, informe, resumen):
    # Desde la carga de octubre ningún vencimiento legítimo alcanzó estas filas;
    # el mes de pago cubre las que un reverso de pago movió a octubre.
    alcance = Q(fecha_carga__gte=INICIO_CARGA_ORIGINAL) | Q_MES
    vencidas = Comision.objects.filter(alcance, estado='Vencida')
    resumen['filas vencidas a restaurar'] = vencidas.count()

    restauradas = defaultdict(int)
    for prefijo, (estado, _) in LEDGER.items():
        restauradas[estado] += vencidas.filter(iccid__startswith=prefijo).update(estado=estado)
    restantes = vencidas.exclude(Q_LEDGER)
    # Las creadas a mano no traen el campo pago del Excel y nacen Pendiente
    restauradas['Pendiente'] += restantes.filter(pago__isnull=True).update(estado='Pendiente')
    # Misma regla que procesar_archivo_comisiones
    restauradas['Acumulada'] += restantes.filter(
        Q(iccid='') | Q(pago__icontains='acumulado')
    ).update(estado='Acumulada')
    restauradas['Pendiente'] += restantes.update(estado='Pendiente')
    resumen['restauradas a Pendiente'] = restauradas['Pendiente']
    resumen['restauradas a Acumulada'] = restauradas['Acumulada']
    resumen['vencidas sin restaurar'] = vencidas.count()

    cambios = []
    sin_producto = []
    for c in Comision.objects.filter(alcance, producto=PRODUCTO_NO_VISITA).only('id', 'iccid', 'pago'):
        prefijo = next((p for p in LEDGER if c.iccid.startswith(p)), None)
        if prefijo:
            c.producto = LEDGER[prefijo][1].format(c.iccid[len(prefijo):])
        elif c.iccid in productos:
            c.producto = productos[c.iccid]
        elif c.iccid == '':
            c.producto = ''
        elif c.iccid.startswith('MANUAL-'):
            c.producto = None
        else:
            sin_producto.append([c.id, c.iccid])
            continue
        cambios.append(c)
    Comision.objects.bulk_update(cambios, ['producto'], batch_size=LOTE)
    resumen['productos recuperados'] = len(cambios)
    resumen['productos sin recuperar'] = len(sin_producto)
    _escribir_csv(informe, 'productos_sin_recuperar.csv', ['comision_id', 'iccid'], sin_producto)


def _escribir_csv(carpeta, nombre, encabezados, filas):
    with open(os.path.join(carpeta, nombre), 'w', newline='', encoding='utf-8-sig') as f:
        escritor = csv.writer(f)
        escritor.writerow(encabezados)
        escritor.writerows(filas)
