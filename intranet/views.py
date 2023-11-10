from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.models import User
from rest_framework.decorators import api_view
from django.db.models.signals import pre_save
from django.dispatch import receiver
from rest_framework.response import Response
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from sqlControl.sqlControl import Sql_conexion
from . import models
import jwt, datetime
import json
import pandas as pd
from decimal import Decimal
import random
# import locale




def shopify_token(request):
    api_key = 'd37d57aff7101337661ae6594f0f38d5'	#Set Partner app api key
    api_secret = '3ec5b155828a868687ef85444f88601f' #Set Partner app api secret
    scopes = 'write_products,read_content,read_discounts,read_locales'
    redirect_uri = 'https://api.teamcomunicaciones.com.co/api/v1.0/shopify-return/'
    shop = 'quickstart-06207d6f.myshopify.com'
    nonce = random.random() 
    url = "https://{}/admin/oauth/authorize?client_id={}&scope={}&redirect_uri={}&state={}&grant_options[]=offline-access".format(shop, api_key,  scopes, redirect_uri, nonce)
    redirect(url)

def shopify_return(request):
    code = request.GET
    return Response({"message":code})
    

@api_view(['GET', 'POST', 'OPTIONS'])
def login(request):
    if request.method == 'POST':
        username = request.data['email']
        password = request.data['password']
        user = authenticate(request, username=username, password= password)
        if user is not None:
            payload ={
                'id': user.username,
                'exp' : datetime.datetime.utcnow() + datetime.timedelta(minutes= 60),
                'iat' : datetime.datetime.utcnow()
            }
            token = jwt.encode(payload, 'secret', algorithm='HS256')
            response = Response()
            response.set_cookie(key='jwt', value=token, httponly=True)
            response.data = {
                'jwt':token
            }
            return response
        else:
            raise AuthenticationFailed('Clave o contraseña erroneas')
    raise AuthenticationFailed('Solo metodo POST')

@api_view(['GET', 'POST', 'OPTIONS'])
def create_user(request):
    if request.method == 'POST':
        user = request.data['email']
        password = request.data['password']

    
    raise AuthenticationFailed('Solo metodo POST')

@api_view(['POST'])
def user_validate(request):
    if request.method == 'POST':
        response = Response()
        response.set_cookie(key='jwts', value='hhh', httponly=True)
        data = request.body
        token = json.loads(data)
        token = token['jwt']
        if not token:
            raise AuthenticationFailed('Debes estar logueado')
        try:
            payload = jwt.decode(token, 'secret', algorithms='HS256')
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Debes estar logueado')
        return Response({"message":'usuario valido'})

@api_view(['POST'])
def user_permissions(request):
    if request.method == 'POST':
        response = Response()
        response.set_cookie(key='jwts', value='hhh', httponly=True)
        data = request.body
        token = json.loads(data)
        token = token['jwt']
        if not token:
            raise AuthenticationFailed('Debes estar logueado')
        try:
            payload = jwt.decode(token, 'secret', algorithms='HS256')
            usuario = User.objects.get(username=payload['id'])
            permisos_ind = models.Permisos_usuarios.objects.filter(
                user= usuario
            )
            
            # new_permiso = models.Permisos.objects.create(
            #     permiso ='comercial',
            #     active=True
            # )
            # new_permiso.save()

            permisos = {
                'superadmin' : usuario.is_superuser,
                'administrador' : {
                    'main': False,
                },
                'control_interno' : {
                    'main': False,
                },
                'gestion_humana' : {
                    'main': False,
                },
                'contabilidad' : {
                    'main': False,
                },
                'comisiones' : {
                    'main': False,
                },
                'soporte' : {
                    'main': False,
                },
                'auditoria' : {
                    'main': False,
                },
                'comercial' : {
                    'main': False,
                },
            }
            for i in permisos_ind:
                permisos[i.permiso.permiso]['main'] = i.tiene_permiso
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Debes estar logueado')
        return Response({"permisos":permisos})
    
@api_view(['POST'])
def permissions(request):
    if request.method == 'POST':
        response = Response()
        response.set_cookie(key='jwts', value='hhh', httponly=True)
        data = request.body
        token = json.loads(data)
        token = token['jwt']
        if not token:
            raise AuthenticationFailed('Debes estar logueado')
        try:
            payload = jwt.decode(token, 'secret', algorithms='HS256')
            usuario = User.objects.get(username=payload['id'])
            if usuario.is_superuser == False:
                raise AuthenticationFailed('Debes ser superuser')
            usuarios = list(User.objects.all())
            data = []
            for i in usuarios:
                control_interno = models.Permisos_usuarios.objects.filter(user=i.id, permiso=2)
                gestion_humana = models.Permisos_usuarios.objects.filter(user=i.id, permiso=3)
                contabilidad = models.Permisos_usuarios.objects.filter(user=i.id, permiso=4)
                comisiones = models.Permisos_usuarios.objects.filter(user=i.id, permiso=5)
                soporte = models.Permisos_usuarios.objects.filter(user=i.id, permiso=6)
                auditoria = models.Permisos_usuarios.objects.filter(user=i.id, permiso=7)
                comercial = models.Permisos_usuarios.objects.filter(user=i.id, permiso=8)
                data.append({
                    'usuario': i.username,
                    'control_interno': control_interno[0].tiene_permiso if len(control_interno)>0 else False,
                    'gestion_humana': gestion_humana[0].tiene_permiso if len(gestion_humana)>0 else False,
                    'contabilidad': contabilidad[0].tiene_permiso if len(contabilidad)>0 else False,
                    'comisiones': comisiones[0].tiene_permiso if len(comisiones)>0 else False,
                    'soporte': soporte[0].tiene_permiso if len(soporte)>0 else False,
                    'auditoria': auditoria[0].tiene_permiso if len(auditoria)>0 else False,
                    'comercial': comercial[0].tiene_permiso if len(comercial)>0 else False,
                    })
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Debes estar logueado')
        return Response({"usuarios": data})
    
@api_view(['POST'])
def permissions_edit(request):
    if request.method == 'POST':
        response = Response()
        response.set_cookie(key='jwts', value='hhh', httponly=True)
        data = request.body
        token = json.loads(data)
        token = token['jwt']
        if not token:
            raise AuthenticationFailed('Debes estar logueado')
        try:
            payload = jwt.decode(token, 'secret', algorithms='HS256')
            usuario = User.objects.get(username=payload['id'])
            if usuario.is_superuser == False:
                raise AuthenticationFailed('Debes ser superuser')
            for i in request.data['data']:
                user = User.objects.get(username=i['usuario'])
                for key, value in i.items():
                    if key != 'usuario':
                        perm = models.Permisos.objects.get(permiso=key)
                        permiso, created = models.Permisos_usuarios.objects.get_or_create(
                            user = user,
                            permiso = perm,
                            defaults={'tiene_permiso': value}
                        )
                        if not created:
                            permiso.tiene_permiso = value
                            permiso.save()
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Debes estar logueado')
        return Response({"message": 'guardado con exito'})
    
@api_view(['GET', 'POST'])
def translate_products_prepago(request):
    if request.method == 'GET':
        traducciones = models.Traducciones.objects.filter(tipo='prepago')
        data = []
        for i in traducciones:
            subdata = {
                'producto': i.equipo,
                'stok': i.stok,
                'iva': i.iva,
                'active': i.active,
            }
            data.append(subdata)
        return Response(data)
    if request.method == 'POST':
        data = request.body
        data = json.loads(data)
        equipo = data['equipo'],
        stok = data['stok'],
        iva = data['iva'] ,
        active = data['active'] ,
        tipo = 'prepago'
        query = (
            "SELECT TOP(1000) P.Nombre, lPre.nombre, ValorBruto "  
            "FROM dbo.ldpProductosXAsociaciones lProd " 
            "JOIN dbo.ldpListadePrecios  lPre ON lProd.ListaDePrecios = lPre.Codigo " 
            "JOIN dbo.Productos  P ON lProd.Producto = P.Codigo " 
            "JOIN dbo.TiposDeProducto  TP ON P.TipoDeProducto = TP.Codigo " 
            f"WHERE TP.Nombre = 'Prepagos' and P.Visible = 1 and P.Nombre = '{stok[0]}';"
        )
        conexion = Sql_conexion(query)
        data2 = conexion.get_data()
        if len(data2) == 0:
            raise AuthenticationFailed('Producto inexistente en Stok')
        
        listaStok = []
        for dato in data2:
            nombreStok = dato[0]
            if nombreStok not in listaStok:
                listaStok.append(nombreStok)
        for nstok in listaStok:
            validacion = nstok == stok
            if validacion == False:
                raise AuthenticationFailed(f'intente usar {nstok} y no {stok}')
        
        traduccion = models.Traducciones.objects.filter(equipo = request.data['equipo']).first()

        if traduccion:
            traduccion.stok
            traduccion.iva
            traduccion.active
            traduccion.save()

        else:
            new_translate = models.Traducciones.objects.create(
                equipo=request.data['equipo'],
                stok=request.data['stok'],
                iva =request.data['iva'] ,
                active=request.data['active'] ,
                tipo= 'prepago'
            )
            new_translate.save()

        return Response({'message':'equipo creado con exito'})

@api_view(['POST'])
def translate_prepago(requests):
    if requests.method == 'POST':
        # transnew = models.Traducciones.objects.create(
        #     equipo='equipoejemplo',
        #     stok='stokejemplo',
        #     iva = True,
        #     active= True,
        #     tipo='prepago'
        # )
        # transnew.save()
        data = requests.data
        translates = (models.Traducciones.objects.filter(tipo='prepago'))
        translates = [{
            'equipo': item.equipo,
            'stok': item.stok,
            'iva': item.iva,
            'active': item.active,
            'tipo': item.tipo
        } for item in translates]
        df_translates = pd.DataFrame(translates)
        df_equipos = pd.DataFrame(data)
        df_equipos.columns = [
            'equipo',
            'con iva', 
            'descuento', 
            '-iva +descuento',
            'total',
            'descuento agente',
            'precio -iva',
            'precio +iva'
        ]
        equipos_origen = df_equipos[df_equipos.columns[0]]
        equipos_translate = df_translates['equipo']
        equipos_no_encontrados = equipos_origen[~equipos_origen.isin(equipos_translate)]
        crediminuto = []
        if len(equipos_no_encontrados) > 0:
            validate = False
            data = equipos_no_encontrados.to_list()
        else:
            validate = True
            nuevo_df = df_equipos.merge(df_translates, on='equipo', how='left')
            nuevo_df = nuevo_df.drop_duplicates()
            data =[]
            for index, row in nuevo_df.iterrows():
                update_price = UpdatePrices(
                    row['stok'],
                    row['con iva'],
                    row['descuento'],
                    row['-iva +descuento'],
                    row['total'],
                    row['descuento agente'],
                    row['precio -iva'],
                    row['precio +iva'],
                    row['iva']
                )
                itemData = update_price.returnData()
                data.append(itemData[0])
            
        return Response({'validate': validate, 'data':data, 'crediminuto':crediminuto})
    
@api_view(['GET', 'POST'])
def lista_productos_prepago(requests):
    if requests.method == 'GET':
        query = (
            "SELECT TOP(1000) P.Nombre, lPre.nombre, ValorBruto "  
            "FROM dbo.ldpProductosXAsociaciones lProd " 
            "JOIN dbo.ldpListadePrecios  lPre ON lProd.ListaDePrecios = lPre.Codigo " 
            "JOIN dbo.Productos  P ON lProd.Producto = P.Codigo " 
            "JOIN dbo.TiposDeProducto  TP ON P.TipoDeProducto = TP.Codigo " 
            # f"WHERE P.Visible = 1;"
            f"WHERE TP.Nombre = 'Prepagos' and P.Visible = 1;"
        )
        conexion = Sql_conexion(query)
        data2 = conexion.get_data()
        equipo = []
        precio = []
        valor = []
        for i in data2:
            if i[0] != '.':
                equipo.append(i[0])
                precio.append(i[1])
                valor.append("{:.2f}".format(i[2].quantize(Decimal('0.00'))))
        data = {
            'equipo': equipo,
            'precio': precio,
            'valor': valor,
        }
        df = pd.DataFrame(data)
        # Pivota los datos
        pivot_df = df.pivot(index='equipo', columns='precio', values='valor').reset_index()

        # Reinicia el índice
        pivot_df.reset_index(drop=True, inplace=True)

        # Cambia el nombre de las columnas resultantes
        pivot_df.columns.name = None
        pivot_df = pivot_df.fillna('0')
        precios = pivot_df.to_dict(orient='records')
        return Response({'data' : precios})
    
    if requests.method == 'POST':
        try:
            data = requests.data['data']
            precio = requests.data['precio']
            new_data = []
            # locale.setlocale(locale.LC_ALL, 'es_CO.UTF-8')
            base_iva = 100000
            mensaje = 'no aplica'
            sim = 2000
            simzc = 20000

            for i in data:
                if float(i[precio]) == 999999999:
                    iva = mensaje
                    siniva = mensaje
                    precio_v = mensaje 
                elif float(i[precio]) > base_iva:
                    iva = '${:,.2f}'.format(float(i[precio]) * 0.19)
                    siniva = '${:,.2f}'.format(float(i[precio]))
                    precio_v = '${:,.2f}'.format(float(i[precio]) * 1.19 + sim *1.19)
                else:
                    iva = 0
                    siniva = '${:,.2f}'.format(float(i[precio]))
                    precio_v = '${:,.2f}'.format(float(i[precio]) + sim *1.19)
                tem_data = {
                    'equipo': i['equipo'],
                    'precio simcard': '${:,.2f}'.format(sim),
                    'IVA simcard': '${:,.2f}'.format(sim * 0.19),
                    'equipo sin IVA': siniva,
                    'IVA equipo': iva,
                    'total': precio_v,
                }
                if 'Sistecredito Sin Iva':
                    if tem_data['total'] != mensaje:
                        tem_data['Tramites Kit'] = '${:,.2f}'.format(0)
                        tem_data['Precio Sim Zc'] = '${:,.2f}'.format(simzc /1.19)
                        tem_data['IVA Sim Zc'] = '${:,.2f}'.format(simzc /1.19 * 0.19)
                        total_temp = float(tem_data['total'].replace('$', '').replace(',', ''))
                        tramites_temp = float(tem_data['Tramites Kit'].replace('$', '').replace(',', ''))
                        preciosim_temp = float(tem_data['Precio Sim Zc'].replace('$', '').replace(',', ''))
                        ivasim_temp = float(tem_data['IVA Sim Zc'].replace('$', '').replace(',', ''))
                        resultado = total_temp + tramites_temp + preciosim_temp + ivasim_temp
                        tem_data['total'] = '${:,.2f}'.format(resultado)
                    else:
                        tem_data['Tramites Kit'] = mensaje
                        tem_data['Precio Sim Zc'] = mensaje
                        tem_data['IVA Sim Zc'] = mensaje

                new_data.append(tem_data)

            return Response({'data' : new_data})
        except Exception as e:
            return AuthenticationFailed(e)

class UpdatePrices:

    def __init__(
        self, 
        producto,
        precioConIva,
        descuentoClaroPagoContado,
        valorSinIvaConDescuento,
        valorPagarDescuentoContado,
        descuentoAlDistribuidor,
        precioVtaDistribuidorSinIva,
        precioVtaDistribuidorConIva,
        iva
        ):
        

        self.producto = producto
        self.precioConIva = precioConIva
        self.descuentoClaroPagoContado = descuentoClaroPagoContado
        self.valorSinIvaConDescuento = valorSinIvaConDescuento
        self.valorPagarDescuentoContado = valorPagarDescuentoContado
        self.descuentoAlDistribuidor = descuentoAlDistribuidor
        self.precioVtaDistribuidorSinIva = precioVtaDistribuidorSinIva
        self.precioVtaDistribuidorConIva = precioVtaDistribuidorConIva
        self.iva = iva
        self.costoActual = '999999999.00'
        self.precioPubicoSinIva = '999999999.00'
        self.subdistribuidorSinIva = '999999999.00'
        self.freeMobileStore = '999999999.00'
        self.cliente0A5MesesSinIva = '999999999.00'
        self.cliente6A23MesesSinIva = '999999999.00'
        self.clienteMayorA24MesesSinIva = '999999999.00'
        self.clienteDescuentoKitPrepagoSinIva = '999999999.00'
        self.distritadosSinIva = '999999999.00'
        self.premiumSinIva = '999999999.00'
        self.tramitarSinIva = '999999999.00'
        self.peopleSinIva = '999999999.00'
        self.cooservunalSinIva = '999999999.00'
        self.fintechOficinasTeamSinIva = '999999999.00'
        self.fintechZonificacionSinIva = '999999999.00'
        self.oficinaMovilSinIva = '999999999.00'
        self.elianaRodas = '999999999.00'
        self.newcostoActual()
        self.newprecioPubicoSinIva()
        self.newsubdistribuidorSinIva()
        self.newfreeMobileStore()
        self.newcliente0A5MesesSinIva()
        self.newcliente6A23MesesSinIva()
        self.newclienteMayorA24MesesSinIva()
        self.newclienteDescuentoKitPrepagoSinIva()
        self.newdistritadosSinIva()
        self.newpremiumSinIva()
        self.newtramitarSinIva()
        self.newpeopleSinIva()
        self.newcooservunalSinIva()
        self.newfintechOficinasTeamSinIva()
        self.newfintechZonificacionSinIva()
        self.newoficinaMovilSinIva()
        self.newelianaRodas()

    def newcostoActual(self):
        self.costoActual = self.precioVtaDistribuidorSinIva - 2000

    def newprecioPubicoSinIva(self):
        if self.descuentoClaroPagoContado >0:
            descuento = 2000
        else:
            descuento = 0
        self.precioPubicoConIva= self.valorPagarDescuentoContado + descuento
        if self.iva == '1':
            self.precioPubicoSinIva = (self.precioPubicoConIva - 2380) / 1.19
        else:
            self.precioPubicoSinIva = (self.precioPubicoConIva - 2380)

    def newsubdistribuidorSinIva(self):
        precioSimEquipoSinIva = self.precioPubicoSinIva + 2000
        psqsi = precioSimEquipoSinIva
        self.psqsi = psqsi
        # Sub Descuento

        if psqsi > 702000:
            subDescuento = 38127
        elif psqsi > 520000:
            subDescuento = 35360
        elif psqsi > 442000:
            subDescuento = 31200
        elif psqsi > 299000:
            subDescuento = 27727
        elif psqsi > 130000:
            subDescuento = 24274
        elif psqsi > 104000:
            subDescuento = 17327
        elif psqsi > 91000:
            subDescuento = 13874
        elif psqsi > 78000:
            subDescuento = 10400
        elif psqsi > 51948:
            subDescuento = 7280
        elif psqsi > 18200:
            subDescuento = 4160
        else:
            subDescuento = 0

        # Descuento Adicional Sub
        if psqsi > 2500000:
            descuentoAdicionalSub = 25410
        elif psqsi > 1500000:
            descuentoAdicionalSub = 20510
        elif psqsi > 702001:
            descuentoAdicionalSub = 28210
        elif psqsi > 522001:
            descuentoAdicionalSub = 14560
        elif psqsi > 442001:
            descuentoAdicionalSub = 12600
        elif psqsi > 299001:
            descuentoAdicionalSub = 10780
        elif psqsi > 130001:
            descuentoAdicionalSub = 1890
        else:
            descuentoAdicionalSub = 0
        
        self.descuentoAdicionalsub = descuentoAdicionalSub
        
        if self.iva == '1':
            totalDecuentos = subDescuento + (descuentoAdicionalSub/1.19)
            subPrecioSinIva = psqsi - totalDecuentos +500
            subPrecioConIva = subPrecioSinIva * 1.19
            self.subdistribuidorSinIva = (subPrecioConIva-2380) / 1.19
        else:
            totalDecuentos = subDescuento + descuentoAdicionalSub
            subPrecioSinIva = psqsi - totalDecuentos +500
            subPrecioConIva = subPrecioSinIva + 380
            self.subdistribuidorSinIva = (subPrecioConIva - 2380)
        

    def newfreeMobileStore(self):
        # Ya no se utiliza, alianza vieja
        pass

    def newcliente0A5MesesSinIva(self):
        # Para postpago
        pass

    def newcliente6A23MesesSinIva(self):
        # Para postpago
        pass

    def newclienteMayorA24MesesSinIva(self):
        # Para postpago
        pass

    def newclienteDescuentoKitPrepagoSinIva(self):
        if self.descuentoClaroPagoContado > 0:
            if self.iva == '1':
                self.clienteDescuentoKitPrepagoSinIva = (self.precioConIva / 1.19) + 1680
            else:
                self.clienteDescuentoKitPrepagoSinIva =self.precioConIva - 2380 +2000
        else:
            self.clienteDescuentoKitPrepagoSinIva = self.precioPubicoSinIva

    def newdistritadosSinIva(self):
        # Ya no se utiliza, alianza vieja
        pass

    def newpremiumSinIva(self):

        # Descuento Premium

        if self.psqsi > 702000:
            descuentoPremium = 40040
        elif self.psqsi > 522000:
            descuentoPremium = 37655
        elif self.psqsi > 442000:
            descuentoPremium = 34069
        elif self.psqsi > 299000:
            descuentoPremium = 31075
        elif self.psqsi > 130000:
            descuentoPremium = 28098
        elif self.psqsi > 104000:
            descuentoPremium = 21658
        elif self.psqsi > 91000:
            descuentoPremium = 17342
        elif self.psqsi > 78000:
            descuentoPremium = 13000
        elif self.psqsi > 51948:
            descuentoPremium = 9100
        elif self.psqsi > 18200:
            descuentoPremium = 5200
        else:
            descuentoPremium = 0
        
        if self.iva == '1':
            totalDescuento = descuentoPremium + (self.descuentoAdicionalsub/1.19)
            elianaPrecioSinIva = self.psqsi - totalDescuento
            elianaPrecioConIVa = elianaPrecioSinIva * 1.19
            self.premiumSinIva = (elianaPrecioConIVa - 2380) / 1.19

        else:
            totalDescuento = descuentoPremium + self.descuentoAdicionalsub
            elianaPrecioConIVa = self.precioPubicoSinIva + 2000 - totalDescuento +380
            self.premiumSinIva = elianaPrecioConIVa - 2380
        
    def newtramitarSinIva(self):
        if self.psqsi > 702000:
            descuentoTramitar = 38127
        elif self.psqsi > 522000:
            descuentoTramitar = 35360
        elif self.psqsi > 442000:
            descuentoTramitar = 31200
        elif self.psqsi > 299000:
            descuentoTramitar = 27727
        elif self.psqsi > 130000:
            descuentoTramitar = 24274
        elif self.psqsi > 104000:
            descuentoTramitar = 17327
        elif self.psqsi > 91000:
            descuentoTramitar = 13874
        elif self.psqsi > 78000:
            descuentoTramitar = 10400
        elif self.psqsi > 51948:
            descuentoTramitar = 7280
        elif self.psqsi > 18200:
            descuentoTramitar = 4160
        else:
            descuentoTramitar = 0
        
        

        if self.iva == '1':
            tramitarSinIva = self.psqsi - descuentoTramitar
            tramitarConIVa = tramitarSinIva * 1.19
            self.tramitarSinIva = (tramitarConIVa - 2380) / 1.19 + 4201.68
        else:
            tramitarConIVa = self.psqsi - descuentoTramitar +380
            self.tramitarSinIva = (tramitarConIVa - 2380) + 5000

    def newpeopleSinIva(self):
        if self.iva == '1':
            peopleConIVa = self.precioPubicoConIva * 1.05
            self.peopleSinIva = (peopleConIVa - 2380) / 1.19

        else:
            peopleConIVa = self.precioPubicoSinIva * 1.05
            # 933064 es la base del iva, cualquier cambio en base mover aca
            baseIva = 933064

            if peopleConIVa > baseIva:
                self.peopleSinIva = baseIva
            else:
                self.peopleSinIva = peopleConIVa

    def newcooservunalSinIva(self):
        # Ya no se utiliza, alianza vieja
        pass

    def newfintechOficinasTeamSinIva(self):
        if self.iva == '1':
            self.fintechOficinasTeamSinIva = (self.precioPubicoConIva + 60000 - 2380) / 1.19
            self.fintechOficinasTeamConIva = (self.fintechOficinasTeamSinIva * 1.19) + 2380 + 20000
        else:
            # 933064 es la base del iva, cualquier cambio en base mover aca
            baseIva = 933064
            self.fintechOficinasTeamSinIva = (self.precioPubicoConIva + 60000 - 2380)
            self.fintechOficinasTeamConIva = (self.fintechOficinasTeamSinIva) + 2380 + 20000
            if self.fintechOficinasTeamSinIva > baseIva:
                self.fintechOficinasTeamSinIva = baseIva

    def newfintechZonificacionSinIva(self):
        if self.iva == '1':
            self.fintechZonificacionSinIva = (self.precioPubicoConIva + 80000 - 2380) / 1.19
        else:
            # 933064 es la base del iva, cualquier cambio en base mover aca
            baseIva = 933064 
            self.fintechZonificacionSinIva = (self.precioPubicoConIva + 80000 - 2380)
            if self.fintechZonificacionSinIva > baseIva:
                self.fintechZonificacionSinIva = baseIva

    def newoficinaMovilSinIva(self):
        if self.descuentoClaroPagoContado > 0:
            self.oficinaMovilSinIva = self.precioPubicoSinIva
        else:
            self.oficinaMovilSinIva = self.subdistribuidorSinIva

    def newelianaRodas(self):
        # Ya no se utiliza, alianza vieja
        pass

    def formatoData(self):
        if (type(self.producto)) == float : self.producto  = round(self.producto ,2)
        if (type(self.costoActual)) == float : self.costoActual  = round(self.costoActual ,2)
        if (type(self.precioPubicoSinIva)) == float : self.precioPubicoSinIva  = round(self.precioPubicoSinIva ,2)
        if (type(self.subdistribuidorSinIva)) == float : self.subdistribuidorSinIva  = round(self.subdistribuidorSinIva ,2)
        if (type(self.freeMobileStore)) == float : self.freeMobileStore  = round(self.freeMobileStore ,2)
        if (type(self.cliente0A5MesesSinIva)) == float : self.cliente0A5MesesSinIva  = round(self.cliente0A5MesesSinIva ,2)
        if (type(self.cliente6A23MesesSinIva)) == float : self.cliente6A23MesesSinIva  = round(self.cliente6A23MesesSinIva ,2)
        if (type(self.clienteMayorA24MesesSinIva)) == float : self.clienteMayorA24MesesSinIva  = round(self.clienteMayorA24MesesSinIva ,2)
        if (type(self.clienteDescuentoKitPrepagoSinIva)) == float : self.clienteDescuentoKitPrepagoSinIva  = round(self.clienteDescuentoKitPrepagoSinIva ,2)
        if (type(self.distritadosSinIva)) == float : self.distritadosSinIva  = round(self.distritadosSinIva ,2)
        if (type(self.premiumSinIva)) == float : self.premiumSinIva  = round(self.premiumSinIva ,2)
        if (type(self.tramitarSinIva)) == float : self.tramitarSinIva = round(self.tramitarSinIva,2)
        if (type(self.peopleSinIva)) == float : self.peopleSinIva  = round(self.peopleSinIva ,2)
        if (type(self.cooservunalSinIva)) == float : self.cooservunalSinIva  = round(self.cooservunalSinIva ,2)
        if (type(self.fintechOficinasTeamSinIva)) == float : self.fintechOficinasTeamSinIva  = round(self.fintechOficinasTeamSinIva ,2)
        if (type(self.fintechZonificacionSinIva)) == float : self.fintechZonificacionSinIva  = round(self.fintechZonificacionSinIva ,2)
        if (type(self.oficinaMovilSinIva)) == float : self.oficinaMovilSinIva  = round(self.oficinaMovilSinIva ,2)
        if (type(self.elianaRodas)) == float : self.elianaRodas  = round(self.elianaRodas ,2)
        if (type(self.fintechOficinasTeamConIva)) == float : self.fintechOficinasTeamConIva  = round(self.fintechOficinasTeamConIva ,0)
    
    def returnData(self):
        self.formatoData()
        return [
           [ 
                str(self.producto),
                str(self.costoActual),
                str(self.precioPubicoSinIva),
                str(self.subdistribuidorSinIva),
                str(self.freeMobileStore),
                str(self.cliente0A5MesesSinIva),
                str(self.cliente6A23MesesSinIva),
                str(self.clienteMayorA24MesesSinIva),
                str(self.clienteDescuentoKitPrepagoSinIva),
                str(self.distritadosSinIva),
                str(self.premiumSinIva),
                str(self.tramitarSinIva),
                str(self.peopleSinIva),
                str(self.cooservunalSinIva),
                str(self.fintechOficinasTeamSinIva),
                str(self.fintechZonificacionSinIva),
                str(self.oficinaMovilSinIva),
                str(self.elianaRodas),
            ],
            self.fintechOficinasTeamConIva,
        ]