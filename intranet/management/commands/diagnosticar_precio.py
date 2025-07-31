from django.core.management.base import BaseCommand
from decimal import Decimal
import re
import ast
from collections import defaultdict
from intranet.models import Traducciones, Permisos_precio, Formula, Lista_precio, Variables_prices

def motor_de_evaluacion_diagnostico(formula_string, price_list_id, context, mapa_variables, cache_variables):
    cache_key = (formula_string, price_list_id)
    if cache_key in cache_variables:
        return cache_variables[cache_key]

    if formula_string is None:
        return Decimal('0')

    variables_en_formula = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', formula_string)
    contexto_local = context.copy()

    for var_name in set(variables_en_formula):
        if var_name in contexto_local:
            continue
        
        variables_especificas = mapa_variables.get(price_list_id, {})
        variable_obj = variables_especificas.get(var_name)

        if not variable_obj:
            variables_globales = mapa_variables.get(1, {})
            variable_obj = variables_globales.get(var_name)

        if variable_obj:
            valor_variable = motor_de_evaluacion_diagnostico(variable_obj.formula, price_list_id, context, mapa_variables, cache_variables)
            contexto_local[var_name] = valor_variable

    try:
        resultado = Decimal(eval(formula_string, {"__builtins__": None}, contexto_local))
        cache_variables[cache_key] = resultado
        return resultado
    except Exception as e:
        print(f"ERROR evaluando la fórmula '{formula_string}' con contexto {contexto_local}: {e}")
        return Decimal('0')

class Command(BaseCommand):
    help = 'Diagnostica el cálculo de precios para un producto y una lista específicos.'

    def add_arguments(self, parser):
        parser.add_argument('nombre_producto', type=str, help='El nombre exacto del producto.')
        parser.add_argument('nombre_lista', type=str, help='El nombre exacto de la lista de precios.')

    def handle(self, *args, **options):
        nombre_producto_traducido = options['nombre_producto']
        nombre_lista = options['nombre_lista']

        self.stdout.write(self.style.SUCCESS(f"--- Iniciando diagnóstico para '{nombre_producto_traducido}' en la lista '{nombre_lista}' ---"))

        producto = Traducciones.objects.filter(stok=nombre_producto_traducido, active=True).first()
        if not producto:
            self.stdout.write(self.style.ERROR(f"[FALLO] El producto con nombre traducido '{nombre_producto_traducido}' no se encontró o no está activo."))
            return
        self.stdout.write(f"[PASO 1] Producto encontrado: '{producto.stok}' (Nombre original: {producto.equipo})")

        costo_obj = Lista_precio.objects.filter(producto=nombre_producto_traducido, nombre='Costo').order_by('-dia').first()
        costo_base = costo_obj.valor if costo_obj else Decimal('0')
        self.stdout.write(f"[PASO 2] Costo base: {self.style.SUCCESS(costo_base) if costo_obj else self.style.WARNING('No encontrado (se usa 0)')}")

        valor_publico_obj = Lista_precio.objects.filter(producto=nombre_producto_traducido, nombre='Valor Publico').order_by('-dia').first()
        valor_publico_base = valor_publico_obj.valor if valor_publico_obj else Decimal('0')
        self.stdout.write(f"[PASO 3] Valor Publico base: {self.style.SUCCESS(valor_publico_base) if valor_publico_obj else self.style.WARNING('No encontrado (se usa 0)')}")

        # --- INICIO DE CORRECCIÓN: AÑADIR BÚSQUEDA DE DESCUENTO ---
        descuento_obj = Lista_precio.objects.filter(producto=nombre_producto_traducido, nombre='Descuento').order_by('-dia').first()
        descuento_base = descuento_obj.valor if descuento_obj else Decimal('0')
        self.stdout.write(f"[PASO 3.5] Descuento base: {self.style.SUCCESS(descuento_base) if descuento_obj else self.style.WARNING('No encontrado (se usa 0)')}")
        # --- FIN DE CORRECCIÓN ---

        try:
            lista_precio = Permisos_precio.objects.get(permiso=nombre_lista)
            self.stdout.write(f"[PASO 4] Lista de precios encontrada: '{lista_precio.permiso}' (ID: {lista_precio.id})")
        except Permisos_precio.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"[FALLO] La lista de precios '{nombre_lista}' no existe."))
            return

        try:
            formula_obj = Formula.objects.get(price_id=lista_precio.id)
            self.stdout.write(f"[PASO 5] Fórmula encontrada: '{formula_obj.formula}'")
        except Formula.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"[FALLO] No se encontró una fórmula para la lista '{nombre_lista}'."))
            return

        self.stdout.write(self.style.HTTP_INFO("\n--- Desglose de Variables ---"))

        # --- INICIO DE CORRECCIÓN: AÑADIR DESCUENTO AL CONTEXTO ---
        contexto_inicial = {'Costo': costo_base, 'Valor': valor_publico_base, 'Descuento': descuento_base}
        # --- FIN DE CORRECCIÓN ---
        
        formula_str = formula_obj.formula
        try:
            formula_list = ast.literal_eval(formula_obj.formula)
            formula_str = ' '.join(map(str, formula_list))
        except (ValueError, SyntaxError):
            pass

        ids_a_cargar = [lista_precio.id, 1]
        todas_las_variables = Variables_prices.objects.filter(price_id__in=ids_a_cargar)
        mapa_variables_diagnostico = defaultdict(dict)
        for var in todas_las_variables:
            mapa_variables_diagnostico[var.price_id][var.name] = var

        variables_en_formula_principal = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', formula_str)
        contexto_final_para_eval = contexto_inicial.copy()

        for var_name in set(variables_en_formula_principal):
            if var_name in contexto_inicial:
                continue
            
            valor_calculado = motor_de_evaluacion_diagnostico(var_name, lista_precio.id, contexto_inicial, mapa_variables_diagnostico, {})
            contexto_final_para_eval[var_name] = valor_calculado
            self.stdout.write(f"  [Variable] '{var_name}' -> tiene el valor calculado de: {self.style.SUCCESS(valor_calculado)}")

        self.stdout.write(self.style.HTTP_INFO(f"\n--- Ejecutando Cálculo Final con Contexto: {contexto_final_para_eval} ---"))
        
        resultado_final = Decimal(eval(formula_str, {"__builtins__": None}, contexto_final_para_eval))

        self.stdout.write(self.style.SUCCESS(f"\nRESULTADO FINAL CALCULADO: {resultado_final}"))