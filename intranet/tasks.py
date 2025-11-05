import pandas as pd
import numpy as np
from celery import shared_task
from django.db import transaction
from django.contrib.auth.models import User
from django.db.models import Max
from django.core.mail import send_mail
from django.conf import settings
from . import models
import os
import time
import logging
import locale
from datetime import date, datetime, time as dt_time
from dateutil.relativedelta import relativedelta
from calendar import monthrange
from django.utils import timezone

# Obtenemos un logger de Celery para ver los mensajes en la consola del worker
logger = logging.getLogger(__name__)


# --- FUNCIÓN HELPER PARA ENVIAR CORREOS (SIN CAMBIOS) ---
def send_completion_email(user_id, status, context_message):
    """Función helper para construir y enviar el email de notificación."""
    try:
        user = User.objects.get(id=user_id)
        if not user.email:
            logger.warning(f"El usuario {user.username} (ID: {user_id}) no tiene un email configurado. No se puede notificar.")
            return

        if status == 'success':
            subject = '✅ Proceso de Carga de Comisiones Completado'
            body = f"""
Hola {user.first_name or user.username},

Te informamos que el archivo de comisiones ha sido procesado exitosamente.

Resumen:
{context_message}

Puedes continuar trabajando en la plataforma.

Saludos,
El equipo de Tu App
            """
        else: # 'error'
            subject = '❌ Error en el Proceso de Carga de Comisiones'
            body = f"""
Hola {user.first_name or user.username},

Lamentamos informarte que ocurrió un error durante el procesamiento de tu archivo de comisiones.

Detalle del error:
{context_message}

Por favor, revisa el archivo o contacta a soporte si el problema persiste.

Saludos,
El equipo de Tu App
            """
        
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL, # Remitente
            [user.email],                  # Destinatario(s)
            fail_silently=False,
        )
        logger.info(f"Email de notificación enviado a {user.email} para el usuario ID {user_id}.")

    except User.DoesNotExist:
        logger.error(f"Se intentó enviar un email a un usuario inexistente con ID: {user_id}")
    except Exception as e:
        logger.error(f"Falló el envío del email de notificación para el usuario ID {user_id}: {e}")


# --- FUNCIÓN HELPER PARA OBTENER FECHA DE CORTE (SIN CAMBIOS) ---
def _get_fecha_corte_helper():
    """Obtiene el día de corte desde el modelo Configuracion. Si no existe, devuelve 1."""
    try:
        config = models.Configuracion.objects.get(clave='dia_corte')
        dia = int(config.valor)
        if 1 <= dia <= 31:
            return dia
        return 1
    except (models.Configuracion.DoesNotExist, ValueError):
        logger.warning("No se encontró una configuración válida para 'dia_corte'. Usando el valor predeterminado: 1.")
        return 1


# ---- INICIO: FUNCIÓN HELPER PARA VENCER POR INACTIVIDAD (CORREGIDA Y MEJORADA) ----
def _vencer_por_inactividad_helper(mes_de_referencia):
    """
    Lógica para vencer comisiones de PDV inactivos durante el ciclo de pago anterior.
    DEVUELVE: Una tupla (mensaje_string, lista_pdv_activos).
    """
    dia_corte = _get_fecha_corte_helper()
    
    # --- Lógica de cálculo de período ---
    try:
        if dia_corte == 1:
            inicio_periodo = mes_de_referencia.replace(day=1)
            last_day = monthrange(mes_de_referencia.year, mes_de_referencia.month)[1]
            fin_periodo = mes_de_referencia.replace(day=last_day)
        else:
            dia_fin_periodo = min(dia_corte - 1, monthrange(mes_de_referencia.year, mes_de_referencia.month)[1])
            fin_periodo = mes_de_referencia.replace(day=dia_fin_periodo)
            mes_anterior = mes_de_referencia - relativedelta(months=1)
            dia_inicio_periodo = min(dia_corte, monthrange(mes_anterior.year, mes_anterior.month)[1])
            inicio_periodo = mes_anterior.replace(day=dia_inicio_periodo)
    except ValueError:
        error_msg = "Error al calcular las fechas del período. Revisa el día de corte."
        logger.error(error_msg)
        return (error_msg, []) # Devolver tupla en caso de error

    inicio_dt = timezone.make_aware(datetime.combine(inicio_periodo, dt_time.min))
    fin_dt = timezone.make_aware(datetime.combine(fin_periodo, dt_time.max))

    periodo_str = f"{inicio_dt.strftime('%Y-%m-%d')} al {fin_dt.strftime('%Y-%m-%d')}"
    logger.info(f"HELPER: Iniciando vencimiento por inactividad para el período: {periodo_str}")

    try:
        with transaction.atomic():
            # 1. Encontrar PDV que SÍ tuvieron pagos en el período (PDV ACTIVOS)
            pdv_con_pagos = models.PagoComision.objects.filter(
                fecha_pago__range=[inicio_dt, fin_dt]
            ).values_list('idpos', flat=True).distinct()
            pdv_activos_set = set(pdv_con_pagos)
            logger.info(f"HELPER: Se encontraron {len(pdv_activos_set)} PDV ACTIVOS en el período.")

            # 2. Encontrar TODOS los PDV que tienen comisiones pendientes o acumuladas
            pdv_con_comisiones_pendientes = models.Comision.objects.filter(
                estado__in=['Pendiente', 'Acumulada']
            ).values_list('idpos', flat=True).distinct()
            pdv_con_comisiones_pendientes_set = set(pdv_con_comisiones_pendientes)
            
            # 3. Identificar PDV inactivos (tienen deuda pero NO hicieron pagos)
            pdv_inactivos = list(pdv_con_comisiones_pendientes_set - pdv_activos_set)

            if not pdv_inactivos:
                mensaje = "HELPER: No se encontraron PDV inactivos para el período."
                logger.info(mensaje)
                # Devolvemos la lista de activos que ya calculamos
                return (mensaje, list(pdv_activos_set))

            # 4. Actualizar las comisiones de los PDV inactivos
            num_actualizadas = models.Comision.objects.filter(
                idpos__in=pdv_inactivos,
                estado__in=['Pendiente', 'Acumulada']
            ).update(estado='Vencida', producto='Vencida por no visita')

            mensaje_final = f"HELPER: Se actualizaron {num_actualizadas} comisiones de {len(pdv_inactivos)} PDV a 'Vencida por no visita'."
            logger.info(mensaje_final)
            # Devolvemos el mensaje Y la lista de PDV activos para el siguiente paso
            return (mensaje_final, list(pdv_activos_set))

    except Exception as e:
        mensaje_error = f"HELPER: Error al vencer comisiones por inactividad: {e}"
        logger.error(mensaje_error, exc_info=True)
        return (mensaje_error, []) # Devolver tupla en caso de error
# ---- FIN: FUNCIÓN HELPER CORREGIDA Y MEJORADA ----


@shared_task
def procesar_archivo_comisiones(file_path, user_id):
    """
    Tarea de Celery para procesar un archivo Excel de comisiones y notificar por email.
    """
    try:
        # Configuración de locale y lectura de Excel
        try:
            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
        except locale.Error:
            locale.setlocale(locale.LC_TIME, 'Spanish_Spain.1252')
        sheets_dict = pd.read_excel(file_path, sheet_name=None, dtype=str)
        
        # --- LÓGICA DE VENCIMIENTO CON ORDEN Y FILTRO CORREGIDOS ---
        first_sheet_name = next(iter(sheets_dict))
        df_for_month_check = sheets_dict[first_sheet_name]
        
        meses_en_archivo = pd.to_datetime(df_for_month_check['MES PAGO'], format='%B %Y', errors='coerce').dt.to_period('M')
        mes_nuevo_periodo = meses_en_archivo.dropna().unique()[0]
        mes_nuevo_fecha = mes_nuevo_periodo.to_timestamp().date()
        logger.info(f"Mes detectado en el archivo: {mes_nuevo_periodo}")

        ultimo_mes_registrado = models.Comision.objects.aggregate(max_mes=Max('mes_pago'))['max_mes']

        if ultimo_mes_registrado:
            logger.info(f"Último mes de PAGO en la BD: {ultimo_mes_registrado.strftime('%Y-%m')}")
            
            if mes_nuevo_fecha > ultimo_mes_registrado:
                # PASO 1: Vencer por inactividad PRIMERO. Capturamos ambos resultados.
                logger.info("El mes del archivo es nuevo. Ejecutando lógica de vencimiento...")
                
                resultado_inactividad, pdv_activos_del_ciclo = _vencer_por_inactividad_helper(ultimo_mes_registrado)
                logger.info(f"Resultado del vencimiento por inactividad: {resultado_inactividad}")
                
                # PASO 2: Vencer por cambio de mes DESPUÉS, USANDO LA LISTA DE PDV ACTIVOS.
                logger.warning(f"Venciendo comisiones restantes de PDV ACTIVOS por cambio de mes.")
                
                if pdv_activos_del_ciclo: # Solo ejecutar si hubo PDV activos
                    with transaction.atomic():
                        # AÑADIMOS EL FILTRO 'idpos__in'
                        num_actualizadas = models.Comision.objects.filter(
                            estado__in=['Pendiente', 'Acumulada'],
                            idpos__in=pdv_activos_del_ciclo
                        ).update(
                            estado='Vencida', 
                            producto='Vencida por cambio de mes'
                        )
                    logger.info(f"Se actualizaron {num_actualizadas} comisiones de PDV activos a 'Vencida por cambio de mes'.")
                else:
                    logger.info("No hubo PDV activos en el ciclo anterior para vencer por cambio de mes.")

        else:
            logger.info("No hay comisiones previas. Se omite la validación de vencimiento.")
        # --- FIN: LÓGICA DE VENCIMIENTO CORREGIDA ---

        # El resto del procesamiento del archivo continúa
        all_asesores_excel = set()
        for sheet_name, df in sheets_dict.items():
            if 'PRIM_LLAMADA_ACTIVACION' in df.columns:
                numeros_de_fecha = pd.to_numeric(df['PRIM_LLAMADA_ACTIVACION'], errors='coerce')
                s_dates = pd.to_datetime(numeros_de_fecha, origin='1899-12-30', unit='D', errors='coerce')
                df['PRIM_LLAMADA_ACTIVACION'] = s_dates.dt.date.replace({pd.NaT: None})
            if 'MES LIQUIDACIÓN' in df.columns:
                s_dates = pd.to_datetime(df['MES LIQUIDACIÓN'], format='%B %Y', errors='coerce')
                df['MES LIQUIDACIÓN'] = s_dates.dt.date.replace({pd.NaT: None})
            if 'MES PAGO' in df.columns:
                s_dates = pd.to_datetime(df['MES PAGO'], format='%B %Y', errors='coerce')
                df['MES PAGO'] = s_dates.dt.date.replace({pd.NaT: None})
            if 'COMISION FINAL' in df.columns:
                numeric_series = pd.to_numeric(df['COMISION FINAL'], errors='coerce')
                df['COMISION FINAL'] = numeric_series.apply(lambda x: str(x) if pd.notna(x) else None)
            if 'ASESOR' in df.columns:
                all_asesores_excel.update(df['ASESOR'].dropna().astype(str).unique())
        
        usuarios_map = {user.username: user for user in User.objects.filter(username__in=all_asesores_excel)}
        comisiones_para_crear = []
        
        for sheet_name, df_sheet in sheets_dict.items():
            df_sheet = df_sheet.replace({np.nan: None, pd.NaT: None})
            for index, row in df_sheet.iterrows():
                iccid = str(row.get('ICCID') or '').strip()
                producto = str(row.get('PRODUCTO') or '').strip()
                idpos = str(row.get('IDPOS') or '').strip()
                punto_de_venta = str(row.get('PUNTO DE VENTA') or '').strip()
                if not iccid and not producto and not idpos and not punto_de_venta:
                    continue
                is_special_case = not iccid and not producto
                if is_special_case:
                    if not idpos: continue
                else:
                    if not iccid or not producto: continue
                pago_valor = str(row.get('PAGO') or '').strip().lower()
                estado_final = 'Pendiente'
                if is_special_case or 'acumulado' in pago_valor:
                    estado_final = 'Acumulada'
                asesor_identificador = str(row.get('ASESOR') or '').strip()
                usuario_encontrado = usuarios_map.get(asesor_identificador)
                comisiones_para_crear.append(
                    models.Comision(
                        asesor_identificador=asesor_identificador, asesor=usuario_encontrado, 
                        iccid=iccid, distribuidor=row.get('DISTRIBUIDOR'), producto=producto,
                        co_id=row.get('CO_ID'), prim_llamada_activacion=row.get('PRIM_LLAMADA_ACTIVACION'),
                        min=str(row.get('MIN') or ''), idpos=idpos, punto_de_venta=punto_de_venta,
                        ruta=row.get('RUTA'), comision_final=row.get('COMISION FINAL'),
                        pago=pago_valor, mes_liquidacion=row.get('MES LIQUIDACIÓN'),
                        mes_pago=row.get('MES PAGO'), estado=estado_final,
                    )
                )

        if comisiones_para_crear:
            with transaction.atomic():
                models.Comision.objects.bulk_create(comisiones_para_crear, batch_size=5000)
        
        registros_creados_total = len(comisiones_para_crear)
        logger.info(f"Proceso completado. Se crearon {registros_creados_total} nuevos registros.")
        mensaje_exito = f"Se crearon {registros_creados_total} nuevos registros de comisión."
        send_completion_email(user_id, 'success', mensaje_exito)
        return f"Proceso completado. Se crearon {registros_creados_total} nuevos registros."

    except Exception as e:
        logger.error(f"La tarea principal falló debido a: {e}", exc_info=True)
        mensaje_error = str(e)
        send_completion_email(user_id, 'error', mensaje_error)
        return f"El proceso falló: {str(e)}"
    
    finally:
        # Limpieza del archivo
        locale.setlocale(locale.LC_TIME, '')
        if os.path.exists(file_path):
            intentos = 5
            for i in range(intentos):
                try:
                    os.remove(file_path)
                    logger.info(f"Archivo temporal {file_path} eliminado con éxito.")
                    break
                except PermissionError:
                    if i < intentos - 1:
                        logger.warning(f"Intento {i+1}/{intentos} fallido al borrar {file_path}. Reintentando en 2 segundos...")
                        time.sleep(2)
                    else:
                        logger.error(f"No se pudo borrar el archivo temporal {file_path} después de {intentos} intentos.")


# ---- TAREA PROGRAMADA (SIN CAMBIOS, AHORA USA EL HELPER CORREGIDO) ----
@shared_task
def vencer_comisiones_por_inactividad():
    """
    Tarea programada que se ejecuta el día de corte para evaluar el ciclo anterior.
    """
    today = date.today()
    dia_corte = _get_fecha_corte_helper()

    if today.day == dia_corte:
        logger.info(f"Hoy es día {dia_corte}, el día de corte. Ejecutando vencimiento por inactividad.")
        # El mes de referencia para el ciclo que acaba de terminar es el mes actual.
        # El helper calculará el período correcto (p.ej., del día de corte del mes pasado a ayer)
        mes_de_referencia = today.replace(day=1) 
        
        # La tarea programada solo necesita ejecutar el helper, no necesita la lista de pdv activos
        mensaje_resultado, _ = _vencer_por_inactividad_helper(mes_de_referencia)
        return mensaje_resultado
    else:
        mensaje = f"Hoy es día {today.day}. La tarea solo se ejecuta el día {dia_corte} de cada mes. No se hace nada."
        logger.info(mensaje)
        return mensaje
