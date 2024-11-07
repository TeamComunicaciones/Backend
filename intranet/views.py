from rest_framework.exceptions import AuthenticationFailed
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.models import User
from rest_framework.decorators import api_view
from django.db.models.signals import pre_save
from django.dispatch import receiver
from rest_framework.response import Response
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
from sqlControl.sqlControl import Sql_conexion
from django.db import IntegrityError
from django.utils import timezone
from . import models
import jwt, datetime
import json
import pandas as pd
import numpy as np
from decimal import Decimal
import random
import requests
import os
import shutil
import uuid
import ast
from datetime import date
# import locale
import string
import base64


ruta = "D:\\Proyectos\\TeamComunicaciones\\pagina\\frontend\\src\\assets"

@api_view(['POST'])
def assign_responsible(request):
    responsable = request.data['encargado']
    sucursal = request.data['sucursal']
    responsable_id = models.User.objects.get(username=responsable.split('-')[0])
    sucursal_id = models.Codigo_oficina.objects.get(terminal=sucursal)
    try:
        responsable_corresponsal = models.Responsable_corresponsal.objects.get(sucursal=sucursal_id)
        responsable_corresponsal.user = responsable_id
        responsable_corresponsal.save()
    except ObjectDoesNotExist:
        models.Responsable_corresponsal.objects.create(sucursal=sucursal_id, user=responsable_id)
    return Response([])


@api_view(['POST'])
def get_image_corresponsal(request):
    tenant_id = '69002990-8016-415d-a552-cd21c7ad750c'
    client_id = '46a313cf-1a14-4d9a-8b79-9679cc6caeec'
    client_secret = 'w3V8Q~2H9W7urWqPPpRLywCU3c69WLSjHWDRhdhB'

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data2 = {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default'
    }

    response = requests.post(url, headers=headers, data=data2)

    if response.status_code == 200:
        access_token = response.json().get('access_token')
    else:
        raise AuthenticationFailed(f"Error getting access token")
    
    file_name = request.data['url']

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    site_id = 'teamcommunicationsa.sharepoint.com,71134f24-154d-4138-8936-3ef32a41682e,1c13c18c-ec54-4bf0-8715-26331a20a826'
    download_url = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/uploads/{file_name}:/content'

    # Descargar la imagen desde SharePoint
    response = requests.get(download_url, headers=headers)

    if response.status_code == 200:
        # Devolver la imagen al frontend
        encoded_image = base64.b64encode(response.content).decode('utf-8')
        return JsonResponse({'image': encoded_image, 'content_type': response.headers['Content-Type']})
    else:
        return JsonResponse({'error': response.json()}, status=400)


    pass

@api_view(['POST'])
def select_consignaciones_corresponsal_cajero(request):
    fecha = request.data['fecha']
    sucursal = request.data['sucursal']
    tamaño_fecha = len(fecha)
    if tamaño_fecha == 7:
        año, mes = map(int, fecha.split('-'))
        fecha_inicio = datetime.datetime(año, mes, 1)
        if mes == 12:
            fecha_fin = datetime.datetime(año + 1, 1, 1) - datetime.timedelta(seconds=1)
        else:
            fecha_fin = datetime.datetime(año, mes + 1, 1) - datetime.timedelta(seconds=1)
    else:
        fecha_inicio = datetime.datetime.strptime(fecha, '%Y-%m-%d')
        fecha_fin = datetime.datetime.strptime(fecha, '%Y-%m-%d')

    transacciones = models.Corresponsal_consignacion.objects.filter(fecha__range=(fecha_inicio, fecha_fin), codigo_incocredito=sucursal)
    transacciones_data = []
    total_datos = 0
    data_transacciones = []
    for t in transacciones:
            total_datos = total_datos + t.valor
            data_transacciones.append({
                'banco': t.banco,
                'url': t.url,
                'valor': f"${t.valor:,.2f}",
            })
    return Response({'total': f"${total_datos:,.2f}", 'detalles': data_transacciones})

@api_view(['POST'])
def consignacion_corresponsal(request):
    if request.method == 'POST':
        data = request.data
        token = request.data['jwt']
        image = request.FILES['image']
        consignacion_data = json.loads(request.POST.get('data'))
        payload = jwt.decode(token, 'secret', algorithms='HS256')
        usuario = User.objects.get(username=payload['id'])
        print(usuario.id)
        tenant_id = '69002990-8016-415d-a552-cd21c7ad750c'
        client_id = '46a313cf-1a14-4d9a-8b79-9679cc6caeec'
        client_secret = 'w3V8Q~2H9W7urWqPPpRLywCU3c69WLSjHWDRhdhB'

        url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        data2 = {
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': 'https://graph.microsoft.com/.default'
        }

        response = requests.post(url, headers=headers, data=data2)

        if response.status_code == 200:
            access_token = response.json().get('access_token')
        else:
            raise AuthenticationFailed(f"Error getting access token")
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/octet-stream'
        }
        site_id = 'teamcommunicationsa.sharepoint.com,71134f24-154d-4138-8936-3ef32a41682e,1c13c18c-ec54-4bf0-8715-26331a20a826'  # Reemplaza con tu site-id
        file_name = generate_unique_filename(image.name)
        upload_url = f'https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/uploads/{file_name}:/content'
        response = requests.put(upload_url, headers=headers, data=image.read())
        estado = 'saldado' if consignacion_data.get('banco') == 'Corresponsal Banco de Bogota' else 'pendiente'
        models.Corresponsal_consignacion.objects.create(
            valor = consignacion_data.get('valor'),
            banco = consignacion_data.get('banco'),
            fecha_consignacion = datetime.datetime.strptime(consignacion_data.get('fechaConsignacion'), '%Y-%m-%d').date(),
            fecha = datetime.datetime.strptime(data['fecha'], '%Y-%m-%d').date(),
            responsable = usuario.id,
            estado = estado,
            detalle = consignacion_data.get('detalle'),
            url = file_name,
            codigo_incocredito = 'Alpujarra',
            detalle_banco = consignacion_data.get('proveedor'),
        )
        print(data['data'])
        return Response([])

@api_view(['GET', 'POST', 'PUT'])
def lista_usuarios(request):
    if request.method == 'GET':
        users = User.objects.all()
        users_list = [{'id': i.id, 'document': i.username, 'firstName': i.first_name, 'lastName': i.last_name, 'active': i.is_active } for i in users if i.username != 'sebasmoncada']
        return Response(users_list)
    if request.method == 'POST':
        type_action = request.data['type']
        data = request.data['user']
        user = User.objects.get(username = data['document'])
        if type_action == 'reset':
            user.set_password('Cambiame123')
            user.save()
        elif type_action == 'activate':
            user.is_active = not data['active']
            user.save()
        return Response([])
    if request.method == 'PUT':
        data = request.data
        user = User.objects.create_user(
            password = 'Cambiame123',
            username = data['document'],
            first_name = data['firstName'],
            last_name = data['lastName'],
            email = data['email'],
        )
        user.save()
        return Response([])

@api_view(['POST'])
def encargados_corresponsal(request):
    sucursales = models.Codigo_oficina.objects.all()
    sucursales = [i.terminal for i in sucursales]
    responsables = models.Responsable_corresponsal.objects.all()
    responsables = {i.sucursal.terminal: f'{i.user.username}-{i.user.first_name}-{i.user.last_name}' for i in responsables}
    users = User.objects.all()
    users_list = [f'{i.username}-{i.first_name}-{i.last_name}' for i in users]
    users_options = [{'value':f'{i.username}-{i.first_name}-{i.last_name}', 'text':f'{i.username}-{i.first_name}-{i.last_name}'} for i in users if i.username != 'sebasmoncada']
    data = {
        'sucursales': sucursales,
        'users': users_list,
        'users_options': users_options,
        'responsables': responsables,
    }
    return Response(data)

@api_view(['POST'])
def resumen_corresponsal(request):
    fecha = request.data['fecha']
    sucursal = request.data['sucursal']
    tamaño_fecha = len(fecha)
    if tamaño_fecha == 7:
        año, mes = map(int, fecha.split('-'))
        fecha_inicio = datetime.datetime(año, mes, 1)
        if mes == 12:
            fecha_fin = datetime.datetime(año + 1, 1, 1) - datetime.timedelta(seconds=1)
        else:
            fecha_fin = datetime.datetime(año, mes + 1, 1) - datetime.timedelta(seconds=1)
    else:
        fecha_inicio = datetime.datetime.strptime(fecha, '%Y-%m-%d')
        fecha_fin = datetime.datetime.strptime(fecha, '%Y-%m-%d')
    transacciones = models.Transacciones_sucursal.objects.filter(fecha__range=(fecha_inicio, fecha_fin), codigo_incocredito=sucursal )
    valor_total = 0
    for i in transacciones:
        valor_total = valor_total + i.valor
    nombre_sucursal = models.Codigo_oficina.objects.get(codigo=sucursal).terminal
    transacciones2 = models.Corresponsal_consignacion.objects.filter(fecha__range=(fecha_inicio, fecha_fin), codigo_incocredito=nombre_sucursal)
    total_datos2 = 0
    pendientes = 0
    transacciones_data = []
    usuarios = User.objects.all()
    dic_usuarios = { i.id: i.username for i in usuarios}
    for t in transacciones2:
            transacciones_data.append({
                'valor' : f"${t.valor:,.2f}",
                'banco' : t.banco,
                'fecha_consignacion' : t.fecha_consignacion,
                'fecha' : t.fecha,
                'responsable' : dic_usuarios[int(t.responsable)],
                'estado' : t.estado,
                'detalle' : t.detalle,
                'url': t.url
            })
            if t.estado == 'pendiente':
                pendientes = pendientes + t.valor
            else:
                total_datos2 = total_datos2 + t.valor
    sucursal_codigo = models.Codigo_oficina.objects.filter(codigo=sucursal).first()
    df_consolidado = pd.DataFrame(transacciones_data)
    consolidado = df_consolidado.to_html(classes='table table-striped', index=False)
    data = {
        'valor':f"${valor_total:,.2f}", 
        'titulo':sucursal_codigo.terminal,
        'consignacion': f"${total_datos2:,.2f}",
        'pendiente': f"${pendientes:,.2f}",
        'restante':f"${valor_total - total_datos2 - pendientes:,.2f}",
        'consignaciones': transacciones_data
    }
    return Response(data)

@api_view(['POST'])
def select_datos_corresponsal(request):
    fecha = request.data['fecha']
    tamaño_fecha = len(fecha)
    if tamaño_fecha == 7:
        año, mes = map(int, fecha.split('-'))
        fecha_inicio = datetime.datetime(año, mes, 1)
        if mes == 12:
            fecha_fin = datetime.datetime(año + 1, 1, 1) - datetime.timedelta(seconds=1)
        else:
            fecha_fin = datetime.datetime(año, mes + 1, 1) - datetime.timedelta(seconds=1)
    else:
        fecha_inicio = datetime.datetime.strptime(fecha, '%Y-%m-%d')
        fecha_fin = datetime.datetime.strptime(fecha, '%Y-%m-%d')
    transacciones = models.Transacciones_sucursal.objects.filter(fecha__range=(fecha_inicio, fecha_fin))
    transacciones_data = []
    for t in transacciones:
            transacciones_data.append({
                'establecimiento': t.establecimiento,
                'codigo_aval': t.codigo_aval,
                'codigo_incocredito': t.codigo_incocredito,
                'terminal': t.terminal,
                'fecha': t.fecha.strftime('%d/%m/%Y'),
                'hora': t.hora,
                'nombre_convenio': t.nombre_convenio,
                'operacion': t.operacion,
                'fact_cta': t.fact_cta,
                'cod_aut': t.cod_aut,
                'valor': t.valor,
                'nura': t.nura,
                'esquema': t.esquema,
                'numero_tarjeta': t.numero_tarjeta,
                'comision': t.comision,
            })
    sucursales = models.Codigo_oficina.objects.all()
    cod_sucursales = {i.codigo: i.terminal for i in sucursales} 
    sucursales_dict = [{'value':i.codigo,'text':i.terminal} for i in sucursales]
    df_transacciones = pd.DataFrame(transacciones_data)
    df_transacciones['codigo_incocredito'] = df_transacciones['codigo_incocredito'].map(cod_sucursales)
    df_transacciones['cuenta'] = 1
    df_consolidado = df_transacciones.groupby(['codigo_incocredito']).agg({'cuenta':'sum', 'valor':'sum'}).reset_index()
    if tamaño_fecha == 7:
        fecha_inicio = timezone.make_aware(fecha_inicio, timezone.get_current_timezone())
        fecha_fin = timezone.make_aware(fecha_fin, timezone.get_current_timezone())
    consignaciones = models.Corresponsal_consignacion.objects.filter(fecha__range=(fecha_inicio, fecha_fin))
    consignaciones_data = []
    for i in consignaciones:
            consignaciones_data.append({
                'codigo_incocredito': i.codigo_incocredito,
                'estado': i.estado,
                'valor': i.valor,
            })
    df_consignaciones = pd.DataFrame(consignaciones_data)
    df_consignaciones = df_consignaciones.pivot_table(
        index='codigo_incocredito', 
        columns='estado', 
        values='valor', 
        aggfunc='sum'
    ).reset_index()
    df_consignaciones = df_consignaciones.fillna(0)
    df_consolidado = pd.merge(df_consolidado, df_consignaciones, on='codigo_incocredito', how='outer')
    df_consolidado = df_consolidado.fillna(0)
    df_consolidado['valor'] = df_consolidado['valor'].apply(lambda x: f"${x:,.2f}")
    df_consolidado['pendiente'] = df_consolidado['pendiente'].apply(lambda x: f"${x:,.2f}")
    df_consolidado['saldado'] = df_consolidado['saldado'].apply(lambda x: f"${x:,.2f}")
    consolidado = df_consolidado.to_dict(orient='records')
    data_excel = [i | {'sucursal': cod_sucursales[i['codigo_incocredito']]} for i in transacciones_data]
    return Response({'consolidado': consolidado, 'sucursales': sucursales_dict, 'data': data_excel })

@api_view(['POST'])
def select_datos_corresponsal_cajero(request):
    fecha = request.data['fecha']
    token = request.data['jwt']
    payload = jwt.decode(token, 'secret', algorithms='HS256')
    user = User.objects.get(username = payload['id'])
    sucursales = models.Responsable_corresponsal.objects.all()
    sucursal = ''
    for i in sucursales:
        if i.user.username == user.username:
            sucursal = i.sucursal.terminal
            break
    # sucursal = request.data['sucursal']
    tamaño_fecha = len(fecha)
    if tamaño_fecha == 7:
        año, mes = map(int, fecha.split('-'))
        fecha_inicio = datetime.datetime(año, mes, 1)
        if mes == 12:
            fecha_fin = datetime.datetime(año + 1, 1, 1) - datetime.timedelta(seconds=1)
        else:
            fecha_fin = datetime.datetime(año, mes + 1, 1) - datetime.timedelta(seconds=1)
    else:
        fecha_inicio = datetime.datetime.strptime(fecha, '%Y-%m-%d')
        fecha_fin = datetime.datetime.strptime(fecha, '%Y-%m-%d')
    sucursales = models.Codigo_oficina.objects.all()
    cod_sucursales = {i.terminal: i.codigo for i in sucursales}
    codigo_sucursal = cod_sucursales[sucursal] 
    transacciones = models.Transacciones_sucursal.objects.filter(fecha__range=(fecha_inicio, fecha_fin), codigo_incocredito=codigo_sucursal)
    transacciones_data = []
    total_datos = 0
    for t in transacciones:
            transacciones_data.append({
                'establecimiento': t.establecimiento,
                'codigo_aval': t.codigo_aval,
                'codigo_incocredito': t.codigo_incocredito,
                'terminal': t.terminal,
                'fecha': t.fecha.strftime('%d/%m/%Y'),
                'hora': t.hora,
                'nombre_convenio': t.nombre_convenio,
                'operacion': t.operacion,
                'fact_cta': t.fact_cta,
                'cod_aut': t.cod_aut,
                'valor': t.valor,
                'nura': t.nura,
                'esquema': t.esquema,
                'numero_tarjeta': t.numero_tarjeta,
                'comision': t.comision,
            })
            total_datos = total_datos + t.valor
    return Response({'total': f"${total_datos:,.2f}", 'sucursal': sucursal})

@api_view(['POST'])
def guardar_datos_corresponsal(request):
    cabecera = request.data['cabecera']
    items = request.data['items']
    df =pd.DataFrame(items, columns=cabecera)
    df.fillna("", inplace=True)
    df['valor'] = df['valor'].replace("", "0").astype(int)
    df['nura'] = df['nura'].replace("", "0").astype(int)
    df['comision'] = df['comision'].replace("", "0").astype(int)
    # df['fecha'] = pd.to_datetime(df['fecha'], format='%d/%m/%Y')
    fecha_min = df['fecha'].min()
    fecha_max = df['fecha'].max()
    fecha_minima = timezone.make_aware(datetime.datetime.strptime(fecha_min, '%d/%m/%Y'))
    fecha_maxima = timezone.make_aware(datetime.datetime.strptime(fecha_max, '%d/%m/%Y'))
    try:
        transacciones = models.Transacciones_sucursal.objects.filter(fecha__range=(fecha_minima, fecha_maxima))
        transacciones_data = []
        for t in transacciones:
            transacciones_data.append({
                'establecimiento': t.establecimiento,
                'codigo_aval': t.codigo_aval,
                'codigo_incocredito': t.codigo_incocredito,
                'terminal': t.terminal,
                'fecha': t.fecha.strftime('%d/%m/%Y'),
                'hora': t.hora,
                'nombre_convenio': t.nombre_convenio,
                'operacion': t.operacion,
                'fact_cta': t.fact_cta,
                'cod_aut': t.cod_aut,
                'valor': t.valor,
                'nura': t.nura,
                'esquema': t.esquema,
                'numero_tarjeta': t.numero_tarjeta,
                'comision': t.comision,
            })

        rows_to_drop = []
        for index, row in df.iterrows():
            row_dict = row.to_dict()
            if row_dict in transacciones_data:
                print('esta es igual ')
                rows_to_drop.append(index)
        df.drop(rows_to_drop, inplace=True)
    except:
        pass
    transacciones = []
    for index, row in df.iterrows():
        try:
            establecimiento = row.establecimiento
            codigo_aval = row.codigo_aval
            codigo_incocredito = row.codigo_incocredito
            terminal = row.terminal
            fecha = datetime.datetime.strptime(row.fecha, "%d/%m/%Y").date()
            hora = row.hora
            nombre_convenio = row.nombre_convenio
            operacion = row.operacion
            fact_cta = row.fact_cta
            cod_aut = row.cod_aut
            valor = row.valor if operacion != 'Retiro' else -row.valor
            nura = row.nura
            esquema = row.esquema
            numero_tarjeta = row.numero_tarjeta
            comision = row.comision
            transacciones.append(models.Transacciones_sucursal(
                establecimiento=establecimiento,
                codigo_aval=codigo_aval,
                codigo_incocredito=codigo_incocredito,
                terminal=terminal,
                fecha=fecha,
                hora=hora,
                nombre_convenio=nombre_convenio,
                operacion=operacion,
                fact_cta=fact_cta,
                cod_aut=cod_aut,
                valor=valor,
                nura=nura,
                esquema=esquema,
                numero_tarjeta=numero_tarjeta,
                comision=comision,
            ))
        except Exception as e:
            texto = str(e).replace("'Series' object has no attribute ","Datos no tienen columna ")
            raise AuthenticationFailed(texto)
        
    models.Transacciones_sucursal.objects.bulk_create(transacciones)
   
    return Response({'mensaje':'Guardado con exito'})

@api_view(['POST'])
def calcular_comisiones(request):
    comisiones = models.Porcentaje_comision.objects.all()
    comisiones_dic = {i.nombre:i.valor for i in comisiones}

    def comision_servicios_hfc(row):
        red = row['RED']
        tipo = row['TIPO VENTA']
        convergencia = row['CONVERGENCIA']
        valor =row['TOTAL MENSUALIDAD']

        if red == 'HFC':
            if convergencia == 'Convergente':
                if tipo == 'CROSS SELLING' or tipo == 'NEW':
                    comision_valor = comisiones_dic['hfc new cross selling convergente']
                elif tipo == 'UP SELLING/FO' or tipo == 'UP SELLING':
                    comision_valor = comisiones_dic['hfc up selling convergente']
                else:
                    comision_valor = 0
            else:
                if tipo == 'CROSS SELLING' or tipo == 'NEW':
                    comision_valor = comisiones_dic['hfc new cross selling no convergente']
                elif tipo == 'UP SELLING/FO' or tipo == 'UP SELLING':
                    comision_valor = comisiones_dic['hfc up selling no convergente']
                else:
                    comision_valor = 0
            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_float = 0
        resultado = float(valor) * comision_float
        return resultado
    
    def aceleradores_hfc(row):
        red = row['RED']
        cantidad = row['cantidad']
        convergencia = row['CONVERGENCIA']
        valor =row['TOTAL MENSUALIDAD']
        if red == 'HFC' or red=='DTH':
            if convergencia == 'Convergente':
                if cantidad == 1:
                    comision_valor = comisiones_dic['hfc sencillo red dth convergente']
                elif cantidad == 2:
                    comision_valor = comisiones_dic['hfc doble hfc dth convergente']
                elif cantidad == 3:
                    comision_valor = comisiones_dic['hfc triple hfc dth convergente']
                else:
                    comision_valor = 0
                
            else:
                if cantidad == 1:
                    comision_valor = comisiones_dic['hfc sencillo red dth no convergente']
                elif cantidad == 2:
                    comision_valor = comisiones_dic['hfc doble hfc dth no convergente']
                elif cantidad == 3:
                    comision_valor = comisiones_dic['hfc triple hfc dth no convergente']
                else:
                    comision_valor = 0

            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_float = 0
        resultado = float(valor) * comision_float
        return resultado
    
    def comision_servicios_fo(row):
        red = row['RED']
        convergencia = row['CONVERGENCIA']
        valor =row['TOTAL MENSUALIDAD']

        if red == 'FO':
            if convergencia == 'Convergente':
                comision_valor = comisiones_dic['servicios fo convergente']
            else:
                comision_valor = comisiones_dic['servicios fo no convergente']
            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_float = 0
        resultado = float(valor) * comision_float
        return resultado
    
    def bono_velocidad_internet(row):
        red = row['RED']
        velocidad = row['VELOCIDAD']
        valor =row['TOTAL MENSUALIDAD']

        if red == 'FO':
            if velocidad == 'VEL_2':
                comision_valor = comisiones_dic['servicios fo vel 2']
            elif velocidad == 'VEL_3':
                comision_valor = comisiones_dic['servicios fo vel 3']
            elif velocidad == 'VEL_4':
                comision_valor = comisiones_dic['servicios fo vel 4']
            else:
                comision_valor = 0
            
            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_float = 0
        resultado = float(valor) * comision_float
        return resultado
    
    def bono_duracion_contrato(row):
        red = row['RED']
        duracion = row['DURACION CONTRATO']
        valor =row['TOTAL MENSUALIDAD']
        print(duracion, type(duracion), duracion==24)
        if red == 'FO':
            if duracion == 24:
                print('aca 24')
                comision_valor = comisiones_dic['servicios fo 24 meses']
                print(comision_valor)
            elif duracion == 36:
                print('aca 36')
                comision_valor = comisiones_dic['servicios fo 36 meses']
            elif duracion >= 48:
                print('aca 48')
                comision_valor = comisiones_dic['servicios fo 48 meses']
            else:
                comision_valor = 0
            
            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_valor = 0
            comision_float = 0
        resultado = float(valor) * comision_float
        print(resultado, valor, comision_float, comision_valor)
        return resultado
    
    def servicio_cloud_iaas(row):
        red = row['RED']
        duracion = row['DURACION CONTRATO']
        valor =row['TOTAL MENSUALIDAD']

        if red == 'FO':
            if duracion == 24:
                comision_valor = comisiones_dic['servicios fo 24 meses']
            elif duracion == 36:
                comision_valor = comisiones_dic['servicios fo 36 meses']
            elif duracion >= 48:
                comision_valor = comisiones_dic['servicios fo 48 meses']
            else:
                comision_valor = 0
            
            comision_float = float(str(comision_valor).replace('%','')) / 100
        else:
            comision_float = 0
        resultado = float(valor) * comision_float
        return resultado

    
    print('activado calcular comisiones')
    items = request.data['data']
    df = pd.DataFrame(items)
    df['comision servicios hfc'] = df.apply(comision_servicios_hfc, axis=1)
    df['guia_llave'] = df['LLAVE'].str[:17]
    paquetes = df.copy()
    paquetes['LLAVE2'] = paquetes['LLAVE'].str[:17]
    paquetes['cantidad'] = paquetes['LLAVE2']
    paquetes = paquetes[['LLAVE2', 'cantidad']].groupby(['LLAVE2']).count().reset_index()
    df = pd.merge(df, paquetes, left_on='guia_llave', right_on='LLAVE2', how='left')
    df['aceleradores hfc'] = df.apply(aceleradores_hfc, axis=1)
    df['comision servicios fo'] = df.apply(comision_servicios_fo, axis=1)
    df['bono velocidad internet'] = df.apply(bono_velocidad_internet, axis=1)
    df['bono duracion contrato'] = df.apply(bono_duracion_contrato, axis=1)

    print(paquetes)


    # for valorT in items:
    #     for clave in valorT:
    #         valor = valorT[clave]   
    #         if not isinstance(valor, float) or valor == float('inf') or valor == float('-inf') or valor != valor:
    #             print('este es el valor', valor)

    agregados =[
        'comision servicios hfc',
        'aceleradores hfc',
        'comision servicios fo',
        'bono velocidad internet',
        'bono duracion contrato',
    ]
    df['Total'] = df[agregados].sum(axis=1)
    df['TOTAL MENSUALIDAD'] = pd.to_numeric(df['TOTAL MENSUALIDAD'], errors='coerce')
    df['Porcentaje total'] = df['Total'] / df['TOTAL MENSUALIDAD'] * 100
    df['Porcentaje total'] = df['Porcentaje total'].astype(str) + '%'

    agregados.append('Total')
    agregados.append('Porcentaje total')

    df = df.drop(['guia_llave','LLAVE2','cantidad'], axis=1)
    df.fillna(0, inplace=True)
    df = df.astype(str)
    lista_df = df.to_dict(orient='records')

    return Response({'data': lista_df, 'agregados': agregados})

@api_view(['GET', 'POST'])
def porcentajes_comisiones(request):
    porcentajes = [
        'hfc new cross selling no convergente',
        'hfc new cross selling convergente',
        'hfc up selling no convergente',
        'hfc up selling convergente',
        'hfc sencillo red dth no convergente',
        'hfc sencillo red dth convergente',
        'hfc doble hfc dth no convergente',
        'hfc doble hfc dth convergente',
        'hfc triple hfc dth no convergente',
        'hfc triple hfc dth convergente',
        'total fijo 100-104,99% 1',
        'total fijo 105-109,99% 1',
        'total fijo 110-124,99% 1',
        'total fijo 125% 1',
        'total fijo 100-104,99% 2',
        'total fijo 105-109,99% 2',
        'total fijo 110-124,99% 2',
        'total fijo 125% 2',
        'total movil 80-89,99% 1',
        'total movil 90-109,99% 1',
        'total movil 110-124,99% 1',
        'total movil 125% 1',
        'total movil 80-89,99% 2',
        'total movil 90-109,99% 2',
        'total movil 110-124,99% 2',
        'total movil 125% 2',
        'servicios fo no convergente',
        'servicios fo convergente',
        'servicios fo vel 2',
        'servicios fo vel 3',
        'servicios fo vel 4',
        'servicios fo 24 meses',
        'servicios fo 36 meses',
        'servicios fo 48 meses',
        'servicios fo 0-49,9%',
        'servicios fo 50-79,9%',
        'servicios fo 80-99,9%',
        'servicios fo 100-104,9%',
        'servicios fo 105-109,9%',
        'servicios fo 110%',
        'iaas no convergente mes 1',
        'iaas convergente mes 1',
        'iaas no convergente mes 2',
        'iaas convergente mes 2',
        'iaas no convergente mes 3',
        'iaas convergente mes 3',
        'iaas no convergente mes 4',
        'iaas convergente mes 4',
        'saas no convergente mes 1',
        'saas convergente mes 1',
        'saas no convergente mes 2',
        'saas convergente mes 2',
        'saas no convergente mes 3',
        'saas convergente mes 3',
        'saas no convergente mes 4',
        'saas convergente mes 4',
    ]
    data_consulta = models.Porcentaje_comision.objects.all()
    df = list(data_consulta.values())
    diccionario = {i['nombre']:i['valor'] for i in df}
    
    if request.method == 'GET':
        data =[diccionario[i] for i in porcentajes]
        return Response({'comisiones':data})
    
    if request.method == 'POST':
        data_request = request.data
        save_data = [{'nombre':porcentajes[i], 'valor': data_request[i]} for i in range(len(porcentajes)) if data_request[i] != diccionario[porcentajes[i]]]
        print(save_data)
        for i in save_data:
            porcentaje = models.Porcentaje_comision.objects.get(nombre=i['nombre'])
            porcentaje.valor = i['valor']
            porcentaje.save()
        return Response({'respuesta':'data guardada'})

@api_view(['POST'])
def excel_precios(request):
    sin_data = '999999999.00'
    titulos = [
        'Producto',
        'Costo Actual',
        'Precio Publico Sin Iva',
        'Subdistribuidor Sin Iva',
        'Addi',
        'Cliente 0 A 5 Meses Sin Iva',
        'Cliente 6 A 23 Meses Sin Iva',
        'Cliente Mayor A 24 Meses Sin Iva',
        'Cliente Descuento Kit Prepago Sin Iva',
        'Sistecredito Sin Iva',
        'Premium Sin Iva',
        'Tramitar Sin Iva',
        'People Sin Iva',
        'Flamingo Sin Iva',
        'Fintech Oficinas Team Y Externos Sin Iva',
        'Fintech Zonificacion Subdistribuidores Y Externos Sin Iva',
        'Oficina Movil Sin Iva',
        'Cenestel',
        ]
    titulos_diccionario = {
        'Producto': 'Equipo',
        'Costo Actual': 'Costo',
        'Precio Publico Sin Iva': 'Precio publico',
        'Subdistribuidor Sin Iva': 'Precio sub',
        'Addi': 'Precio Addi',
        'Cliente 0 A 5 Meses Sin Iva': None,
        'Cliente 6 A 23 Meses Sin Iva': None,
        'Cliente Mayor A 24 Meses Sin Iva': None,
        'Cliente Descuento Kit Prepago Sin Iva': 'Precio Cliente Kit Prepago',
        'Sistecredito Sin Iva': None,
        'Premium Sin Iva': 'Precio premium',
        'Tramitar Sin Iva': None,
        'People Sin Iva': None,
        'Flamingo Sin Iva': 'Precio Flamingo',
        'Fintech Oficinas Team Y Externos Sin Iva': 'Precio Fintech',
        'Fintech Zonificacion Subdistribuidores Y Externos Sin Iva': None,
        'Oficina Movil Sin Iva': None,
        'Cenestel': None,
    }
    cabecera = request.data['cabecera']
    for key, value in titulos_diccionario.items():
        for i in cabecera:
            if value == i['text']:
                titulos_diccionario[key] = i['value']
                print('....................................1')
                print(value, key, i['value'])
                print('....................................1')

    data = [titulos]

    items = request.data['items']
    for precio in items:
        temp_fila = []
        for titulo in titulos:
            if titulos_diccionario[titulo] is None:
                temp_fila.append(sin_data)
            else:
                print('---------------------------------------------------------')
                print(titulos_diccionario)
                print(titulo)
                print(precio)
                print('--------------------------------')
                temp_fila.append(precio[int(titulos_diccionario[titulo])])
        data.append(temp_fila)
    
    return Response({'excel':data})

@api_view(['POST'])
def guardar_precios(request):
    cabecera = request.data['cabecera']
    items = request.data['items']
    
    for precio in items:
        for i in range(1,len(cabecera)):
            producto = precio[0]
            nombre = cabecera[i]['text']
            valor = precio[i]
            print(producto, nombre, valor)
            models.Lista_precio.objects.create(
                producto= producto,
                nombre = nombre,
                valor = valor
            )
            
    return Response({'data':'data'})


@api_view(['POST'])
def consultar_formula(request):
    nombre = request.data['nombre']
    print(nombre)
    consulta = models.Formula.objects.filter(nombre=nombre).first()
    formula = consulta.formula
    formula_lista = ast.literal_eval(formula)
    print(consulta.formula)
    # formula_lista = []
    return Response({'formula':formula_lista})




@api_view(['POST'])
def guardar_formula(request):
    formula = request.data['funtion']
    nombre = request.data['nombre']
    texto = str(formula)
    token = request.data['jwt']
    try:
        payload = jwt.decode(token, 'secret', algorithms='HS256')
        usuario = User.objects.get(username=payload['id'])
    except:
        raise AuthenticationFailed('Error con usuario')
    formula_obj, created = models.Formula.objects.get_or_create(
        nombre=nombre,
        defaults={
            'formula': texto,
            'usuario': usuario,
        }
    )

    if not created:
        # El objeto ya existía, actualiza los campos necesarios
        formula_obj.formula = formula
        formula_obj.usuario = usuario
        formula_obj.save()

    return Response({'data':''})


@api_view(['POST'])
def prueba_formula(request):
    formula = request.data['funtion']
    diccionario = request.data['dic']
    nombre = request.data['nombre']
    formula = ' '.join(formula)
    variables = {k: float(v) for k, v in diccionario.items()}
    consulta = models.Formula.objects.filter(nombre='Precio publico').first()
    formula_publico = consulta.formula
    formula_lista = ast.literal_eval(formula_publico)
    formula2 = ' '.join(formula_lista)
    formula = formula.replace('precioPublico',formula2)
    formula = formula.replace('=','==')
    formula = formula.replace('> ==','>=')
    formula = formula.replace('< ==','<=')
    resultado = eval(formula, variables)
    print(formula)
    print(diccionario)
    print(resultado)
    print(nombre)
    return Response({'data':resultado})

@api_view(['POST'])
def contactanos(request):
    nombre = request.data['nombre']
    correo = request.data['correo']
    asunto = request.data['asunto']
    mensaje = request.data['mensaje']
    models.Contactanos.objects.create(
        nombre = nombre,
        correo = correo,
        asunto = asunto,
        mensaje = mensaje,
    )
    return Response({'data':'data'})

@api_view(['POST'])
def informes(request):
    start = request.data['start']
    end = request.data['end']
    arrowup='\u25B2'
    arrowdown = '\u25BC'
    fecha_inicio_2023 = datetime.datetime(int(start[0:4]), int(start[5:7]), int(start[8:10]))
    fecha_fin_2023 = datetime.datetime(int(end[0:4]), int(end[5:7]), int(end[8:10]), 23, 59, 59)
    fecha_inicio_2023_sql = fecha_inicio_2023.strftime('%Y-%m-%d %H:%M:%S')
    fecha_fin_2023_sql = fecha_fin_2023.strftime('%Y-%m-%d %H:%M:%S')
    query = (
        f"SELECT Fac.Numero, Fac.Fecha, Ter.Identificacion,  "
        f"ValorBruto, ValorIva, ValorDescuento, ValorFlete, "
        f"ReteFuente, ReteIca, ReteIva, OtroImp1, OtroImp2, "
        f"ValorNeto, Ubi.Nombre "
        f"FROM dbo.Facturas Fac "
        f"JOIN dbo.Terceros Ter ON Fac.Tercero = Ter.Codigo "
        f"JOIN dbo.Ubicaciones Ubi ON Fac.Ubicacion = Ubi.Codigo "
        f"WHERE Fecha >= '{fecha_inicio_2023_sql}' AND Fecha <= '{fecha_fin_2023_sql}'"
    )
    conexion = Sql_conexion(query)
    rows = conexion.get_data()
    columns = [column[0] for column in conexion.description]
    print(columns)
    columns[len(columns)-1] = 'Ubicacion'
    # columns.append('Ubicacion')
    df = pd.DataFrame.from_records(rows, columns=columns)
    periodo = 'mes' if (fecha_fin_2023 - fecha_inicio_2023).days > 31 else 'dia'
    if periodo == 'mes':
        df['Fecha'] = df['Fecha'].dt.strftime('%Y-%m')
    if periodo == 'dia':
        df['Fecha'] = df['Fecha'].dt.strftime('%Y-%m-%d')
    ventasPeriodo = df[['ValorNeto', 'Fecha']].groupby('Fecha').sum().reset_index()
    print(fecha_inicio_2023_sql)
    print(fecha_fin_2023_sql)
    median = ventasPeriodo['ValorNeto'][:-1].median()
    ultimoValor = float(ventasPeriodo['ValorNeto'].iloc[-1])
    periodo = (ventasPeriodo['Fecha'].iloc[-1])
    delta = round((ultimoValor- median) / median * 100, 2)
    if delta > 0:
        arrow = arrowup
        color = '#c0ca33'
    else:
        arrow = arrowdown
        delta = delta * -1
        color = '#f4511e'
    delta = f'{arrow}{delta}%'
    ultimoValor = f'${formating_numbers(ultimoValor)}'
    label = ventasPeriodo['Fecha'].tolist()
    values = ventasPeriodo['ValorNeto'].tolist()

    ubicaciones = df[['ValorNeto', 'Ubicacion']].groupby('Ubicacion').sum().reset_index()
    labelPie = ubicaciones['Ubicacion'].tolist()
    valuesPie = ubicaciones['ValorNeto'].tolist()
    cantidadPie = len(ubicaciones)

    query2 =(
        f"SELECT Pro.Nombre, Df.Cantidad, Df.PrecioVenta "
        f"FROM dbo.DetallesXFacturas Df "
        f"JOIN dbo.Facturas Fac ON Df.Factura = Fac.Codigo "
        f"JOIN dbo.Productos Pro ON Df.Producto = Pro.Codigo "
        f"WHERE Fac.Fecha >= '{fecha_inicio_2023_sql}' AND Fac.Fecha <= '{fecha_fin_2023_sql}'"
    )

    conexion = Sql_conexion(query2)
    columns = [column[0] for column in conexion.description]
    rows = conexion.get_data()
    df = pd.DataFrame.from_records(rows, columns=columns)
    productos = df[['Nombre', 'Cantidad', 'PrecioVenta']].groupby('Nombre').sum().reset_index()
    productos = productos.sort_values(by='Cantidad', ascending=False)
    productos = productos.head(5)
    productos['PrecioVenta'] = productos['PrecioVenta'].astype(float)
    listaProductos = productos.to_dict(orient='records')


    data = {
        'median': str(median),
        'ultimoValor': str(ultimoValor),
        'delta': str(delta),
        'periodo': periodo,
        'color': color,
        'label': label,
        'values': values,
        'productos': listaProductos,
        'labelPie': labelPie,
        'valuesPie' : valuesPie,
        'cantidadPie': cantidadPie,
    }
    print(data)

    return Response(data)

@api_view(['GET'])
def tienda(request):
    plan = models.Imagenes.objects.all()
    data = []
    for i in plan:
        print(i.id)
        data.append({
            'id':i.id, 
            'img':i.url, 
            'titulo':i.titulo, 
            'detalle':i.detalle, 
            'precio':i.precio,
            'marca':i.marca,
            })
    return Response({'data':data})

@api_view(['GET'])
def productos(request):
    plan = models.Imagenes.objects.filter(carpeta='productos')
    data = []
    for i in plan:
        print(i.id)
        data.append({'id':i.id, 'img':i.url, 'titulo':i.titulo, 'detalle':i.detalle, 'precio':i.precio})
    return Response({'data':data})

@api_view(['GET'])
def planes(request):
    plan = models.Imagenes.objects.filter(carpeta='planes')
    data = []
    for i in plan:
        print(i.id)
        data.append({'id':i.id, 'img':i.url, 'titulo':i.titulo, 'detalle':i.detalle, 'precio':i.precio})
    return Response({'data':data})

@api_view(['POST'])
def cargarImagen(request):
    nombre = str(uuid.uuid4()) +'.png'
    titulo = request.POST.get('titulo')
    detalle = request.POST.get('detalle')
    precio = request.POST.get('valor')
    imagen = request.FILES.get('imagen')
    carpeta = request.POST.get('carpeta')
    print(type(imagen))
    ruta_carpeta_destino = ''
    ruta_carpeta_destino2 = ruta + '\\'+carpeta+'\\'
    if not default_storage.exists(ruta_carpeta_destino):
        default_storage.makedirs(ruta_carpeta_destino)
    nueva_ruta_imagen = default_storage.path(os.path.join(ruta_carpeta_destino, nombre))
    with default_storage.open(nueva_ruta_imagen, 'wb') as destino:
        destino.write(imagen.read())
    ruta_carpeta_destino = os.path.join(ruta_carpeta_destino, nombre)
    shutil.move(ruta_carpeta_destino, ruta_carpeta_destino2)
    models.Imagenes.objects.create(
        url = nombre,
        titulo = titulo,
        detalle = detalle,
        precio = precio,
        carpeta = carpeta,
    )

    return Response({'data':'d'})

@api_view(['POST'])
def deleteImagen(request):
    id = request.data['id']
    objeto = models.Imagenes.objects.get(id=id)
    nombre = objeto.url
    carpeta = request.data['carpeta']
    ruta_carpeta_destino = ruta + '\\'+carpeta+'\\'
    objeto.delete()
    ruta_eliminar = os.path.join(ruta_carpeta_destino, nombre)
    os.remove(ruta_eliminar)
    return Response({'data':'d'})


def shopify_token(request):
    api_key = 'd37d57aff7101337661ae6594f0f38d5'	#Set Partner app api key
    api_secret = '3ec5b155828a868687ef85444f88601f' #Set Partner app api secret
    scopes = 'write_products,read_content,read_discounts,read_locales'
    redirect_uri = 'https://api.teamcomunicaciones.com.co/api/v1.0/shopify-return'
    shop = 'quickstart-06207d6f.myshopify.com'
    nonce = random.random() 
    url = "https://{}/admin/oauth/authorize?client_id={}&scope={}&redirect_uri={}&state={}&grant_options[]=offline-access".format(shop, api_key,  scopes, redirect_uri, nonce)
    return redirect(url)

@api_view(['GET'])
def shopify_return(request):
    api_key = 'd37d57aff7101337661ae6594f0f38d5'	#Set Partner app api key
    api_secret = '3ec5b155828a868687ef85444f88601f' #Set Partner app api secret
    code = request.GET.get('code', '')
    shop = request.GET.get('shop', '')
    url = 'https://{}/admin/oauth/access_token'.format(shop)
    myobj = {'client_id': api_key,'client_secret': api_secret,'code': code}

    x = requests.post(url, data = myobj)
    respuesta = x.json()['access_token']
    return Response({"message":respuesta, "code": code})
    

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
                'iat' : datetime.datetime.utcnow(),
                'change': True if password == 'Cambiame123' else False
            }
            token = jwt.encode(payload, 'secret', algorithm='HS256')
            response = Response()
            response.set_cookie(key='jwt', value=token, httponly=True)
            response.data = {
                'jwt':token,
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
        return Response({"cambioClave": False})

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
            if payload['change']:
                return Response({"cambioClave": True})
            usuario = User.objects.get(username=payload['id'])
            permisos_ind = models.Permisos_usuarios.objects.filter(
                user= usuario
            )
            
            # new_permiso = models.Permisos.objects.create(
            #     permiso ='informes',
            #     active=True
            # )
            # new_permiso.save()

            permisos = {
                'superadmin' : usuario.is_superuser,
                'administrador' : {
                    'main': False,
                },
                'informes':{
                    'main':False,
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
                'corresponsal' : {
                    'main': False,
                },
                'caja' : {
                    'main': False,
                },
            }
            for i in permisos_ind:
                permisos[i.permiso.permiso]['main'] = i.tiene_permiso
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Debes estar logueado')
        return Response({"permisos":permisos, "cambioClave": False})

@api_view(['POST'])
def cambio_clave(request):
    print('d')
    if request.method == 'POST':
        contraseña = request.data['password']
        contraseña2 = request.data['retrypassword']
        token = request.data['jwt']
        if contraseña == contraseña2:
            print(contraseña, contraseña2, token)
            if not token:
                raise AuthenticationFailed('Debes estar logueado')
            try:
                payload = jwt.decode(token, 'secret', algorithms='HS256')
                usuario = User.objects.get(username=payload['id'])
            except jwt.ExpiredSignatureError:
                raise AuthenticationFailed('Debes estar logueado')
            
            usuario.set_password(contraseña)
            usuario.save()
            return Response({"usuarios": ''})
        else:
            raise AuthenticationFailed('Las contraseñas deben ser iguales')

@api_view(['POST'])
def permissions(request):
    if request.method == 'POST':
        # new_permiso = models.Permisos.objects.create(
        #         permiso ='informes',
        #         active=True
        #     )
        # new_permiso.save()
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
                administrador = models.Permisos_usuarios.objects.filter(user=i.id, permiso=1)
                control_interno = models.Permisos_usuarios.objects.filter(user=i.id, permiso=2)
                gestion_humana = models.Permisos_usuarios.objects.filter(user=i.id, permiso=3)
                contabilidad = models.Permisos_usuarios.objects.filter(user=i.id, permiso=4)
                comisiones = models.Permisos_usuarios.objects.filter(user=i.id, permiso=5)
                soporte = models.Permisos_usuarios.objects.filter(user=i.id, permiso=6)
                auditoria = models.Permisos_usuarios.objects.filter(user=i.id, permiso=7)
                comercial = models.Permisos_usuarios.objects.filter(user=i.id, permiso=8)
                informes= models.Permisos_usuarios.objects.filter(user=i.id, permiso=9)
                corresponsal= models.Permisos_usuarios.objects.filter(user=i.id, permiso=10)
                data.append({
                    'usuario': i.username,
                    'administrador': administrador[0].tiene_permiso if len(administrador)>0 else False,
                    'informes': informes[0].tiene_permiso if len(informes) >0 else False,
                    'control_interno': control_interno[0].tiene_permiso if len(control_interno)>0 else False,
                    'gestion_humana': gestion_humana[0].tiene_permiso if len(gestion_humana)>0 else False,
                    'contabilidad': contabilidad[0].tiene_permiso if len(contabilidad)>0 else False,
                    'comisiones': comisiones[0].tiene_permiso if len(comisiones)>0 else False,
                    'soporte': soporte[0].tiene_permiso if len(soporte)>0 else False,
                    'auditoria': auditoria[0].tiene_permiso if len(auditoria)>0 else False,
                    'comercial': comercial[0].tiene_permiso if len(comercial)>0 else False,
                    'corresponsal': comercial[0].tiene_permiso if len(corresponsal)>0 else False,
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
            validacion = nstok == stok[0]
            if validacion == False:
                raise AuthenticationFailed(f'intente usar {nstok} y no {stok[0]}')
        
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
        iva = 1035430
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
            'valor', 
            'descuento', 
            'costo',
            'precioConIva',
        ]
        equipos_origen = df_equipos[df_equipos.columns[0]]
        equipos_translate = df_translates['equipo']
        equipos_no_encontrados = equipos_origen[~equipos_origen.isin(equipos_translate)]
        crediminuto = []
        if len(equipos_no_encontrados) > 0:
            validate = False
            data = equipos_no_encontrados.to_list()
            cabecera = []
        else:
            validate = True
            nuevo_df = df_equipos.merge(df_translates, on='equipo', how='left')
            nuevo_df = nuevo_df.drop_duplicates()
            data =[]
            precios = models.Formula.objects.all()
            cabecera = [{'text':'Equipo', 'value':'0'}]
            contador = 1
            for i in precios:
                cabecera.append({'text':i.nombre, 'value':str(contador)})
                contador += 1
                if 'Precio Fintech' in i.nombre:
                    cabecera.append({'text':'Kit Fintech', 'value':str(contador)})
                    contador += 1
                elif 'Precio Addi' in i.nombre:
                    cabecera.append({'text':'Kit Addi', 'value':str(contador)})
                    contador += 1
                elif 'Precio sub' in i.nombre:
                    cabecera.append({'text':'Kit Sub', 'value':str(contador)})
                    contador += 1
            cabecera.append({'text':'descuento', 'value':str(contador)})
            lista_produtos = []
            for index, row in nuevo_df.iterrows():
                if row['stok'] in lista_produtos:
                    continue
                lista_produtos.append(row['stok'])
                temp_data =[row['stok']]
                for precio in precios:
                    dict_formula = ast.literal_eval(precio.formula)
                    formula = ' '.join(dict_formula)
                    consulta2 = models.Formula.objects.filter(nombre='Precio publico').first()
                    formula_publico = consulta2.formula
                    formula_lista = ast.literal_eval(formula_publico)
                    formula2 = ' '.join(formula_lista)
                    formula = formula.replace('precioPublico',formula2)
                    formula = formula.replace('=','==')
                    formula = formula.replace('> ==','>=')
                    formula = formula.replace('< ==','<=')
                    variables = {
                        'valor':row['valor'],
                        'costo':row['costo'],
                        'descuento':row['descuento'],
                        'iva': iva,
                        'precioConIva': row['precioConIva']
                    }
                    kit = 0
                    kit_comprobante = False
                    resultado = eval(formula, variables)
                    if 'Precio Fintech' in precio.nombre or 'Precio Addi' in precio.nombre:
                        kit_comprobante = True
                        if resultado >= iva and row['valor'] < iva:
                            kit = resultado - 1032620
                            resultado = 1032620
                    elif 'Precio sub' in precio.nombre:
                        kit_comprobante = True
                        if resultado < iva and row['valor'] >= iva:
                            kit = resultado * 0.19
                    temp_data.append(resultado)
                    if kit_comprobante:
                        temp_data.append(kit)
                temp_data.append(row['descuento'])
                data.append(temp_data)
            # print(cabecera)
        return Response({'validate': validate, 'data':data, 'crediminuto':crediminuto, 'cabecera':cabecera})
@api_view(['PUT', 'POST'])
def lista_productos_prepago_equipo(requests):
    if requests.method == 'POST':
        precio = requests.data['precio']
        equipo = requests.data['equipo']
        print(precio, equipo)
        new_data = []
        data = models.Lista_precio.objects.all()
        df = pd.DataFrame(list(data.values()))
        df['dia'] = pd.to_datetime(df['dia'])
        df['valor'] = df['valor'].astype(float)

        df_resultado = df[(df['producto'] == equipo) & (df['nombre'] == precio)]
       

        for index, row in df_resultado.iterrows():
           
            tem_data = {
                'equipo': row['producto'],
                'valor sin iva': '${:,.2f}'.format(row['valor']),
                'fecha': row['dia'],
    
            }
            new_data.append(tem_data)
        
        print(new_data)

        return Response({'data' : new_data})


@api_view(['PUT', 'POST'])
def lista_productos_prepago(requests):
    if requests.method == 'PUT':
        traduccion = {
            'Precio publico':'Precio Publico',
            'Precio sub':'Subdistribuidor',
            'Precio premium':'Premium',
            'Precio Fintech':'Fintech Zonificacion Subdistribuidores Y Externos',
            'Precio Addi':'Addi',
            'Precio Flamingo':'Flamingo',
            'Costo':'Costo',
        }
        lista_precios = []
        token = requests.data['jwt']
        payload = jwt.decode(token, 'secret', algorithms='HS256')
        usuario = User.objects.get(username=payload['id'])
        listas = models.Permisos_usuarios_precio.objects.filter(user= usuario.id)
        for i in listas:
            permiso = i.permiso.permiso
            print(permiso)
            lista_precios.append({'id':permiso, 'nombre':traduccion[permiso]})
        

        return Response({'data' : lista_precios})
    
    if requests.method == 'POST':   
        new_data = []
        productos = []
        precio = requests.data['precio']
        

        data = models.Lista_precio.objects.all()
        df = pd.DataFrame(list(data.values()))
        df['dia'] = pd.to_datetime(df['dia'])
        df['valor'] = df['valor'].astype(float)

        df_descuentos = df[df['nombre'] == 'descuento']
        df_descuentos = df_descuentos.sort_values('dia', ascending=False).drop_duplicates('nombre').reset_index(drop=True)
        df_descuentos = df_descuentos.rename(columns={'valor': 'descuento'})

        df_filtrado = df[df['nombre'] == precio]
        
        df_resultado = df_filtrado.sort_values('dia', ascending=False).drop_duplicates('producto').reset_index(drop=True)
        
        df_resultado = pd.merge(df_resultado, df_descuentos[['producto', 'descuento']], on='producto', how='left')

        df_kit_addi = df[df['nombre'] == 'Kit Addi']
        df_kit_addi = df_kit_addi.sort_values('dia', ascending=False).drop_duplicates('producto').reset_index(drop=True)
        df_kit_addi = df_kit_addi.rename(columns={'valor': 'kit addi'})
        df_resultado = pd.merge(df_resultado, df_kit_addi[['producto', 'kit addi']], on='producto', how='left')

        df_kit_fintech = df[df['nombre'] == 'Kit Fintech']
        df_kit_fintech = df_kit_fintech.sort_values('dia', ascending=False).drop_duplicates('producto').reset_index(drop=True)
        df_kit_fintech = df_kit_fintech.rename(columns={'valor': 'kit fintech'})
        df_resultado = pd.merge(df_resultado, df_kit_fintech[['producto', 'kit fintech']], on='producto', how='left')


        df_kit_sub = df[df['nombre'] == 'Kit Sub']
        df_kit_sub = df_kit_sub.sort_values('dia', ascending=False).drop_duplicates('producto').reset_index(drop=True)
        df_kit_sub = df_kit_sub.rename(columns={'valor': 'kit sub'})
        df_resultado = pd.merge(df_resultado, df_kit_sub[['producto', 'kit sub']], on='producto', how='left')

        df_costo = df[df['nombre'] == 'Costo']
        df_costo = df_costo.sort_values('dia', ascending=False).drop_duplicates('producto').reset_index(drop=True)
        df_costo = df_costo.rename(columns={'valor': 'costo'})
        df_resultado = pd.merge(df_resultado, df_costo[['producto', 'costo']], on='producto', how='left')
        


        sim = 2000
        base = 1035430

        for index, row in df_resultado.iterrows():
            if precio == 'Costo':
                tem_data = {
                    'equipo': row['producto'],
                    'costo': '${:,.2f}'.format(row['costo']),
                    'descuento': '${:,.2f}'.format(row['descuento']),
                    'total': '${:,.2f}'.format(row['costo'] - row['descuento']),
                }
                new_data.append(tem_data)
            else:
                valor = row['valor']
                iva = row['valor'] * 0.19 if row['valor'] >= base else 0
                total = sim * 1.19 + valor + iva
                tem_data = {
                    'equipo': row['producto'],
                    'precio simcard': '${:,.2f}'.format(sim),
                    'IVA simcard': '${:,.2f}'.format(sim * 0.19),
                    'equipo sin IVA': '${:,.2f}'.format(valor),
                    'IVA equipo': '${:,.2f}'.format(iva),
                }
                if precio == 'Precio sub':
                    kit = row['kit sub']
                    tem_data['KIT'] = kit
                    total = total + kit
                elif precio == 'Precio Fintech':
                    kit = row['kit fintech']
                    tem_data['KIT'] = kit
                    total = total + kit
                elif precio == 'Precio Addi':
                    kit = row['kit addi']
                    tem_data['KIT'] = kit
                    total = total + kit
                
                tem_data['total'] = '${:,.2f}'.format(total)
                if precio == 'Precio publico':
                    tem_data['Promo'] = 'PROMO' if row['descuento'] >0 else 'NO'
                new_data.append(tem_data)

        return Response({'data' : new_data})

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

def formating_numbers(number, type_value=''):
    if type_value != 'Money':
        if number >= 1000000000:
            formated_number = str(round(number/1000000000, 2)) + 'B'
        elif number >= 1000000:
            formated_number = str(round(number/1000000, 2)) + 'M'
        elif number >= 1000:
            formated_number = str(round(number/1000, 2)) + 'K'
        else:
            formated_number = str(round(number, 2))
    else:
        formated_number = str(f'{number:,.2f}')
    return formated_number

# def restablecerContraseña(id):
#     usuario = User.objects.get(username=id)
#     usuario.set_password('Cambiame123')
#     usuario.save()


def generate_unique_filename(filename):
            # Obtener la extensión del archivo
            file_extension = filename.split('.')[-1]
            # Obtener la fecha y hora actual
            current_time = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
            # Generar una cadena aleatoria de 6 caracteres
            random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
            # Combinar para crear un nombre único
            unique_filename = f"{current_time}_{random_string}.{file_extension}"
            return unique_filename