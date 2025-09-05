# en tu_app/services.py
import pandas as pd
from .models import ReporteDetalleVenta
from django.db import transaction

def process_sales_report_file(uploaded_file):
    """
    Lee un archivo Excel, procesa la hoja 'DETALLE VENTAS' y guarda los datos en la BD.
    Devuelve un diccionario con el resumen del proceso.
    """
    try:
        df = pd.read_excel(uploaded_file, sheet_name='DETALLE VENTAS')

        column_mapping = {
            'Fecha': 'fecha',
            'Imei': 'imei',
            'Modelo Equipo': 'modelo_equipo',
            'Sucursal': 'sucursal',
            'Tipo producto': 'tipo_producto',
            'Tipo  de venta': 'tipo_venta_original', 
            'Tipo de venta': 'tipo_venta_original',
            'Asesor': 'asesor',
            'Canal': 'canal',
            'Tiket de venta': 'tiket_venta',
            # --- SECCIÓN A REVISAR ---
            # Añade aquí otras posibles variaciones del nombre de la columna de costo
            'Costo del equipo': 'costo_equipo',
            'Costo Equipo': 'costo_equipo',
            'costo del equipo': 'costo_equipo',
            # --- FIN SECCIÓN ---
            'Incentivo': 'incentivo'
        }
        
        df.rename(columns=lambda c: column_mapping.get(str(c).strip(), str(c).strip()), inplace=True)
        
        # --- NUEVO: Limpieza y Estandarización de Fechas ---
        if 'fecha' in df.columns:
            # 1. Convierte la columna a formato de fecha. Pandas es inteligente y reconoce muchos formatos.
            #    Los valores que no pueda convertir se volverán NaT (Not a Time).
            df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
            
            # 2. Elimina las filas donde la fecha no se pudo convertir. Es crucial para la integridad de los datos.
            df.dropna(subset=['fecha'], inplace=True)
        else:
            # Si no hay columna 'fecha', es un error y no podemos continuar.
            raise ValueError("El archivo Excel no contiene la columna 'Fecha', que es obligatoria.")
        
        # --- Limpieza de Datos Numéricos ---
        numeric_columns = ['costo_equipo', 'incentivo']
        for col in numeric_columns:
            if col not in df.columns:
                df[col] = 0
            df[col] = pd.to_numeric(df[col], errors='coerce')
            df[col] = df[col].fillna(0)

        # --- Limpieza de IMEI ---
        df.dropna(subset=['imei'], inplace=True)
        df['imei'] = df['imei'].astype(str).str.strip()
        
        registros_a_crear = []
        imeis_existentes = set(ReporteDetalleVenta.objects.filter(imei__in=df['imei'].tolist()).values_list('imei', flat=True))

        for _, row in df.iterrows():
            row_dict = row.to_dict()

            if row_dict.get('imei') in imeis_existentes:
                continue

            tipo_venta = str(row_dict.get('tipo_venta_original', '')).lower()
            clasificacion = 'Otro'
            if 'compra' in tipo_venta or 'activacion pos' in tipo_venta:
                clasificacion = 'Sell In'
            elif 'venta' in tipo_venta:
                clasificacion = 'Sell Out'
            elif 'inventario' in tipo_venta:
                clasificacion = 'Inventario'

            tipo_vendedor = None
            if clasificacion == 'Sell Out':
                pass

            registros_a_crear.append(
                ReporteDetalleVenta(
                    fecha=row_dict.get('fecha'),
                    imei=row_dict.get('imei'),
                    modelo_equipo=row_dict.get('modelo_equipo'),
                    sucursal=row_dict.get('sucursal'),
                    tipo_producto=row_dict.get('tipo_producto'),
                    tipo_venta_original=row_dict.get('tipo_venta_original'),
                    asesor=row_dict.get('asesor'),
                    canal=row_dict.get('canal'),
                    tiket_venta=row_dict.get('tiket_venta'),
                    costo_equipo=row_dict.get('costo_equipo'),
                    incentivo=row_dict.get('incentivo'),
                    clasificacion_venta=clasificacion,
                    tipo_vendedor=tipo_vendedor,
                )
            )

        with transaction.atomic():
            ReporteDetalleVenta.objects.bulk_create(registros_a_crear, ignore_conflicts=True)
            
        return {"status": "success", "creados": len(registros_a_crear), "existentes": len(df) - len(registros_a_crear)}

    except Exception as e:
        if 'Worksheet named' in str(e):
             return {"status": "error", "message": "El archivo Excel no contiene la hoja 'DETALLE VENTAS'."}
        if isinstance(e, ValueError): # Captura el error de la columna 'Fecha' faltante
             return {"status": "error", "message": str(e)}
        if 'ValidationError' in str(type(e)):
             return {"status": "error", "message": f"Error de validación de datos: {str(e)}"}
        return {"status": "error", "message": f"Error procesando el archivo: {str(e)}"}