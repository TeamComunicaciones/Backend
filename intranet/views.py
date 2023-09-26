from rest_framework.exceptions import AuthenticationFailed
from rest_framework.decorators import api_view
from django.db.models.signals import pre_save
from django.dispatch import receiver
from rest_framework.response import Response
from django.shortcuts import render
from django.contrib.auth import login, authenticate
from . import models
import jwt, datetime
import json
import pandas as pd

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
    
@api_view(['GET', 'POST'])
def translate_products_prepago(request):
    if request.method == 'GET':
        models.Traducciones.objects.filter(tipo='prepago')
        return Response()
    if request.method == 'POST':
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
        print(df_translates)
        df_equipos = pd.DataFrame(data)
        df_equipos.columns = ['equipo']
        print('---------')
        print(df_equipos)
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
            nuevo_df['costo'] = 10
            nuevo_df = nuevo_df[['stok', 'costo']]
            data = nuevo_df.values.tolist()
            
        return Response({'validate': validate, 'data':data, 'crediminuto':crediminuto})