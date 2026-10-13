from datetime import date
from io import BytesIO

import jwt
import pandas as pd
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
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
