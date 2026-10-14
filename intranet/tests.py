import csv
import os
import tempfile
from datetime import date, datetime, timezone as dt_timezone
from io import BytesIO, StringIO

import jwt
import pandas as pd
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from . import models
from .views import _leer_excel_comisiones

URL_PREVIEW = '/api/v1.0/admin/comisiones/rutas/preview/'
URL_APLICAR = '/api/v1.0/admin/comisiones/rutas/aplicar/'
OCTUBRE = date(2026, 10, 1)
SEPTIEMBRE = date(2026, 9, 1)


def _excel(filas):
    buffer = BytesIO()
    pd.DataFrame(filas).to_excel(buffer, index=False)
    return SimpleUploadedFile(
        'comisiones.xlsx',
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


def _comision(idpos, ruta, mes_pago, **extra):
    datos = {
        'asesor_identificador': 'asesor',
        'iccid': f'ICC-{idpos}',
        'punto_de_venta': f'PDV {idpos}',
        'comision_final': 1000,
        'estado': 'Pendiente',
    }
    datos.update(extra)
    return models.Comision.objects.create(idpos=idpos, ruta=ruta, mes_pago=mes_pago, **datos)


class ActualizarRutasComisionesTests(TestCase):

    def setUp(self):
        admin = User.objects.create_user('admin', password='x')
        permiso = models.Permisos.objects.create(permiso='admin_comisiones', active=True)
        models.Permisos_usuarios.objects.create(user=admin, permiso=permiso, tiene_permiso=True)
        token = jwt.encode({'id': admin.id}, settings.SECRET_KEY, algorithm='HS256')
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        asesor = User.objects.create_user('asesor_a', password='x')
        models.Perfil.objects.create(user=asesor, ruta_asignada='RUTA A')
        supervisor = User.objects.create_user('supervisor_b', password='x')
        models.RutaAsignada.objects.create(user=supervisor, ruta='RUTA B')

        # IDPOS 100: comisiones del Excel en octubre, una pagada, con la fila
        # que crea el pago; y una comisión de septiembre que no debe moverse.
        self.pago = models.PagoComision.objects.create(
            idpos='100', monto_total_pagado=1000, monto_comisiones=1000,
            metodos_pago={'Nequi': 1000},
        )
        _comision('100', 'RUTA A', OCTUBRE, estado='Consolidada', pagos=self.pago)
        _comision('100', 'RUTA A', OCTUBRE)
        _comision('100', 'RUTA A', OCTUBRE, estado='Pagada', iccid='PAGO-1',
                  producto='PAGO REGISTRADO #1', pagos=self.pago)
        self.septiembre = _comision('100', 'RUTA A', SEPTIEMBRE)
        _comision('200', 'RUTA B', OCTUBRE)
        _comision('300', 'RUTA A', OCTUBRE)

        self.excel_filas = [
            {'MES PAGO': 'Octubre 2026', 'IDPOS': '100', 'RUTA': 'RUTA C'},
            {'MES PAGO': 'Octubre 2026', 'IDPOS': '100', 'RUTA': 'RUTA C'},
            {'MES PAGO': 'Octubre 2026', 'IDPOS': '200', 'RUTA': 'RUTA B'},
            {'MES PAGO': 'Octubre 2026', 'IDPOS': '300', 'RUTA': 'RUTA A'},
            {'MES PAGO': 'Octubre 2026', 'IDPOS': '300', 'RUTA': 'RUTA B'},
        ]

    def _preview(self):
        return self.client.post(URL_PREVIEW, {'file': _excel(self.excel_filas)}, format='multipart')

    def test_preview_lista_cambios_conflictos_y_rutas_sin_asesor(self):
        respuesta = self._preview()

        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data['mes_pago'], '2026-10')
        self.assertEqual(respuesta.data['cambios'], [{
            'idpos': '100',
            'punto_de_venta': 'PDV 100',
            'rutas_actuales': ['RUTA A'],
            'ruta_nueva': 'RUTA C',
            'filas': 3,
        }])
        self.assertEqual(respuesta.data['conflictos'], [{'idpos': '300', 'rutas': ['RUTA A', 'RUTA B']}])
        self.assertEqual(respuesta.data['rutas_sin_asesor'], ['RUTA C'])

    def test_preview_no_modifica_nada(self):
        self._preview()

        self.assertFalse(models.Comision.objects.exclude(ruta__in=['RUTA A', 'RUTA B']).exists())

    def test_preview_exige_columnas_idpos_y_ruta(self):
        archivo = _excel([{'MES PAGO': 'Octubre 2026', 'IDPOS': '100'}])

        respuesta = self.client.post(URL_PREVIEW, {'file': archivo}, format='multipart')

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('RUTA', respuesta.data['errores'][0])

    def test_aplicar_mueve_solo_el_mes_y_conserva_el_pago(self):
        preview = self._preview().data
        cambios = [{'idpos': c['idpos'], 'ruta_nueva': c['ruta_nueva']} for c in preview['cambios']]

        respuesta = self.client.post(
            URL_APLICAR, {'mes_pago': preview['mes_pago'], 'cambios': cambios}, format='json'
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data, {'idpos_actualizados': 1, 'filas_actualizadas': 3})
        octubre_100 = models.Comision.objects.filter(idpos='100', mes_pago=OCTUBRE)
        self.assertEqual(set(octubre_100.values_list('ruta', flat=True)), {'RUTA C'})
        self.septiembre.refresh_from_db()
        self.assertEqual(self.septiembre.ruta, 'RUTA A')
        self.assertTrue(models.PagoComision.objects.filter(pk=self.pago.pk).exists())
        self.assertEqual(
            set(self.pago.comisiones_pagadas.values_list('estado', flat=True)),
            {'Consolidada', 'Pagada'},
        )
        self.assertEqual(models.Comision.objects.get(idpos='300').ruta, 'RUTA A')

    def test_aplicar_rechaza_mes_invalido_o_sin_cambios(self):
        sin_mes = self.client.post(
            URL_APLICAR, {'mes_pago': 'octubre', 'cambios': [{'idpos': '100', 'ruta_nueva': 'X'}]},
            format='json',
        )
        sin_cambios = self.client.post(URL_APLICAR, {'mes_pago': '2026-10', 'cambios': []}, format='json')

        self.assertEqual(sin_mes.status_code, 400)
        self.assertEqual(sin_cambios.status_code, 400)
        self.assertFalse(models.Comision.objects.filter(ruta='X').exists())


class LeerExcelComisionesTests(TestCase):

    def test_rechaza_archivo_con_varios_meses(self):
        archivo = _excel([
            {'MES PAGO': 'Octubre 2026', 'IDPOS': '100'},
            {'MES PAGO': 'Noviembre 2026', 'IDPOS': '200'},
        ])

        df, mes_pago, errores = _leer_excel_comisiones(archivo)

        self.assertIsNone(df)
        self.assertIsNone(mes_pago)
        self.assertIn('Solo se permite un mes de PAGO', errores[0])

    def test_devuelve_el_mes_del_archivo(self):
        _, mes_pago, errores = _leer_excel_comisiones(_excel([{'MES PAGO': 'Octubre 2026'}]))

        self.assertEqual(errores, [])
        self.assertEqual(mes_pago.strftime('%Y-%m'), '2026-10')


FECHA_CARGA_ORIGINAL = datetime(2026, 10, 5, 16, 0, tzinfo=dt_timezone.utc)
FECHA_CARGA_DUPLICADA = datetime(2026, 10, 13, 23, 0, tzinfo=dt_timezone.utc)
FECHA_PAGO_NOCHE = datetime(2026, 10, 13, 23, 30, tzinfo=dt_timezone.utc)
NO_VISITA = 'Vencida por no visita'


def _fila(fecha, idpos, ruta, iccid, estado='Vencida', producto='PREPAGO', pago='',
          mes=OCTUBRE, pagos=None):
    fila = models.Comision.objects.create(
        asesor_identificador='asesor', iccid=iccid, idpos=idpos, punto_de_venta=f'PDV {idpos}',
        ruta=ruta, mes_pago=mes, mes_liquidacion=mes, comision_final=1000, estado=estado,
        producto=producto, pago=pago, pagos=pagos, co_id=f'CO-{iccid}', min='300',
    )
    models.Comision.objects.filter(pk=fila.pk).update(fecha_carga=fecha)
    return fila


def _pago(idpos, comisiones=1000, pagado=1000):
    return models.PagoComision.objects.create(
        idpos=idpos, monto_total_pagado=pagado, monto_comisiones=comisiones, metodos_pago={'Nequi': pagado},
    )


class RepararComisionesOctubreTests(TestCase):

    def setUp(self):
        self.carpeta = tempfile.mkdtemp()
        self.excel = os.path.join(self.carpeta, 'octubre.xlsx')
        pd.DataFrame([
            {'ICCID': iccid, 'PRODUCTO': producto, 'MES PAGO': 'Octubre 2026'}
            for iccid, producto in [('I1', 'PROD-I1'), ('I2', 'PROD-I2'), ('I4', 'PREPAGO'),
                                    ('I5', 'PROD-I5'), ('I8', 'PREPAGO'), ('I10', 'PROD-I10')]
        ]).to_excel(self.excel, index=False)

        pago_antes, self.pago_antes_p6, otro_pago = _pago('P1'), _pago('P6'), _pago('P8')
        self.pago_mover = _pago('P4')
        # Original y copia seleccionadas juntas: se registró el doble y se pagó menos de lo debido
        self.pago_mixto = _pago('P5', comisiones=2000, pagado=600)
        # La original ya la había pagado otro pago: todo lo pagado aquí es de más
        self.pago_doble = _pago('P6')
        self.pago_sin_original = _pago('P9')
        self.pago_saldo_cobrado = _pago('P8', comisiones=2000, pagado=500)

        o = FECHA_CARGA_ORIGINAL
        self.o1 = _fila(o, 'P1', 'RUTA A', 'I1', producto=NO_VISITA)
        self.o2 = _fila(o, 'P1', 'RUTA A', 'I2', estado='Consolidada', pagos=pago_antes)
        self.o3 = _fila(o, 'P2', 'RUTA A', '', producto=NO_VISITA)
        self.o4 = _fila(o, 'P3', 'RUTA A', 'I4')
        self.o5 = _fila(o, 'P4', 'RUTA A', 'I5', producto=NO_VISITA)
        self.o6 = _fila(o, 'P5', 'RUTA A', 'I6', estado='Consolidada', pagos=self.pago_mixto)
        self.o7 = _fila(o, 'P6', 'RUTA A', 'I7', estado='Consolidada', pagos=self.pago_antes_p6)
        self.o11 = _fila(o, 'P8', 'RUTA A', 'I11', estado='Consolidada', pagos=self.pago_saldo_cobrado)
        self.o8 = _fila(o, 'P7', 'RUTA A', 'I8')
        self.o10 = _fila(o, 'P3', 'RUTA A', 'I10', pago='acumulado')
        self.manual = _fila(o, 'P3', 'RUTA A', 'MANUAL-1', producto=NO_VISITA, pago=None)
        self.septiembre = _fila(datetime(2026, 9, 3, tzinfo=dt_timezone.utc), 'P1', 'RUTA A', 'I1S',
                                producto=NO_VISITA, mes=SEPTIEMBRE)

        d = FECHA_CARGA_DUPLICADA
        self.duplicadas_libres = [
            _fila(d, 'P1', 'RUTA B', 'I1'), _fila(d, 'P1', 'RUTA B', 'I2'), _fila(d, 'P2', 'RUTA A', ''),
            _fila(d, 'P3', 'RUTA A', 'I4'), _fila(d, 'P3', 'RUTA A', 'I10', pago='acumulado'),
            _fila(d, 'P7', 'RUTA C', 'I8'), _fila(d, 'P7', 'RUTA D', 'I8B'),
        ]
        self.d5 = _fila(d, 'P4', 'RUTA A', 'I5', estado='Consolidada', pagos=self.pago_mover)
        self.d6 = _fila(d, 'P5', 'RUTA A', 'I6', estado='Consolidada', pagos=self.pago_mixto)
        self.d7 = _fila(d, 'P6', 'RUTA A', 'I7', estado='Consolidada', pagos=self.pago_doble)
        self.d9 = _fila(d, 'P9', 'RUTA A', 'I9', estado='Consolidada', pagos=self.pago_sin_original)
        self.d11 = _fila(d, 'P8', 'RUTA A', 'I11', estado='Consolidada', pagos=self.pago_saldo_cobrado)

        n = FECHA_PAGO_NOCHE
        self.saldo = _fila(n, 'P4', 'RUTA A', f'SALDO-{self.pago_mover.id}',
                           producto=NO_VISITA, pagos=self.pago_mover)
        self.saldo_mixto = _fila(n, 'P5', 'RUTA A', f'SALDO-{self.pago_mixto.id}', pagos=self.pago_mixto)
        models.Comision.objects.filter(pk=self.saldo_mixto.pk).update(comision_final=1400)
        self.saldo_cobrado = _fila(n, 'P8', 'RUTA A', f'SALDO-{self.pago_saldo_cobrado.id}',
                                   estado='Consolidada', pagos=otro_pago)

    def _correr(self, aplicar):
        opciones = {'excel': self.excel, 'informe': self.carpeta, 'stdout': StringIO()}
        if aplicar:
            opciones['aplicar'] = True
        call_command('reparar_comisiones_octubre_2026', **opciones)

    def _foto(self):
        return (
            list(models.Comision.objects.order_by('id')
                 .values_list('id', 'estado', 'producto', 'ruta', 'pagos_id', 'comision_final')),
            list(models.PagoComision.objects.order_by('id').values_list('id', 'monto_comisiones')),
        )

    def _csv(self, nombre):
        with open(os.path.join(self.carpeta, nombre), encoding='utf-8-sig') as f:
            return list(csv.DictReader(f))

    def _recargar(self, *filas):
        for fila in filas:
            fila.refresh_from_db()

    def test_simulacion_no_guarda_nada_pero_escribe_el_informe(self):
        antes = self._foto()

        self._correr(aplicar=False)

        self.assertEqual(self._foto(), antes)
        de_mas = {int(f['pago_id']) for f in self._csv('pagos_pagados_de_mas.csv')}
        self.assertEqual(de_mas, {self.pago_doble.id})

    def test_borra_duplicados_y_pasa_el_pago_a_la_original_libre(self):
        self._correr(aplicar=True)

        duplicadas = [f.id for f in self.duplicadas_libres] + [
            self.d5.id, self.d6.id, self.d7.id, self.d9.id, self.d11.id]
        quedan = set(models.Comision.objects.filter(id__in=duplicadas).values_list('id', flat=True))
        self.assertEqual(quedan, {self.d9.id, self.d11.id})
        self.o5.refresh_from_db()
        self.assertEqual((self.o5.estado, self.o5.pagos_id), ('Consolidada', self.pago_mover.id))

    def test_pago_con_original_y_copia_queda_con_total_y_saldo_reales(self):
        self._correr(aplicar=True)

        self._recargar(self.pago_mixto, self.saldo_mixto, self.o6)
        self.assertEqual(self.pago_mixto.monto_comisiones, 1000)
        self.assertEqual(self.pago_mixto.monto_total_pagado, 600)
        self.assertEqual((self.saldo_mixto.comision_final, self.saldo_mixto.estado), (400, 'Pendiente'))
        self.assertEqual(self.o6.pagos_id, self.pago_mixto.id)

    def test_pago_de_mas_queda_sin_saldo_y_en_su_informe(self):
        self._correr(aplicar=True)

        self.pago_doble.refresh_from_db()
        self.assertEqual(self.pago_doble.monto_comisiones, 0)
        [fila] = self._csv('pagos_pagados_de_mas.csv')
        self.assertEqual((fila['se_debia'], fila['se_pago'], fila['pagado_de_mas']), ('0.00', '1000.00', '1000.00'))
        self.assertIn(f'ya pagadas en el pago {self.pago_antes_p6.id}', fila['detalle'])
        corregidos = {int(f['pago_id']) for f in self._csv('pagos_corregidos.csv')}
        self.assertEqual(corregidos, {self.pago_mixto.id, self.pago_doble.id})

    def test_pagos_que_no_se_pueden_corregir_no_se_tocan(self):
        self._correr(aplicar=True)

        self._recargar(self.d9, self.d11, self.pago_saldo_cobrado)
        self.assertEqual(self.d9.pagos_id, self.pago_sin_original.id)
        self.assertEqual(self.pago_saldo_cobrado.monto_comisiones, 2000)
        motivos = {int(f['pago_id']): f['por_que_no_se_corrige'] for f in self._csv('filas_en_revision.csv')}
        self.assertEqual(motivos, {
            self.pago_sin_original.id: 'hay copias sin comisión original',
            self.pago_saldo_cobrado.id: 'el saldo pendiente de este pago ya se cobró en otro pago',
        })

    def test_deshace_el_vencimiento_con_estado_y_producto_originales(self):
        self._correr(aplicar=True)

        self._recargar(self.o1, self.o3, self.o4, self.o5, self.o10, self.manual, self.saldo)
        self.assertEqual((self.o1.estado, self.o1.producto), ('Pendiente', 'PROD-I1'))
        self.assertEqual((self.o3.estado, self.o3.producto), ('Acumulada', ''))
        self.assertEqual((self.o4.estado, self.o4.producto), ('Pendiente', 'PREPAGO'))
        self.assertEqual(self.o5.producto, 'PROD-I5')
        self.assertEqual(self.o10.estado, 'Acumulada')
        self.assertEqual((self.manual.estado, self.manual.producto), ('Pendiente', None))
        self.assertEqual((self.saldo.estado, self.saldo.producto),
                         ('Pendiente', f'SALDO PENDIENTE PAGO #{self.pago_mover.id}'))

    def test_no_toca_meses_anteriores(self):
        self._correr(aplicar=True)

        self.septiembre.refresh_from_db()
        self.assertEqual((self.septiembre.estado, self.septiembre.producto), ('Vencida', NO_VISITA))

    def test_aplica_las_rutas_corregidas_salvo_idpos_con_dos_rutas(self):
        self._correr(aplicar=True)

        self._recargar(self.o1, self.o2, self.o8)
        self.assertEqual((self.o1.ruta, self.o2.ruta), ('RUTA B', 'RUTA B'))
        self.assertEqual(self.o8.ruta, 'RUTA A')
        self.assertEqual([f['idpos'] for f in self._csv('idpos_con_dos_rutas.csv')], ['P7'])

    def test_correrlo_dos_veces_no_cambia_nada_mas(self):
        self._correr(aplicar=True)
        despues = self._foto()

        self._correr(aplicar=True)

        self.assertEqual(self._foto(), despues)

    def test_rechaza_un_excel_de_otro_mes(self):
        pd.DataFrame([{'ICCID': 'I1', 'PRODUCTO': 'X', 'MES PAGO': 'Septiembre 2026'}]).to_excel(
            self.excel, index=False)

        with self.assertRaisesMessage(Exception, 'no es de octubre 2026'):
            self._correr(aplicar=False)
