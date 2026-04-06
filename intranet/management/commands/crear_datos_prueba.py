from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from intranet.models import (
    Perfil, Permisos, Permisos_usuarios, Comision, ComisionCarga,
    PagoComision, Configuracion, RutaAsignada,
)


class Command(BaseCommand):
    help = 'Crea datos de prueba completos para desarrollo local.'

    def handle(self, *args, **options):
        self.stdout.write('Creando datos de prueba...')

        # ── 1. USUARIOS ──────────────────────────────────────────────────────────
        admin = self._crear_usuario('admin', 'admin@test.com', 'Admin2024!')
        asesor1 = self._crear_usuario('carlos.torres', 'carlos@test.com', 'Asesor2024!')
        asesor2 = self._crear_usuario('maria.lopez', 'maria@test.com', 'Asesor2024!')
        supervisor = self._crear_usuario('juan.perez', 'juan@test.com', 'Super2024!')

        # ── 2. PERFILES ───────────────────────────────────────────────────────────
        Perfil.objects.get_or_create(user=admin)
        Perfil.objects.get_or_create(user=asesor1, defaults={'ruta_asignada': 'RUTA-01'})
        Perfil.objects.get_or_create(user=asesor2, defaults={'ruta_asignada': 'RUTA-02'})
        Perfil.objects.get_or_create(user=supervisor, defaults={'ruta_asignada': 'RUTA-01'})

        # ── 3. PERMISOS ───────────────────────────────────────────────────────────
        perm_admin, _ = Permisos.objects.get_or_create(permiso='admin_comisiones', defaults={'active': True})
        perm_asesor, _ = Permisos.objects.get_or_create(permiso='asesor_comisiones', defaults={'active': True})
        perm_supervisor, _ = Permisos.objects.get_or_create(permiso='supervisor_comisiones', defaults={'active': True})

        Permisos_usuarios.objects.get_or_create(user=admin, permiso=perm_admin, defaults={'tiene_permiso': True})
        Permisos_usuarios.objects.get_or_create(user=asesor1, permiso=perm_asesor, defaults={'tiene_permiso': True})
        Permisos_usuarios.objects.get_or_create(user=asesor2, permiso=perm_asesor, defaults={'tiene_permiso': True})
        Permisos_usuarios.objects.get_or_create(user=supervisor, permiso=perm_supervisor, defaults={'tiene_permiso': True})
        Permisos_usuarios.objects.get_or_create(user=supervisor, permiso=perm_asesor, defaults={'tiene_permiso': True})

        # ── 4. RUTAS ──────────────────────────────────────────────────────────────
        RutaAsignada.objects.get_or_create(user=asesor1, ruta='RUTA-01')
        RutaAsignada.objects.get_or_create(user=asesor2, ruta='RUTA-02')
        RutaAsignada.objects.get_or_create(user=supervisor, ruta='RUTA-01')

        # ── 5. CONFIGURACIÓN ──────────────────────────────────────────────────────
        hoy = date.today()
        Configuracion.objects.update_or_create(
            clave='FECHA_CORTE_DIA',
            defaults={'valor': str(hoy.day)}
        )
        self.stdout.write(f'  Fecha de corte configurada al día {hoy.day} (hoy)')

        # ── 6. CARGAS DE COMISIONES ───────────────────────────────────────────────
        mes_actual = hoy.replace(day=1)
        mes_anterior = (hoy.replace(day=1) - timedelta(days=1)).replace(day=1)

        carga1, _ = ComisionCarga.objects.get_or_create(
            file_name='comisiones_marzo_2026.xlsx',
            defaults={
                'created_by': admin,
                'mes_detectado': mes_anterior,
                'estado': 'success',
                'registros_creados': 6,
                'detalle': 'Carga de prueba mes anterior',
            }
        )
        carga2, _ = ComisionCarga.objects.get_or_create(
            file_name='comisiones_abril_2026.xlsx',
            defaults={
                'created_by': admin,
                'mes_detectado': mes_actual,
                'estado': 'success',
                'registros_creados': 8,
                'detalle': 'Carga de prueba mes actual',
            }
        )

        # ── 7. PAGO EXISTENTE (para comisiones Consolidadas) ──────────────────────
        pago, _ = PagoComision.objects.get_or_create(
            idpos='PDV-001',
            defaults={
                'punto_de_venta': 'PUNTO DE VENTA UNO',
                'creado_por': asesor1,
                'monto_total_pagado': Decimal('150000.00'),
                'monto_comisiones': Decimal('150000.00'),
                'metodos_pago': {'Efectivo': 150000},
                'observacion': 'Pago de prueba generado automáticamente',
            }
        )

        # ── 8. COMISIONES ─────────────────────────────────────────────────────────
        comisiones = [
            # PDV-001 — asesor1 — Pendiente (puede pagar hoy)
            dict(asesor=asesor1, identificador='CARLOS TORRES', iccid='89570130000000001', idpos='PDV-001',
                 pdv='PUNTO DE VENTA UNO', ruta='RUTA-01', estado='Pendiente', monto=50000, carga=carga2,
                 mes_pago=mes_actual, mes_liq=mes_actual),
            dict(asesor=asesor1, identificador='CARLOS TORRES', iccid='89570130000000002', idpos='PDV-001',
                 pdv='PUNTO DE VENTA UNO', ruta='RUTA-01', estado='Pendiente', monto=75000, carga=carga2,
                 mes_pago=mes_actual, mes_liq=mes_actual),

            # PDV-002 — asesor1 — Acumulada (puede pagar)
            dict(asesor=asesor1, identificador='CARLOS TORRES', iccid='89570130000000003', idpos='PDV-002',
                 pdv='PUNTO DE VENTA DOS', ruta='RUTA-01', estado='Acumulada', monto=30000, carga=carga1,
                 mes_pago=mes_anterior, mes_liq=mes_actual),
            dict(asesor=asesor1, identificador='CARLOS TORRES', iccid='89570130000000004', idpos='PDV-002',
                 pdv='PUNTO DE VENTA DOS', ruta='RUTA-01', estado='Acumulada', monto=45000, carga=carga2,
                 mes_pago=mes_actual, mes_liq=mes_actual),

            # PDV-001 — asesor1 — Consolidada (ya pagada, vinculada al pago)
            dict(asesor=asesor1, identificador='CARLOS TORRES', iccid='89570130000000005', idpos='PDV-001',
                 pdv='PUNTO DE VENTA UNO', ruta='RUTA-01', estado='Consolidada', monto=150000, carga=carga1,
                 mes_pago=mes_anterior, mes_liq=mes_anterior, pagos=pago),

            # PDV-003 — asesor2 — Pendiente
            dict(asesor=asesor2, identificador='MARIA LOPEZ', iccid='89570130000000006', idpos='PDV-003',
                 pdv='PUNTO DE VENTA TRES', ruta='RUTA-02', estado='Pendiente', monto=60000, carga=carga2,
                 mes_pago=mes_actual, mes_liq=mes_actual),
            dict(asesor=asesor2, identificador='MARIA LOPEZ', iccid='89570130000000007', idpos='PDV-003',
                 pdv='PUNTO DE VENTA TRES', ruta='RUTA-02', estado='Pendiente', monto=40000, carga=carga2,
                 mes_pago=mes_actual, mes_liq=mes_actual),

            # PDV-004 — asesor2 — Vencida (no se puede pagar)
            dict(asesor=asesor2, identificador='MARIA LOPEZ', iccid='89570130000000008', idpos='PDV-004',
                 pdv='PUNTO DE VENTA CUATRO', ruta='RUTA-02', estado='Vencida', monto=25000, carga=carga1,
                 mes_pago=mes_anterior, mes_liq=mes_anterior),
        ]

        for c in comisiones:
            Comision.objects.get_or_create(
                iccid=c['iccid'],
                defaults={
                    'carga': c['carga'],
                    'asesor': c['asesor'],
                    'asesor_identificador': c['identificador'],
                    'idpos': c['idpos'],
                    'punto_de_venta': c['pdv'],
                    'ruta': c['ruta'],
                    'estado': c['estado'],
                    'comision_final': Decimal(str(c['monto'])),
                    'mes_pago': c['mes_pago'],
                    'mes_liquidacion': c['mes_liq'],
                    'pagos': c.get('pagos'),
                    'producto': 'PREPAGO 10GB',
                    'distribuidor': 'TEAM COMUNICACIONES',
                }
            )

        self.stdout.write(self.style.SUCCESS('\n✓ Datos de prueba creados exitosamente.\n'))
        self.stdout.write('  USUARIOS (usuario / contraseña):')
        self.stdout.write('    admin          / Admin2024!   → rol: admin')
        self.stdout.write('    carlos.torres  / Asesor2024!  → rol: asesor  (RUTA-01)')
        self.stdout.write('    maria.lopez    / Asesor2024!  → rol: asesor  (RUTA-02)')
        self.stdout.write('    juan.perez     / Super2024!   → rol: supervisor')
        self.stdout.write('\n  COMISIONES creadas:')
        self.stdout.write('    PDV-001 (carlos) → 2 Pendientes + 1 Consolidada')
        self.stdout.write('    PDV-002 (carlos) → 2 Acumuladas')
        self.stdout.write('    PDV-003 (maria)  → 2 Pendientes')
        self.stdout.write('    PDV-004 (maria)  → 1 Vencida (no se puede pagar)')
        self.stdout.write(f'\n  Fecha de corte: día {hoy.day} (HOY → disparar vencimiento al guardar)\n')

    def _crear_usuario(self, username, email, password):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'first_name': username.split('.')[0].capitalize()}
        )
        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(f'  Usuario creado: {username}')
        else:
            self.stdout.write(f'  Usuario ya existe: {username}')
        return user
