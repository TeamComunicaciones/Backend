import csv
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction
from decimal import Decimal, InvalidOperation

# Importamos los modelos que creamos/modificamos
from tu_app.models import Carga, Lista_precio # <-- ¡IMPORTANTE! Reemplaza 'tu_app' con el nombre real de tu aplicación

class Command(BaseCommand):
    help = 'Carga una lista de precios desde un archivo CSV y la asocia a un nuevo lote de Carga.'

    def add_arguments(self, parser):
        # Argumento para la ruta del archivo CSV
        parser.add_argument('--file', type=str, help='La ruta completa al archivo CSV a procesar.', required=True)
        # Argumento para saber qué usuario está realizando la carga
        parser.add_argument('--user', type=str, help='El nombre de usuario (username) que realiza la carga.', required=True)

    @transaction.atomic # Envuelve toda la operación en una transacción. Si algo falla, se revierte todo.
    def handle(self, *args, **options):
        file_path = options['file']
        username = options['user']

        self.stdout.write(self.style.NOTICE(f'Iniciando carga del archivo: {file_path}'))

        # 1. Validar que el usuario exista
        try:
            user = User.objects.get(username=username)
            self.stdout.write(self.style.SUCCESS(f'Usuario "{username}" encontrado.'))
        except User.DoesNotExist:
            raise CommandError(f'El usuario con username "{username}" no existe. La carga ha sido cancelada.')

        # 2. Crear UN ÚNICO registro de Carga para este lote
        # Este es el paso clave para agrupar todos los precios de este archivo.
        try:
            nueva_carga = Carga.objects.create(
                usuario=user,
                nombre_archivo=file_path.split('/')[-1].split('\\')[-1] # Extrae solo el nombre del archivo
            )
            self.stdout.write(self.style.SUCCESS(f'Lote de Carga creado con ID: {nueva_carga.id}'))
        except Exception as e:
            raise CommandError(f"Error al crear el lote de Carga: {e}")

        # 3. Procesar el archivo y preparar los registros para la inserción masiva
        registros_a_crear = []
        try:
            with open(file_path, mode='r', encoding='utf-8') as csv_file:
                csv_reader = csv.DictReader(csv_file)
                for i, row in enumerate(csv_reader):
                    # Asumimos que tu CSV tiene estas columnas. AJUSTA SEGÚN TU ARCHIVO.
                    producto = row.get('producto')
                    nombre_lista = row.get('nombre_lista')
                    valor_str = row.get('valor')

                    if not all([producto, nombre_lista, valor_str]):
                        self.stdout.write(self.style.WARNING(f"Advertencia: Fila {i+2} ignorada por tener datos faltantes."))
                        continue
                    
                    try:
                        valor = Decimal(valor_str)
                    except InvalidOperation:
                        self.stdout.write(self.style.WARNING(f"Advertencia: Fila {i+2} con producto '{producto}' tiene un valor no numérico ('{valor_str}'). Fila ignorada."))
                        continue

                    # Creamos la instancia en memoria, sin guardarla aún
                    registro = Lista_precio(
                        producto=producto,
                        nombre=nombre_lista,
                        valor=valor,
                        # ASIGNAMOS LA MISMA CARGA A CADA REGISTRO
                        carga=nueva_carga,
                        # ASIGNAMOS EL MISMO TIMESTAMP DE LA CARGA A CADA REGISTRO
                        dia=nueva_carga.fecha_carga 
                    )
                    registros_a_crear.append(registro)
        
        except FileNotFoundError:
            raise CommandError(f'Error: El archivo "{file_path}" no fue encontrado.')
        except Exception as e:
            raise CommandError(f"Error al leer el archivo CSV: {e}")

        # 4. Insertar todos los registros en la base de datos de una sola vez
        # Esto es mucho más rápido y eficiente que guardar uno por uno.
        if registros_a_crear:
            try:
                Lista_precio.objects.bulk_create(registros_a_crear)
                self.stdout.write(self.style.SUCCESS(f'¡Carga completada! Se han insertado {len(registros_a_crear)} registros de precios.'))
            except Exception as e:
                raise CommandError(f"Error durante la inserción masiva en la base de datos: {e}")
        else:
            self.stdout.write(self.style.WARNING('No se encontraron registros válidos para cargar en el archivo.'))