# comisiones/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Nos unimos a un grupo específico del usuario.
        # Así, solo le llegan notificaciones a este usuario.
        self.user = self.scope["user"]
        if self.user.is_authenticated:
            self.room_group_name = f'user_{self.user.id}_notifications'
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()
        else:
            # Rechazar la conexión si el usuario no está autenticado
            await self.close()

    async def disconnect(self, close_code):
        # Salir del grupo al desconectar
        if self.user.is_authenticated:
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    # Este método es llamado cuando la tarea de Celery envía un mensaje.
    async def send_notification(self, event):
        message = event['message']
        status = event.get('status', 'info') # info, success, error

        # Enviar el mensaje al WebSocket
        await self.send(text_data=json.dumps({
            'message': message,
            'status': status,
        }))