import pyodbc
import pandas as pd

drivers = pyodbc.drivers()
print(drivers)

conn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=team.soluciondigital.com.co;DATABASE=TipsII;UID=sa;PWD=Soluciondig2015')

# Definir la consulta con parámetros para las fechas
# query = '''
# SELECT , plnPlanes.TipoDePlan AS [Tipo de Plan], 
#        plnPlanes.ValorCobradoActual AS [Valor Cobrado], plnPlanes.EstadoInicial AS [Estado], 
#        plnPlanes.UsuarioCreador AS [Cedula UsuarioCreador], segUsuarios.Nombre AS [Usuario Creador], 
#        plnPlanes.Comentario AS [Comentarios], venVentas.CodigoDistribuidor AS [Codigo Distribuidor], 
#        perPersonas.Nombre AS [Cliente Nombre], perPersonas.Direccion AS [Cliente Dirección], 
#        perPersonas.Telefono AS [Cliente Teléfono], venVentas.ClienteActual AS [Cliente Id], 
#        perPersonas.TipoDeIdentificacion AS [Cliente TipoId], perPersonas.Email AS [Cliente Email], 
#        venPlanillas.Numero AS [Planilla], venPlanillas.Comentarios AS [Comentarios Planilla], 
#        venPlanillas.FechaDeRecepcion AS [Fecha Recepcion Planilla]
# FROM venVentas 
# JOIN vndPuntosDeActivacionDeVendedor ON venVentas.PuntoDeActivacionId = vndPuntosDeActivacionDeVendedor.Codigo 

 
# JOIN plnPlanes ON venVentas.Plan = plnPlanes.Codigo 
# JOIN segUsuarios ON plnPlanes.UsuarioCreador = segUsuarios.Codigo 
# JOIN venContratos ON venVentas.Contrato = venContratos.Codigo 
# JOIN venTiposDeLinea ON venVentas.TipoDeLineaID = venTiposDeLinea.Codigo 
 
# JOIN perPersonas ON venVentas.ClienteActual = perPersonas.Codigo 
# WHERE venVentas.Fecha BETWEEN ? AND ?;
# '''
query = '''
SELECT venVentas.Fecha AS [Fecha], venVentas.FechaDeCreacion AS [Fecha de Creacion], 
       venVentas.Min AS [Min], venVentas.Iccid AS [Iccid], venVentas.Imei AS [Imei], 
       venVentas.Contrato AS [Contrato], venVentas.Valor AS [Valor], 
       venVentas.CustCode AS [CustCode], eqpEquipos.Marca AS [Marca Equipo], 
       eqpEquipos.Modelo AS [Modelo Equipo], vndVendedores.TipoDeVendedorActual AS [Tipo de Vendedor], 
       vndVendedores.GrupoDeVendedoresActual AS [Grupo de Vendedores], vndSucursales.Regional AS [Regional],
       venVentas.SucursalAlternativa AS [Sucursal], vndSucursales.Ciudad AS [Ciudad], 
       plnPlanes.Nombre AS [Nombre del Plan], segUsuarios.Nombre as [Usuario Creador]
       
FROM venVentas
LEFT JOIN eqpEquipos ON venVentas.Equipo = eqpEquipos.Codigo
LEFT JOIN vndVendedores ON venVentas.VendedorQueCierraId = vndVendedores.Codigo
LEFT JOIN vndSucursales ON venVentas.SucursalAlternativa = vndSucursales.Codigo
LEFT JOIN plnPlanes ON venVentas.[Plan] = plnPlanes.Codigo
LEFT JOIN segUsuarios ON plnPlanes.UsuarioCreador = segUsuarios.Codigo AND segUsuarios.Nombre IS NOT NULL



WHERE venVentas.Fecha BETWEEN ? AND ?;
'''

# Definir el rango de fechas
fecha_inicio = '2025-02-01'
fecha_fin = '2025-02-15'


cursor = conn.cursor()

cursor.execute(query, fecha_inicio, fecha_fin)

df = pd.DataFrame.from_records(cursor.fetchall(), columns=[desc[0] for desc in cursor.description])
df.to_excel('POS2.xlsx')


cursor.close()
conn.close()

#Variable en formato de cadena
cadena_con_formato = '${:,.2f}'.format(150000)

# Elimina el símbolo '$' y las comas, luego convierte a un valor numérico
valor_numerico = float(cadena_con_formato.replace('$', '').replace(',', ''))
resultado = valor_numerico + 200000
resultado_formateado = '${:,.2f}'.format(resultado)

# Imprime el resultado formateado
print(resultado_formateado)