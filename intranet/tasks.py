import pandas as pd
import numpy as np
from celery import shared_task
from django.db import transaction
from django.contrib.auth.models import User
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
    Versión final con todas las conversiones de datos y reglas de negocio.
    """
    xls = None
    try:
        # 1. Configurar el idioma para que pandas entienda meses en español
        try:
            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8') # Para Linux/Mac
        except locale.Error:
            locale.setlocale(locale.LC_TIME, 'Spanish_Spain.1252') # Para Windows

        # 2. Leer todas las hojas del Excel, forzando todo a texto para máxima seguridad.
        sheets_dict = pd.read_excel(file_path, sheet_name=None, dtype=str)

        all_asesores_excel = set()
        
        # 3. Pre-procesamiento de datos en cada hoja
        for sheet_name, df in sheets_dict.items():
            # a) Convierte la fecha serial de Excel (ej. '45704') a fecha
            if 'PRIM_LLAMADA_ACTIVACION' in df.columns:
                numeros_de_fecha = pd.to_numeric(df['PRIM_LLAMADA_ACTIVACION'], errors='coerce')
                s_dates = pd.to_datetime(numeros_de_fecha, origin='1899-12-30', unit='D', errors='coerce')
                df['PRIM_LLAMADA_ACTIVACION'] = s_dates.dt.date.replace({pd.NaT: None})

            # b) Convierte el texto "Mes Año" (ej. "Marzo 2025") a fecha
            if 'MES LIQUIDACIÓN' in df.columns:
                s_dates = pd.to_datetime(df['MES LIQUIDACIÓN'], format='%B %Y', errors='coerce')
                df['MES LIQUIDACIÓN'] = s_dates.dt.date.replace({pd.NaT: None})
            if 'MES PAGO' in df.columns:
                s_dates = pd.to_datetime(df['MES PAGO'], format='%B %Y', errors='coerce')
                df['MES PAGO'] = s_dates.dt.date.replace({pd.NaT: None})

            # c) Convierte la comisión a número y luego a texto para compatibilidad con DecimalField
            if 'COMISION FINAL' in df.columns:
                numeric_series = pd.to_numeric(df['COMISION FINAL'], errors='coerce')
                df['COMISION FINAL'] = numeric_series.apply(lambda x: str(x) if pd.notna(x) else None)

            # d) Recolectar asesores para una única consulta a la BD
            if 'ASESOR' in df.columns:
                all_asesores_excel.update(df['ASESOR'].dropna().astype(str).unique())
        
        # 4. Optimización de Consulta a la Base de Datos
        usuarios_map = {user.username: user for user in User.objects.filter(username__in=all_asesores_excel)}
        
        comisiones_para_crear = []
        
        # 5. Construcción de los objetos a guardar con la lógica de negocio
        for sheet_name, df_sheet in sheets_dict.items():
            df_sheet = df_sheet.replace({np.nan: None, pd.NaT: None})
            
            for index, row in df_sheet.iterrows():
                # Obtención de datos de la fila
                iccid = str(row.get('ICCID') or '').strip()
                producto = str(row.get('PRODUCTO') or '').strip()
                idpos = str(row.get('IDPOS') or '').strip()
                punto_de_venta = str(row.get('PUNTO DE VENTA') or '').strip()

                # Validación de datos mínimos (ignorar filas completamente vacías o sin sentido)
                if not iccid and not producto and not idpos and not punto_de_venta:
                    continue

                # Lógica para casos especiales de Acumuladas
                is_special_case = not iccid and not producto
                
                if is_special_case:
                    if not idpos:
                        continue # Si es caso especial, debe tener al menos IDPOS
                else:
                    if not iccid or not producto: # Si es caso normal, debe tener ICCID y producto
                        continue
                
                # --- LÓGICA DE ESTADO (MODIFICADA) ---
                pago_valor = str(row.get('PAGO') or '').strip().lower()
                estado_final = 'Pendiente'  # Por defecto, todos son 'Pendiente'

                # Únicamente revisamos si se debe cambiar a 'Acumulada'
                if is_special_case or 'acumulado' in pago_valor:
                    estado_final = 'Acumulada'
                # --- FIN DE LA MODIFICACIÓN ---

                # Construcción del objeto
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
        return f"Proceso completado. Se crearon {registros_creados_total} nuevos registros."

    except Exception as e:
        logger.error(f"La tarea principal falló debido a: {e}", exc_info=True)
        return f"El proceso falló: {str(e)}"
    
    finally:
        # 7. Limpieza Segura del Archivo
        locale.setlocale(locale.LC_TIME, '') # Reseteamos el locale a su valor por defecto
        if xls:
            xls.close()
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