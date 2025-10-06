# comisiones/tasks.py

import pandas as pd
import numpy as np
from celery import shared_task
from django.db import transaction
from django.contrib.auth.models import User
from django.db.models import Max  # <-- Importante añadir Max
from . import models
import os
import time
import logging
import locale

# Obtenemos un logger de Celery para ver los mensajes en la consola del worker
logger = logging.getLogger(__name__)

@shared_task
def procesar_archivo_comisiones(file_path, user_id):
    """
    Tarea de Celery para procesar un archivo Excel de comisiones.
    Incluye:
    - Vencimiento de comisiones antiguas si se carga un mes más reciente.
    - Procesamiento detallado de datos del archivo.
    - Creación masiva de nuevos registros de comisión.
    """
    try:
        # 1. Configurar el idioma para que pandas entienda meses en español
        try:
            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8') # Para Linux/Mac
        except locale.Error:
            locale.setlocale(locale.LC_TIME, 'Spanish_Spain.1252') # Para Windows

        # 2. Leer el archivo Excel, forzando todo a texto.
        sheets_dict = pd.read_excel(file_path, sheet_name=None, dtype=str)
        
        # --- INICIO: LÓGICA DE VENCIMIENTO DE COMISIONES ANTIGUAS ---
        
        # a) Obtener el mes del archivo. Asumimos que la vista ya validó que solo hay un mes.
        #    Tomamos el primer DataFrame para esta comprobación.
        first_sheet_name = next(iter(sheets_dict))
        df_for_month_check = sheets_dict[first_sheet_name]
        
        meses_en_archivo = pd.to_datetime(df_for_month_check['MES LIQUIDACIÓN'], format='%B %Y', errors='coerce').dt.to_period('M')
        mes_nuevo_periodo = meses_en_archivo.dropna().unique()[0]
        mes_nuevo_fecha = mes_nuevo_periodo.to_timestamp().date()
        logger.info(f"Mes detectado en el archivo para la validación de vencimiento: {mes_nuevo_periodo}")

        # b) Obtener el último mes de liquidación registrado en la base de datos.
        ultimo_mes_registrado = models.Comision.objects.aggregate(max_mes=Max('mes_liquidacion'))['max_mes']

        if ultimo_mes_registrado:
            logger.info(f"Último mes de liquidación en la BD: {ultimo_mes_registrado.strftime('%Y-%m')}")
            
            # c) Comparar y actualizar si el nuevo mes es más reciente.
            if mes_nuevo_fecha > ultimo_mes_registrado:
                logger.warning(f"El mes del archivo ({mes_nuevo_periodo}) es más reciente. Venciendo comisiones antiguas.")
                estados_a_vencer = ['Pendiente', 'Acumulada']
                
                with transaction.atomic():
                    comisiones_a_actualizar = models.Comision.objects.filter(estado__in=estados_a_vencer)
                    num_actualizadas = comisiones_a_actualizar.update(estado='Vencida')
                
                if num_actualizadas > 0:
                    logger.info(f"¡ÉXITO! Se actualizaron {num_actualizadas} comisiones a estado 'Vencida'.")
                else:
                    logger.info("No se encontraron comisiones en estado 'Pendiente' o 'Acumulada' para actualizar.")
        else:
            logger.info("No hay comisiones previas en la base de datos. Se omite la validación de vencimiento.")

        # --- FIN: LÓGICA DE VENCIMIENTO ---

        # 3. Pre-procesamiento de datos en cada hoja (tu lógica original)
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
        
        # 4. Optimización de Consulta a la Base de Datos
        usuarios_map = {user.username: user for user in User.objects.filter(username__in=all_asesores_excel)}
        
        comisiones_para_crear = []
        
        # 5. Construcción de los objetos a guardar
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
                        asesor_identificador=asesor_identificador,
                        asesor=usuario_encontrado, 
                        iccid=iccid,
                        distribuidor=row.get('DISTRIBUIDOR'),
                        producto=producto,
                        co_id=row.get('CO_ID'),
                        prim_llamada_activacion=row.get('PRIM_LLAMADA_ACTIVACION'),
                        min=str(row.get('MIN') or ''),
                        idpos=idpos,
                        punto_de_venta=punto_de_venta,
                        ruta=row.get('RUTA'),
                        comision_final=row.get('COMISION FINAL'),
                        pago=pago_valor,
                        mes_liquidacion=row.get('MES LIQUIDACIÓN'),
                        mes_pago=row.get('MES PAGO'),
                        estado=estado_final,
                    )
                )

        # 6. Guardado Masivo en la Base de Datos
        if comisiones_para_crear:
            with transaction.atomic():
                models.Comision.objects.bulk_create(comisiones_para_crear, batch_size=5000)
        
        registros_creados_total = len(comisiones_para_crear)
        logger.info(f"Proceso completado. Se crearon {registros_creados_total} nuevos registros.")
        return f"Proceso completado. Se crearon {registros_creados_total} nuevos registros."

    except Exception as e:
        logger.error(f"La tarea principal falló debido a: {e}", exc_info=True)
        return f"El proceso falló: {str(e)}"
    
    finally:
        # 7. Limpieza Segura del Archivo (tu lógica original)
        locale.setlocale(locale.LC_TIME, '') # Reseteamos el locale
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