import pyodbc
import pandas as pd

class Sql_conexion:

    def __init__(self,query):
        self.server = '***REMOVED-STOK_DB_SERVER***'
        self.bd = 'Stok'
        self.bd2 = 'TipsII'
        self.usuario = 'sa'
        self.contraseña = '***REMOVED-STOK_DB_PASSWORD***'

        # self.conn_key = ('Driver= {ODBC Driver 18 for SQL Server};'
        #             f'Server={self.server};'
        #             f'Database={self.bd};'
        #             f'UID={self.usuario};'
        #             f'PWD={self.contraseña}'
        #         )

        self.conn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=***REMOVED-STOK_DB_SERVER***;DATABASE=Stok;UID=sa;PWD=***REMOVED-STOK_DB_PASSWORD***')
        self.cursor = self.conn.cursor()
        self.query = query

        # self.conn = pyodbc.connect(self.conn_key)
        # self.conn.setdecoding(pyodbc.SQL_CHAR, encoding='latin-1')
        # self.conn.setencoding('latin-1')
        # self.data = pd.read_sql_query(self.query, self.conn)
        self.cursor.execute(self.query)
        self.description = self.cursor.description
        self.data = self.cursor.fetchall()
        self.conn.close()
    
    def get_data(self):
        return self.data
