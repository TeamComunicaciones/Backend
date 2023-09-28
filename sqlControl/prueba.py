import pyodbc
import pandas as pd

drivers = pyodbc.drivers()
print(drivers)

conn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=team.soluciondigital.com.co;DATABASE=Stok;UID=sa;PWD=Soluciondig2015')

cursor = conn.cursor()

query= (
            "SELECT TOP(1000) P.Nombre, lPre.nombre, ValorBruto "  
            "FROM dbo.ldpProductosXAsociaciones lProd " 
            "JOIN dbo.ldpListadePrecios  lPre ON lProd.ListaDePrecios = lPre.Codigo " 
            "JOIN dbo.Productos  P ON lProd.Producto = P.Codigo " 
            "JOIN dbo.TiposDeProducto  TP ON P.TipoDeProducto = TP.Codigo " 
            f"WHERE TP.Nombre = 'Prepagos' and P.Visible = 1 and P.Nombre = 'Isphone 12 128 Gb Prepago';"
        )

cursor.execute(query)

rows = cursor.fetchall()
print(len(rows))

for row in rows:
    print(row[0])

conn.close()