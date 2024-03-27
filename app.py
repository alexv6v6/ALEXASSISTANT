# Importar librerías
import streamlit as st
import random
import openai
import time
from PIL import Image
import io
from datetime import datetime
#from dotenv import load_dotenv
import os
import base64
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from googleapiclient.http import MediaIoBaseDownload
import zipfile
import json
import pytz
#import pandas_gbq
import requests
import pandas as pd
import numpy as np
import sqlite3

# Inicialización de la API de OpenAI
client = openai

#load_dotenv()
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
ASSISTANT_ID = st.secrets["ASSISTANT_ID"]
FILE_ID_DB = st.secrets["FILE_ID_DB"]
PROJECT_ID = st.secrets["PROJECT_ID"]
USER = st.secrets["USER"]
PASSWORD = st.secrets["PASSWORD"]    

# Inicializar la API de OpenAI, dandole la llave de la API
openai.api_key = OPENAI_API_KEY

# Configurar la página de Streamlit con un título e ícono	
st.set_page_config(page_title="Asistente IA UManizales", page_icon="./images/logo.jpeg", layout="centered")

# Inicialiar variables de la sesión
if 'uploaded_files_id' not in st.session_state:
    st.session_state.uploaded_files_id = None

if "last_openai_run_state" not in st.session_state:
    st.session_state.last_openai_run_state = None

if 'instructions' not in st.session_state:
    st.session_state.instructions = None

if "openai_model" not in st.session_state:
    st.session_state.openai_model = "gpt-4-1106-preview"

if "messages" not in st.session_state:
    st.session_state.messages = []

# Constants
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'key.json'
MIME_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

def obtener_hora():
    try:
        # Obtener la hora actual
        hora_actual = datetime.now()
        # Formatear la hora como una cadena
        hora_formateada = hora_actual.strftime("%H:%M:%S")
        return hora_formateada
    except Exception as e:
        print("Error al obtener la hora:", e)
        return None

def limpiar_historial_chat():
    msg_bienvenida="👋 Hola, soy el Asistente IA. Puedo responder a cualquier pregunta que tengas. ¿Le puedo ayudar en algo?"
    st.session_state.messages = [{"role": "assistant", "content": msg_bienvenida, "type": "text"}]
    if "thread_id" in st.session_state:
        # Crear un nuevo hilo de conversación solo si ya existe uno
        thread = client.beta.threads.create()
        st.session_state.thread_id = thread.id
        #st.write("Identificador de la conversación nueva: ", thread.id)

def upload_file_to_openai(file_path):
    try:
        with open(file_path, "rb") as file:
            uploaded_file = client.files.create(file=file, purpose='assistants')
        return uploaded_file.id
    except Exception as e:
        st.error(f"Error al cargar el archivo: {e}", icon="🚨")
        return None

# Función para eliminar un archivo de forma silenciosa
def silent_delete(file_path):
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except:
        # Si surge un error, no hace nada y continúa
        pass

def download_file_from_drive(FILE_ID_DB, out_name):
    """Downloads an Excel file from Google Drive."""
    try:
        with st.spinner('Actualizando asistente...'):
            try:
                credentials_dict = json.loads(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
            except:
                credentials_dict = json.loads(st.secrets["google"]["GOOGLE_APPLICATION_CREDENTIALS"])

            credentials = Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
            service = build('drive', 'v3', credentials=credentials)
            request = service.files().export_media(fileId=FILE_ID_DB, mimeType=MIME_TYPE)

            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)

            # Create the directory if it doesn't exist
            if not os.path.exists('files'):
                os.makedirs('files')

            done = False
            while not done:
                _, done = downloader.next_chunk()

            # Save the file
            out_path = os.path.join('files', f"{out_name}.xlsx")
            with open(out_path, 'wb') as f:
                fh.seek(0)
                f.write(fh.read())
            
            excel_path = os.path.join('files', f"{out_name}.xlsx")
            zip_path = os.path.join('files', f"{out_name}.zip")
            # Ahora guarda el archivo Excel dentro de un archivo ZIP
            with zipfile.ZipFile(zip_path, 'w') as myzip:
                myzip.write(excel_path, arcname=f"{out_name}.xlsx")
            
            uploaded_FILE_ID_DB = upload_file_to_openai(zip_path)
            #st.write(uploaded_FILE_ID_DB)
            
            if uploaded_FILE_ID_DB:
                client.beta.assistants.update(assistant_id=ASSISTANT_ID,file_ids=[uploaded_FILE_ID_DB])

                metadata_path = os.path.join('files', 'metadata.txt')
                # Establece la zona horaria de Bogotá
                bogota_zone = pytz.timezone('America/Bogota')
                # Obtiene la hora actual en la zona horaria de Bogotá
                bogota_time = datetime.now(bogota_zone).strftime('%d-%m-%Y %H:%M:%S')
                with open(metadata_path, 'w', encoding='utf-8') as meta_file:
                    meta_file.write(f"Actualizado el: {bogota_time}")

                st.success(f"Asistente actualizado: {bogota_time}", icon="✅")
                
                # Intenta eliminar ambos archivos
                silent_delete(excel_path)
                silent_delete(zip_path)
            return out_path

    except Exception as e:
        st.error(f"No se logró actualizar: {e}", icon="🚨")
        return None

@st.cache_resource(ttl=10) # Seconds
def update_assistant(FILE_ID_DB, out_name):
    """Updates the file and returns a message."""
    return download_file_from_drive(FILE_ID_DB, out_name)

out_name = "data_downloaded"  # The desired output name

def read_metadata():
    """Reads the metadata file and returns the content."""
    metadata_path = os.path.join('files', 'metadata.txt')
    try:
        with open(metadata_path, 'r') as meta_file:
            return meta_file.read()
    except FileNotFoundError:
        return "Metadata no encontrada."
    


#############################################################
# Configuración de la función de consulta en SQLite
#############################################################
# Crear la carpeta si no existe
folder_path = './data'
if not os.path.exists(folder_path):
    os.makedirs(folder_path)

def json_to_dataframe(url, username, password, table, max_attempts=5, sleep_interval=5):
    attempts = 0
    while attempts < max_attempts:
        response = requests.get(url, auth=(username, password))
        if response.status_code == 200:
            json_data = response.json()
            if table in json_data:
                data = json_data[table]
                dataframe = pd.DataFrame(data)
                return dataframe
            else:
                return f"La clave '{table}' no se encuentra en el JSON"
        else:
            print(f"Intento {attempts+1}: Error al obtener los datos: {response.status_code}")
            time.sleep(sleep_interval)  # Espera antes de reintentar
        attempts += 1
    return "Número máximo de intentos alcanzado. No se pudo obtener una respuesta exitosa."

def fun_sqlite_updating():
    #print("inicio llamada actualización")
    try:

        # Crear o abrir una conexión a un archivo de base de datos SQLite
        conn = sqlite3.connect('./data/data.db')
        # Cerrar la conexión
        conn.close()
        #print("fin llamada actualización exitosa")
        return "Actualización exitosa."

    except Exception as e:

        st.error(f"No se logró actualizar: {e}", icon="🚨")
        #print("fin llamada actualización error")
        return f"No se logró actualizar: {e}"

def fun_sqlite_consulting(query):
    #print("inicio llamada consulta")
    try:
        # Abrir una nueva conexión a la base de datos
        conn = sqlite3.connect('./data/data.db')
        # Consulta SQL
        df_query_result = pd.read_sql_query(query, conn)
        # Cerrar la conexión
        conn.close()
        # Dataframe como String
        df_string = df_query_result.to_csv(index=False, sep=',', quotechar='"')

        #print("final llamada consulta exitosa")
        return df_string

    except Exception as e:
        error = f"No fue posible la consulta: {e}" 

        #print("final llamada consulta error")
        return error
    
##############PREGUNTAR HORA
def obtener_hora():
    try:
        # Obtener la hora actual
        hora_actual = datetime.now()
        # Formatear la hora como una cadena
        hora_formateada = hora_actual.strftime("%H:%M:%S")
        return hora_formateada
    except Exception as e:
        print("Error al obtener la hora:", e)
        return None
#############################


#################################
def leer_archivo_desde_ruta():
    try:
        # Leer el archivo desde la ruta especificada
        df = pd.read_csv('C:/Users/alex_/Documents\MAESTRIA-GEI\Semestre-IV/4-Inteligencia Artificial Aplicada a la Empresa\code\data\Libro1.csv')
        # Contar el número de filas del DataFrame
        num_filas = len(df)
        return num_filas
    except Exception as e:
        print(f"Error al leer el archivo desde la ruta: {e}")
        return None, None

################
num_filas = leer_archivo_desde_ruta();
def obtener_numero_aleatorio():
    try:
        # Obtener un número aleatorio entre 1 y 10
        numero_aleatorio = random.randint(1, num_filas)
        return numero_aleatorio
    except Exception as e:
        print("Error al obtener un número aleatorio:", e)
        return None
######################

def obtener_contenido_fila_csv(num):
    try:
        # Leer el archivo CSV
        df = pd.read_csv('C:/Users/alex_/Documents\MAESTRIA-GEI\Semestre-IV/4-Inteligencia Artificial Aplicada a la Empresa\code\data\Libro1.csv')
        # Obtener el contenido de la fila especificada
        fila = df.iloc[num - 1]  # Restamos 1 para ajustarnos al índice de Python (que empieza en 0)
        fila_texto = fila.to_string(index=False)
        return fila_texto
    except Exception as e:
        print("Error al obtener el contenido ")
        return None
# Ejemplo de uso
 ####################################
    
def wait_on_run(run, thread):
    while run.status == "queued" or run.status == "in_progress":
        # print("the run is still in process, please wait a second.")
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id,
        )
        time.sleep(1)
    return run
#############################    
tool_to_function = {
    "obtener_hora": obtener_hora,
    "obtener_numero_aleatorio": obtener_numero_aleatorio, 
    "obtener_contenido_fila_csv": obtener_contenido_fila_csv,
    "wait_on_run":wait_on_run
}

with st.sidebar:    
    # Título de la página y descripción
    st.title("Asistente IA UManizales")
    st.caption("🩸 :gray[Adéntrese en el futuro con nuestro Asistente IA  conociendo informacion precisa sobre las transfusiones de sangre.]")

    # Inicializar la variable de sesión para rastrear si se deben mostrar las preguntas
    if 'mostrar_preguntas' not in st.session_state:
        st.session_state.mostrar_preguntas = False
    
    # Inicializar el estado si es necesario
    #if 'metadata_content' not in st.session_state:
    #    st.session_state.metadata_content = read_metadata()
    
    # Botón para actualizar el asistente
    #if st.sidebar.button('🔃 Actualizar el asistente', type="primary", use_container_width=True):
    #   update_assistant(FILE_ID_DB, out_name)
    #   st.session_state.metadata_content = read_metadata()
    #   limpiar_historial_chat()

    # Mostrar la metadata
    #st.caption(st.session_state.metadata_content)
    
    # Botón para alternar la visualización de las preguntas
    if st.sidebar.button('📱 Ver preguntas comunes: ON/OFF', type="primary", use_container_width=True):
        st.session_state.mostrar_preguntas = not st.session_state.mostrar_preguntas

    # Preguntas predefinidas
    preguntas = [
        "Dime por favor las  Contraindicaciones y precauciones (4, 25, 26 ) del Plasma fresco congelado",
        "¿Cuáles son los Otros componentes plasmáticos?",
        "Dosis y administración del Crioprecipitado"
    ]
    
    # HTML y CSS para estilizar las preguntas
    html_preguntas = f"""
    <div style="background-color: #7E8A9E; padding: 10px; border-radius: 10px; color: white;">
        <ul>
    """
    # Agregar cada pregunta a la lista HTML
    for pregunta in preguntas:
        html_preguntas += f"<li>{pregunta}</li>"
    # Cerrar los tags de la lista y del div
    html_preguntas += """
        </ul>
    </div>
    """

    # Si el usuario ha activado la visualización, muestra las preguntas
    if st.session_state.mostrar_preguntas:
        #st.markdown(html_preguntas, unsafe_allow_html=True)
        uploaded_file = st.file_uploader("Selecciona un archivo PDF", type="csv",accept_multiple_files=False)
        if uploaded_file is not None:
        # Crear el archivo utilizando el archivo cargado
            # Crear el archivo utilizando el archivo cargado
            file = client.files.create(
                file=uploaded_file,
                purpose='assistants'
            )
            st.write("Archivo subido:", uploaded_file.name)
            # Asignar el ID del archivo a la variable de sesión
            st.session_state.uploaded_file_id = file.id
            st.session_state.mostrar_chat = True

    # Boton para reiniciar la conversación y borrarla
    st.sidebar.button('🗑️ Borrar conversación', on_click=limpiar_historial_chat, type="primary", use_container_width=True)
    
    st.markdown("---")
    
    # Función para convertir imagen a base64
    def get_image_as_base64(path):
        with open(path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    # Ruta imagen
    image_path = "images/logo.png"
    # Convertir la imagen a base64
    image_base64 = get_image_as_base64(image_path)
    # Incrustar la imagen con base64 en HTML
    st.sidebar.markdown(f"<img src='data:image/png;base64,{image_base64}' style='width:100%;'>", unsafe_allow_html=True)

# Inicializar la variable de sesión para rastrear el estado de visualización
if 'mostrar_chat' not in st.session_state:
    st.session_state.mostrar_chat = False

# Crear tres columnas para centrar el botón
col1, col2, col3 = st.columns([1, 2, 1])

# Usar la columna del medio para centrar el botón
with col2:
    # Botón para alternar la visualización
    if st.button('Habilitar chat: ON/OFF', type="primary", use_container_width=True):
        st.session_state.mostrar_chat = not st.session_state.mostrar_chat

def get_run_id():
    return st.session_state.last_openai_run_state.id


# Si el botón ha sido presionado
if st.session_state.mostrar_chat:

    if "thread_id" not in st.session_state:
        #st.write("Prueba local")
        # Crear un nuevo hilo de conversación solo si no existe
        thread = client.beta.threads.create()
        st.session_state.thread_id = thread.id
        #st.write("Identificador de la conversación: ", thread.id)

    # Mostrar la interfaz de chat
    # Emojis para el chat
    avatar_asistente = "🤖"  # Emoji para el asistente
    avatar_usuario = "👨🏻‍💻"  # Emoji para el usuario

    # Agregar el mensaje de bienvenida solo la primera vez
    if not st.session_state.messages:
        msg_bienvenida="👋 Hola, soy el Asistente IA UManizales. Puedo responder a cualquier pregunta que tengas. ¿Le puedo ayudar en algo?"
        st.session_state.messages.append({"role": "assistant", "content": msg_bienvenida, "type": "text"})

    # Mostrar los mensajes existentes en el chat
    for message in st.session_state.messages:
        avatar = avatar_asistente if message["role"] == "assistant" else avatar_usuario
        with st.chat_message(message["role"], avatar=avatar):
            if message["type"] == "text":
                st.markdown(message["content"])
            elif message["type"] == "image":
                file_id = message["file_id"]
                try:
                    # Obtener los bytes de la imagen y crear un objeto Image
                    image_bytes = client.files.content(file_id).content
                    image = Image.open(io.BytesIO(image_bytes))

                    # Mostrar la imagen en Streamlit
                    st.image(image, caption="Imagen generada por el Asistente IA UManizales.")
                except Exception as e:
                    error_message = f"Error al cargar la imagen: {e}"
                    st.markdown(error_message) 
            else:
                try:
                    st.markdown(message["content"])
                except:
                    st.markdown("No fue posible obtener el mensaje")

    # Entrada de mensajes del usuario
    try:
        if prompt := st.chat_input("Mensaje"):
            
            # Mostrar el mensaje del usuario en el chat
            st.session_state.messages.append({"role": "user", "content": prompt, "type": "text"})
            with st.chat_message("user", avatar=avatar_usuario):
                st.markdown(prompt)

            try:        
                # Agregar el mensaje del usuario al hilo existente
                client.beta.threads.messages.create(
                    thread_id=st.session_state.thread_id,
                    role="user",
                    content=prompt,
                    file_ids=st.session_state.uploaded_files_id) # Ampliar de 1 minuto a 5 minutos para datasets grandes
                
                # Crear un nuevo run con el modelo y los archivos asociados al asistente
                st.session_state.last_openai_run_state = client.beta.threads.runs.create(
                    thread_id=st.session_state.thread_id,
                    assistant_id=ASSISTANT_ID,
                    instructions=st.session_state.instructions,
                    timeout=5*60)
            except:
                # Agregar el mensaje del usuario al hilo existente
                client.beta.threads.messages.create(
                    thread_id=st.session_state.thread_id,
                    role="user",
                    content=prompt) # Ampliar de 1 minuto a 5 minutos para datasets grandes
            
                # Crear un nuevo run con el modelo y los archivos asociados al asistente
                st.session_state.last_openai_run_state = client.beta.threads.runs.create(
                    thread_id=st.session_state.thread_id,
                    assistant_id=ASSISTANT_ID,
                    timeout=5*60)            
            
            # Verificar si el run ha sido completado
            completed = False
            while not completed:                
                run = client.beta.threads.runs.retrieve(
                    thread_id=st.session_state.thread_id,
                    run_id=get_run_id())    
                if run.status == "requires_action":
                    tools_output = []
                    for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                        f = tool_call.function
                        print("Verificando: ",f)
                        f_name = f.name
                        f_args = json.loads(f.arguments)
                        print(f"Ejecutando la función {f_name} usando el argumento {f_args}")
                        tool_result = tool_to_function[f_name](**f_args)
                        tools_output.append(
                            {
                                "tool_call_id": tool_call.id,
                                "output": tool_result,
                            }
                        )
                        print(f"Respuesta obtenida {tool_result}")
                    client.beta.threads.runs.submit_tool_outputs(
                        thread_id=st.session_state.thread_id,
                        run_id=get_run_id(),
                        tool_outputs=tools_output
                    )

                if run.status == "completed":
                    completed = True

                else:
                    time.sleep(0.2)

            # Recuperar mensajes agregados por el asistente
            messages = client.beta.threads.messages.list(
                thread_id=st.session_state.thread_id
            )

            # Procesar y mostrar los mensajes del asistente
            assistant_messages_for_run = [
                message for message in messages 
                if message.run_id == run.id and message.role == "assistant"
            ]
            for message in reversed(assistant_messages_for_run):
                #print(message.content[0].type)
                if message.content[0].type == "text":
                    full_response = message.content[0].text.value 
                    st.session_state.messages.append({"role": "assistant", "content": full_response, "type": "text"})
                    with st.chat_message("assistant", avatar=avatar_asistente):
                        st.markdown(full_response, unsafe_allow_html=True)
                
                if message.content[0].type == "image_file":
                    # Obtener el file_id del mensaje
                    file_id = message.content[0].image_file.file_id

                    # Agregar una referencia a la imagen en el historial del chat
                    st.session_state.messages.append({"role":"assistant", "content": f"Imagen con ID: {file_id}", "type": "image", "file_id": file_id})

                    try:
                        # Obtener los bytes de la imagen y crear un objeto Image
                        image_bytes = client.files.content(file_id).content
                        image = Image.open(io.BytesIO(image_bytes))

                        # Mostrar la imagen en Streamlit
                        with st.chat_message("assistant", avatar=avatar_asistente):
                            st.image(image, caption="Imagen generada por el Asistente IA UManizales")
                    except Exception as e:
                        error_message = f"Error al obtener la imagen: {e}"
                        with st.chat_message("assistant", avatar=avatar_asistente):
                            st.markdown(error_message)
                
                if message.content[0].type != "text" and message.content[0].type != "image_file":
                    response_text = "No se logró una respuesta válida"
                    st.session_state.messages.append({"role": "assistant", "content": response_text, "type": "text"})
                    with st.chat_message("assistant", avatar=avatar_asistente):
                        st.markdown(response_text, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Error recibiendo el mensaje: {e}", icon="🚨")
else:
    st.caption("¡Bienvenido! Oprima el botón para tener una conversación con su asistente inteligente. Disponible para responder sus preguntas y proporcionarle información basada en datos.")

# python -m venv venv
# venv\Scripts\Activate
# pip install -r requirements.txt
# streamlit run Home.py --server.port 8507
