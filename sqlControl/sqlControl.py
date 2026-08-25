import os

import pyodbc


class Sql_conexion:
    """
    Conexión de solo lectura al SQL Server externo del sistema "Stok"
    (facturación/ventas), ajeno a la app Django.

    Credenciales leídas desde variables de entorno (antes hardcodeadas):
      - STOK_DB_SERVER
      - STOK_DB_USER
      - STOK_DB_PASSWORD
    El nombre de base de datos no es un secreto y admite un valor por
    defecto ('Stok'), pero también puede sobreescribirse con STOK_DB_NAME.
    """

    def __init__(self, query):
        self.server = os.environ.get('STOK_DB_SERVER', '')
        self.bd = os.environ.get('STOK_DB_NAME', 'Stok')
        self.usuario = os.environ.get('STOK_DB_USER', '')
        self.contraseña = os.environ.get('STOK_DB_PASSWORD', '')

        conn_str = (
            'DRIVER={ODBC Driver 17 for SQL Server};'
            f'SERVER={self.server};'
            f'DATABASE={self.bd};'
            f'UID={self.usuario};'
            f'PWD={self.contraseña}'
        )

        self.conn = pyodbc.connect(conn_str)
        self.cursor = self.conn.cursor()
        self.query = query

        self.cursor.execute(self.query)
        self.description = self.cursor.description
        self.data = self.cursor.fetchall()
        self.conn.close()

    def get_data(self):
        return self.data
