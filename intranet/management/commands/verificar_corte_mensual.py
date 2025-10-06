from django.core.management.base import BaseCommand
from django.utils import timezone
from intranet.models import Comision, Configuracion # Ajusta la ruta a tus modelos

class Command(BaseCommand):
    help = 'Verifica si es el día de corte mensual y actualiza las comisiones pendientes y acumuladas a vencidas.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(f"--- Iniciando verificación de corte mensual: {timezone.now()} ---"))

        try:
            # 1. Obtener el día de corte configurado desde la base de datos
            config_dia_corte = Configuracion.objects.get(clave='DIA_CORTE_MENSUAL')
            dia_de_corte = int(config_dia_corte.valor)
            self.stdout.write(f"Día de corte configurado: {dia_de_corte}")

        except Configuracion.DoesNotExist:
            self.stdout.write(self.style.WARNING("No se ha configurado un día de corte mensual. Tarea terminada."))
            return
        except (ValueError, TypeError):
            self.stdout.write(self.style.ERROR("El valor del día de corte no es un número válido. Tarea terminada."))
            return
            
        # 2. Obtener el día actual
        dia_actual = timezone.now().day
        self.stdout.write(f"Día actual: {dia_actual}")

        # 3. Comparar y ejecutar la acción
        if dia_actual == dia_de_corte:
            self.stdout.write(self.style.WARNING(f"¡Hoy es el día de corte! Actualizando comisiones..."))
            
            estados_a_vencer = ['Pendiente', 'Acumulada']
            
            comisiones_para_actualizar = Comision.objects.filter(estado__in=estados_a_vencer)
            
            # .update() es una operación masiva y muy eficiente
            num_actualizadas = comisiones_para_actualizar.update(estado='Vencida')

            if num_actualizadas > 0:
                self.stdout.write(self.style.SUCCESS(f"¡Éxito! Se actualizaron {num_actualizadas} comisiones a estado 'Vencida'."))
            else:
                self.stdout.write(self.style.SUCCESS("No se encontraron comisiones pendientes o acumuladas para actualizar."))
        else:
            self.stdout.write("Hoy no es el día de corte. No se requiere ninguna acción.")

        self.stdout.write(self.style.SUCCESS("--- Verificación de corte mensual terminada. ---"))