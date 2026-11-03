import customtkinter as ctk
import sqlite3, datetime, os, sys, shutil, tempfile
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd
from tkcalendar import DateEntry
from tkinter import messagebox, filedialog
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule
from PIL import Image, ImageDraw
import threading

try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False

# ==========================================
# 0. RESOLUCIÓN DE RUTAS
# ==========================================
def resource_path(relative_path):
    try: base_path = sys._MEIPASS
    except Exception: base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def abrir_mapa_predio(ent_lat, ent_lon, municipio="", departamento=""):
    try:
        from tkintermapview import TkinterMapView
    except ImportError:
        messagebox.showerror("Visor no disponible", "No se pudo cargar el visor de mapas.")
        return

    popup = ctk.CTkToplevel(ventana)
    popup.title("Seleccionar ubicación del predio")
    popup.geometry("1000x700")
    popup.minsize(760, 540)
    popup.transient(ventana)
    popup.grab_set()

    barra_busqueda = ctk.CTkFrame(popup, fg_color="transparent")
    barra_busqueda.pack(fill="x", padx=12, pady=(12, 4))
    entrada_municipio = ctk.CTkEntry(barra_busqueda, placeholder_text="Buscar municipio o departamento", height=36)
    entrada_municipio.pack(side="left", fill="x", expand=True, padx=(0, 8))
    consulta_inicial = ", ".join(parte for parte in (municipio, departamento, "Colombia") if parte)
    if consulta_inicial:
        entrada_municipio.insert(0, consulta_inicial)

    mapa = TkinterMapView(popup, width=960, height=590, corner_radius=0)
    mapa.set_tile_server(
        "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        max_zoom=19,
    )
    mapa.pack(fill="both", expand=True, padx=12, pady=(12, 6))

    estado_coordenada = ctk.CTkLabel(popup, text="Haz clic en el predio para fijar el marcador")
    estado_coordenada.pack(pady=5)
    ctk.CTkLabel(popup, text="Mapa híbrido: imágenes satelitales y nombres de vías · © Google", font=("Arial", 9)).pack(pady=(0, 4))
    marcador = [None]
    busqueda_activa = [False]

    def mostrar_resultado_busqueda(resultado):
        if not popup.winfo_exists():
            return
        busqueda_activa[0] = False
        boton_buscar.configure(state="normal")
        if resultado is None:
            estado_coordenada.configure(text="No se encontró el municipio. Prueba con municipio y departamento.")
            return
        mapa.set_position(resultado.latitude, resultado.longitude)
        mapa.set_zoom(13)
        estado_coordenada.configure(text=f"{resultado.address} · Acerca el mapa y marca el predio exacto.")

    def buscar_municipio():
        consulta = entrada_municipio.get().strip()
        if not consulta or busqueda_activa[0]:
            return
        if "colombia" not in consulta.casefold():
            consulta = f"{consulta}, Colombia"
        estado_coordenada.configure(text="Buscando municipio...")
        busqueda_activa[0] = True
        boton_buscar.configure(state="disabled")

        def consultar_geocodificador():
            try:
                from geopy.geocoders import Nominatim
                geocodificador = Nominatim(user_agent="GestorProyectosGD/1.0 (predio map search)", timeout=12)
                resultado = geocodificador.geocode(consulta, exactly_one=True)
                popup.after(0, lambda resultado=resultado: mostrar_resultado_busqueda(resultado))
            except Exception:
                try:
                    popup.after(0, lambda: mostrar_resultado_busqueda(None))
                except Exception:
                    pass

        threading.Thread(target=consultar_geocodificador, daemon=True).start()

    boton_buscar = ctk.CTkButton(barra_busqueda, text="Buscar", width=110, height=36, command=buscar_municipio)
    boton_buscar.pack(side="right")
    entrada_municipio.bind("<Return>", lambda event: buscar_municipio())

    def actualizar_campos(coordenadas):
        latitud, longitud = coordenadas
        if not -85.05112878 <= latitud <= 85.05112878 or not -180 <= longitud <= 180:
            return
        latitud_txt, longitud_txt = f"{latitud:.6f}", f"{longitud:.6f}"
        ent_lat.delete(0, "end")
        ent_lat.insert(0, latitud_txt)
        ent_lon.delete(0, "end")
        ent_lon.insert(0, longitud_txt)
        estado_coordenada.configure(text=f"Predio: {latitud_txt}, {longitud_txt}")
        if marcador[0] is None:
            marcador[0] = mapa.set_marker(latitud, longitud, text="Predio")
        else:
            marcador[0].set_position(latitud, longitud)

    try:
        latitud_actual = float(ent_lat.get().strip().replace(",", "."))
        longitud_actual = float(ent_lon.get().strip().replace(",", "."))
        if -85.05112878 <= latitud_actual <= 85.05112878 and -180 <= longitud_actual <= 180:
            mapa.set_position(latitud_actual, longitud_actual)
            mapa.set_zoom(15)
            actualizar_campos((latitud_actual, longitud_actual))
        else:
            raise ValueError("Coordenadas fuera de rango")
    except (TypeError, ValueError):
        mapa.set_position(4.5709, -74.2973)
        mapa.set_zoom(5)

    mapa.add_left_click_map_command(actualizar_campos)
    ctk.CTkButton(popup, text="Cerrar", command=popup.destroy, width=120).pack(pady=(4, 12))

# ==========================================
# 1. UTILIDADES Y DATOS GEOGRÁFICOS
# ==========================================
def safe_txt(t):
    return "" if t is None else str(t).replace('•', '-').replace('\u201c', '"').replace('\u201d', '"').replace('\u2013', '-').encode('latin-1', 'replace').decode('latin-1')

def sumar_dias_habiles(fecha_inicio, dias):
    fecha_actual, dias_agregados = fecha_inicio, 0
    while dias_agregados < dias:
        fecha_actual += datetime.timedelta(days=1)
        if fecha_actual.weekday() < 5: dias_agregados += 1
    return fecha_actual

def sumar_meses(fecha, meses):
    mes = fecha.month - 1 + meses
    anio = fecha.year + mes // 12
    mes = mes % 12 + 1
    dias_en_mes = [31, 29 if anio % 4 == 0 and not anio % 400 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return datetime.date(anio, mes, min(fecha.day, dias_en_mes[mes - 1]))

def descargar_mapa_google(lat_str, lon_str):
    try:
        import urllib.request, math
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from io import BytesIO
        lat, lon = float(str(lat_str).replace(',', '.')), float(str(lon_str).replace(',', '.'))
        if not -85.05112878 <= lat <= 85.05112878 or not -180 <= lon <= 180:
            return None
        zoom = 14 
        n = 2.0 ** zoom
        xtile = int((lon + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
        TILE_SIZE = 256
        posiciones = [(dx, dy) for dx in range(-1, 2) for dy in range(-1, 2)]
        proveedores = (
            lambda x, y: f"https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={zoom}",
            lambda x, y: f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{y}/{x}",
        )
        mejores_baldosas = {}

        def descargar_baldosa(url):
            solicitud = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(solicitud, timeout=8) as respuesta:
                with Image.open(BytesIO(respuesta.read())) as baldosa:
                    return baldosa.convert("RGB")

        for crear_url in proveedores:
            baldosas = {}
            with ThreadPoolExecutor(max_workers=9) as executor:
                tareas = {
                    executor.submit(descargar_baldosa, crear_url(xtile + dx, ytile + dy)): (dx, dy)
                    for dx, dy in posiciones
                }
                for tarea in as_completed(tareas):
                    try:
                        baldosas[tareas[tarea]] = tarea.result()
                    except Exception:
                        pass
            if len(baldosas) > len(mejores_baldosas):
                mejores_baldosas = baldosas
            if len(baldosas) == len(posiciones):
                break

        if not mejores_baldosas:
            return None

        mapa_final = Image.new('RGB', (TILE_SIZE * 3, TILE_SIZE * 3), (230, 230, 230))
        for (dx, dy), baldosa in mejores_baldosas.items():
            mapa_final.paste(baldosa, ((dx + 1) * TILE_SIZE, (dy + 1) * TILE_SIZE))
        
        draw = ImageDraw.Draw(mapa_final)
        centro_x, centro_y, r = TILE_SIZE * 1.5, TILE_SIZE * 1.5, 12
        draw.ellipse((centro_x - r, centro_y - r, centro_x + r, centro_y + r), fill='red', outline='white', width=3)
        ruta_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
        mapa_final.save(ruta_temp)
        return ruta_temp
    except Exception: return None

ESTADOS_COLORES = {"PENDIENTE": "gray50", "RADICADO": "#3498db", "EN TRÁMITE": "#e67e22", "EN SUBSANACIONES": "#d35400", "REITERADO": "#d4ac0d", "COMPLETADO": "#27ae60", "VENCIDO": "#e74c3c"}
DEPARTAMENTOS = sorted(["Amazonas", "Antioquia", "Arauca", "Atlántico", "Bolívar", "Boyacá", "Caldas", "Caquetá", "Casanare", "Cauca", "Cesar", "Chocó", "Córdoba", "Cundinamarca", "Guainía", "Guaviare", "Huila", "La Guajira", "Magdalena", "Meta", "Nariño", "Norte de Santander", "Putumayo", "Quindío", "Risaralda", "San Andrés y Providencia", "Santander", "Sucre", "Tolima", "Valle del Cauca", "Vaupés", "Vichada"])
MUNICIPIOS = {
    "Antioquia": ["Medellín", "Bello", "Itagüí", "Envigado", "Apartadó", "Turbo", "Caucasia", "Rionegro", "Sabaneta", "Copacabana", "La Estrella", "Marinilla", "Guarne", "Caldas", "Yarumal", "Santa fe de Antioquia"],
    "Casanare": ["Aguazul", "Chámeza", "Hato Corozal", "La Salina", "Maní", "Monterrey", "Nunchía", "Orocué", "Paz de Ariporo", "Pore", "Recetor", "Sabanalarga", "Sácama", "San Luis de Palenque", "Támara", "Tauramena", "Trinidad", "Villanueva", "Yopal"],
    "Cundinamarca": ["Bogotá", "Cajicá", "Chía", "Cota", "Facatativá", "Funza", "Fusagasugá", "Girardot", "Guaduas", "La Calera", "Madrid", "Mosquera", "Pacho", "Puerto Salgar", "Soacha", "Sopó", "Tocaima", "Tocancipá", "Ubaté", "Villeta", "Zipaquirá"],
    "Meta": ["Villavicencio", "Acacías", "Barranca de Upía", "Cabuyaro", "Castilla la Nueva", "Cubarral", "Cumaral", "El Calvario", "El Castillo", "El Dorado", "Fuente de Oro", "Granada", "Guamal", "La Macarena", "Lejanías", "Mapiripán", "Mesetas", "Puerto Concordia", "Puerto Gaitán", "Puerto Lleras", "Puerto López", "Puerto Rico", "Restrepo", "San Carlos de Guaroa", "San Juan de Arama", "San Juanito", "San Martín", "Uribe", "Vista Hermosa"],
    "Santander": ["Bucaramanga", "Barrancabermeja", "San Gil", "Piedecuesta", "Floridablanca", "Girón", "Socorro", "Vélez", "Málaga", "Zapatoca", "Barichara"],
    "Tolima": ["Ibagué", "Alpujarra", "Cajamarca", "Chaparral", "Espinal", "Flandes", "Fresno", "Guamo", "Honda", "Líbano", "Mariquita", "Melgar", "Natagaima", "Ortega", "Planadas", "Purificación", "Rioblanco", "Rovira", "San Antonio", "Venadillo"],
    "Valle del Cauca": ["Cali", "Buenaventura", "Palmira", "Tuluá", "Buga", "Cartago", "Jamundí", "Yumbo", "Candelaria", "Florida"]
}
REQUISITOS_BASE = [
    ("Trámites de Terreno", "1.1 Matríz de riesgos", "Ingeniería Interna"), ("Trámites de Terreno", "1.2 Concepto de áreas protegidas y ausencia de obligaciones", "CAR"),
    ("Trámites de Terreno", "1.3 Programa de Arqueología Preventiva", "ICANH"), ("Trámites de Terreno", "1.4 Resolución de procedencia de consulta previa", "Min. Interior (DANCP)"),
    ("Trámites de Terreno", "1.5 Certificado de Superposición / Restitución (Ley 1448)", "URT"), ("Trámites de Terreno", "1.6 Concepto de uso de suelo y compatibilidad (POT)", "Alcaldía Municipal"),
    ("Trámites de Terreno", "1.7 Verificación de bienes administrados", "UARIV (FRV)"), ("Trámites de Terreno", "1.8 Estado de contaminación (MAP, REG, MUSE, AEI)", "AICMA"),
    ("Trámites de Terreno", "1.9 Certificados de tradición y libertad (30 días)", "Propietario"), ("Trámites de Terreno", "1.10 Estudio de títulos (A mas de 30 años)", "Propietario"),
    ("Trámites de Terreno", "1.11 Escrituras del predio", "Propietario"), ("Trámites de Terreno", "1.12 Contrato de arrendamiento del Terreno", "INGEV"),
    ("Trámites de Terreno", "1.13 Concepto Superposición Hidrocarburos", "ANH"), ("Trámites de Terreno", "1.14 Certificado Títulos Mineros", "ANM"),
    ("Trámites de Terreno", "1.15 Afectación Infraestructura de Transporte", "ANI"), ("Trámites de Terreno", "1.16 Afectación Espacio Aéreo y Superficies", "Aerocivil"),
    ("Trámites de Terreno", "1.17 Concepto de Incompetencia Ambiental", "ANLA"), ("Trámites de Terreno", "1.18 Certificación zonas protegidas", "Parques Nacionales (PNN)"),
    ("Trámites de Terreno", "1.19 Zona de Reserva Forestal Ley 2da", "MADS / ANLA"), ("Trámites de Terreno", "1.20 Naturaleza Jurídica del Predio (Agrarios)", "Agencia Nal. Tierras (ANT)"),
    ("Trámites de Terreno", "1.21 Seguridad, Orden Público y Viabilidad", "Ejército Nacional"), ("Trámites OR", "2.1 Aprobación de estudio de conexión", "ENERCA / OR"),
    ("Trámites OR", "2.2 Solicitud de insumos al OR para estudio de conexión simplificado", "ENERCA / OR"), ("Trámites OR", "2.3 Insumos y viabilidad ECS", "Área de ingeniería INGEV"),
    ("Trámites OR", "2.4 Contrato de Conexión firmado", "ENERCA / OR"), ("Servidumbre", "3.1 Estudio de Gestión Predial & Valorización", "Interno"),
    ("Servidumbre", "3.2 Contratos de promesa de servidumbres", "Interno"), ("Modelo de Contrato", "4.1 EPC - full EPC", "Interno"),
    ("Modelo de Contrato", "4.2 PPA - Fiducia Garantías", "Interno"), ("Modelo de Contrato", "4.3 Suministro y soporte de equipos", "Interno"),
    ("Modelo de Contrato", "4.4 Contrato de servidumbre (redes eléctricas)", "Interno"), ("Análisis Técnico", "5.1 Estudio geológico y geotécnico", "Interno"),
    ("Análisis Técnico", "5.2 Estudio hidrológico e hidráulico", "Interno"), ("Análisis Técnico", "5.3 Estudio Topográfico (planta y línea)", "Interno"),
    ("Análisis Técnico", "5.4 Base datos meteorológico (Solargis, NREL, IDEAM)", "Interno"), ("Análisis Técnico", "5.5 Polígono de ubicación (KML y Shapefile)", "INGEV"),
    ("Análisis Técnico", "5.6 Ubicación línea trifásica más cercana", "Interno"), ("Ingeniería Básica", "6.1 Trazado de Redes Eléctricas MT y BT en AC/DC", "Interno"),
    ("Ingeniería Básica", "6.2 Memoria de Cálculo", "Interno"), ("Ingeniería Básica", "6.3 Cuarto de Inversores", "Interno"),
    ("Ingeniería Básica", "6.4 Layout general", "Interno"), ("Ingeniería Básica", "6.5 Diagrama Unifilar", "Interno"),
    ("Ingeniería Básica", "6.6 Simulación en PVsyst", "Interno"), ("Ingeniería Básica", "6.7 Fichas Técnicas Equipos Principales", "Interno"),
    ("Antecedentes", "7.1 Antecedentes de la policía (Judiciales)", "Interno"), ("Antecedentes", "7.2 Antecedentes Procuraduría (Disciplinarios)", "Interno"),
    ("Antecedentes", "7.3 Antecedentes Contraloría (Fiscales)", "Interno"), ("Antecedentes", "7.4 Certificado no estar en proceso de liquidación", "Interno"),
    ("Antecedentes", "7.5 Certificado no estar en proceso de insolvencia", "Interno"), ("Antecedentes", "7.6 Lista de beneficiarios finales (DIAN) RUB", "Interno"),
    ("Antecedentes", "7.7 Certificado existencia y representación legal", "Interno"), ("Antecedentes", "7.8 Listas restrictivas (KYC)", "Interno"),
    ("Antecedentes", "7.9 OFAC", "Interno"), ("Antecedentes", "7.10 ONU", "Interno"), ("Antecedentes", "7.11 PEP", "Interno")
]

# ==========================================
# 2. BASE DE DATOS Y MIGRACIONES
# ==========================================
def iniciar_base_datos():
    conexion = sqlite3.connect("sistema_gd_v4.db")
    cursor = conexion.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT UNIQUE, password TEXT, rol TEXT, nombre TEXT)''')
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO usuarios (usuario, password, rol, nombre) VALUES (?, ?, ?, ?)", ("admin", "admin123", "Administrador", "Usuario Principal"))
    cursor.execute('''CREATE TABLE IF NOT EXISTS proyectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cluster TEXT, nombre TEXT, municipio TEXT, departamento TEXT,
            direccion TEXT, latitud TEXT, longitud TEXT, area REAL, radicado TEXT, cod_validacion TEXT, circuito TEXT, coord_conexion TEXT,
            fecha_creacion TEXT, estado_general TEXT DEFAULT 'ACTIVO', capacidad_kw REAL DEFAULT 0.0, req_servidumbre INTEGER DEFAULT 0, req_contrato INTEGER DEFAULT 0,
            num_paneles INTEGER DEFAULT 0, pot_panel REAL DEFAULT 0.0, num_inversores INTEGER DEFAULT 0, modelos_inversores TEXT DEFAULT ''
        )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS requisitos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, proyecto_id INTEGER, categoria TEXT, descripcion TEXT, entidad TEXT,
            estado TEXT, fecha_radicacion TEXT, fecha_limite TEXT, fecha_final TEXT, evidencia_ruta TEXT, observaciones TEXT
        )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS clusteres (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre_cluster TEXT UNIQUE)''')
    
    for col in ["estado_general TEXT DEFAULT 'ACTIVO'", "capacidad_kw REAL DEFAULT 0.0", "req_servidumbre INTEGER DEFAULT 0", "req_contrato INTEGER DEFAULT 0", "num_paneles INTEGER DEFAULT 0", "pot_panel REAL DEFAULT 0.0", "num_inversores INTEGER DEFAULT 0", "modelos_inversores TEXT DEFAULT ''"]:
        try: cursor.execute(f"ALTER TABLE proyectos ADD COLUMN {col}")
        except: pass 
    try: cursor.execute("ALTER TABLE requisitos ADD COLUMN evidencia_respuesta TEXT DEFAULT ''")
    except: pass 
    try:
        cursor.execute("SELECT DISTINCT cluster FROM proyectos WHERE cluster IS NOT NULL AND cluster != ''")
        for c in cursor.fetchall():
            try: cursor.execute("INSERT INTO clusteres (nombre_cluster) VALUES (?)", (c[0],))
            except: pass
    except: pass
    conexion.commit()
    conexion.close()

def respaldar_base_datos():
    try:
        if not os.path.exists("backups"): os.makedirs("backups")
        nombre_backup = f"backups/sistema_gd_v4_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2("sistema_gd_v4.db", nombre_backup)
        messagebox.showinfo("Backup Exitoso", f"Copia de seguridad guardada con éxito en:\n{nombre_backup}")
    except Exception as e: messagebox.showerror("Error de Backup", f"No se pudo respaldar la base de datos.\nDetalle: {str(e)}")

def restaurar_base_datos():
    ruta_backup = filedialog.askopenfilename(title="Seleccionar archivo de Backup", filetypes=[("Archivos de Base de Datos DB", "*.db")])
    if ruta_backup:
        if messagebox.askyesno("Restaurar Backup", "ATENCIÓN: Esto reemplazará tu base de datos actual con la del backup seleccionado.\nCualquier cambio no respaldado se perderá.\n\n¿Estás seguro de continuar?"):
            try:
                shutil.copy2(ruta_backup, "sistema_gd_v4.db")
                messagebox.showinfo("Restauración Exitosa", "La base de datos ha sido restaurada con éxito.\nLa aplicación se cerrará ahora para aplicar los cambios; por favor, ábrela de nuevo.")
                os._exit(0)
            except Exception as e:
                messagebox.showerror("Error de Restauración", f"No se pudo restaurar el backup.\nDetalle: {str(e)}")

# ==========================================
# 3. CONFIGURACIÓN VISUAL Y VARIABLES GLOBALES
# ==========================================
ctk.set_appearance_mode("light")
ventana = ctk.CTk()
ventana.title("Gestor de Proyectos Generación Distribuida GD")
ventana.geometry("1400x900")
ventana.configure(fg_color="#f4f6f9")

ruta_icono = resource_path("icono_gd.ico")
if os.path.exists(ruta_icono):
    try:
        ventana.iconbitmap(default=ruta_icono)
        ventana.wm_iconbitmap(ruta_icono)
    except Exception:
        pass

usuario_actual, barra_lateral, contenedor_principal, area_principal, marco_login = None, None, None, None, None
modo_oscuro = False

def render_gradiente_lateral(frame):
    ancho, alto = 300, 1200
    arr = np.zeros((alto, ancho, 3), dtype=np.uint8)
    c_top, c_bottom = np.array([240, 248, 255]), np.array([41, 128, 185])   
    for y in range(alto): arr[y, :, :] = c_top + (c_bottom - c_top) * (y / alto)
    img = Image.fromarray(arr)
    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(ancho, alto))
    lbl = ctk.CTkLabel(frame, image=ctk_img, text="")
    lbl.image = ctk_img 
    lbl.place(x=0, y=0, relwidth=1, relheight=1)

def limpiar_area_principal():
    global area_principal
    if area_principal is not None:
        for widget in area_principal.winfo_children(): widget.destroy()
        try: area_principal._parent_canvas.yview_moveto(0.0)
        except: pass
        if modo_oscuro:
            area_principal.after_idle(lambda: aplicar_tema(ventana, True))

def render_cabecera(parent):
    marco_top_bg = ctk.CTkFrame(parent, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_top_bg.pack(fill="x", pady=(10, 20), padx=10)
    ctk.CTkLabel(marco_top_bg, text="GESTOR DE PROYECTOS\nGENERACIÓN DISTRIBUIDA GD", font=("Arial", 26, "bold"), text_color="#154360", justify="center").pack(pady=15)
    if usuario_actual: ctk.CTkLabel(marco_top_bg, text=f"👤 Usuario: {usuario_actual[1]} ({usuario_actual[2]})", font=("Arial", 11, "bold"), text_color="#7f8c8d").place(relx=0.98, rely=0.1, anchor="ne")

# ==========================================
# CREACIÓN DE CLÚSTER INDEPENDIENTE
# ==========================================
def mostrar_crear_cluster():
    nuevo_cluster = ctk.CTkInputDialog(text="Ingresa el nombre del Nuevo Clúster:\n(Ej: GD YOPAL 1)", title="Crear Clúster").get_input()
    if nuevo_cluster:
        nuevo_cluster = nuevo_cluster.strip().upper()
        con = sqlite3.connect("sistema_gd_v4.db")
        try:
            con.execute("INSERT INTO clusteres (nombre_cluster) VALUES (?)", (nuevo_cluster,))
            con.commit()
            messagebox.showinfo("Éxito", f"Clúster '{nuevo_cluster}' creado correctamente.\nAhora puedes asignarle proyectos.")
        except sqlite3.IntegrityError: messagebox.showwarning("Aviso", "Ese clúster ya existe.")
        con.close()

def actualizar_nombre_cluster(conexion, nombre_actual, nombre_nuevo):
    cursor = conexion.execute(
        "UPDATE clusteres SET nombre_cluster=? WHERE nombre_cluster=?",
        (nombre_nuevo, nombre_actual),
    )
    if cursor.rowcount == 0:
        raise ValueError("El clúster seleccionado ya no existe.")
    conexion.execute(
        "UPDATE proyectos SET cluster=? WHERE cluster=?",
        (nombre_nuevo, nombre_actual),
    )

def mostrar_renombrar_cluster():
    con = sqlite3.connect("sistema_gd_v4.db")
    clusters = [fila[0] for fila in con.execute(
        "SELECT nombre_cluster FROM clusteres ORDER BY nombre_cluster"
    ).fetchall()]
    con.close()
    if not clusters:
        messagebox.showinfo("Sin clústeres", "No hay clústeres para editar.")
        return

    pop = ctk.CTkToplevel(ventana)
    pop.title("Editar nombre del clúster")
    pop.geometry("420x250")
    pop.resizable(False, False)
    pop.transient(ventana)
    pop.grab_set()
    pop.configure(fg_color="#f4f6f9")
    ctk.CTkLabel(pop, text="Editar nombre del clúster", font=("Arial", 18, "bold"), text_color="#2c3e50").pack(pady=(22, 12))
    seleccion = ctk.StringVar(value=clusters[0])
    ctk.CTkOptionMenu(pop, variable=seleccion, values=clusters, width=340).pack(pady=6)
    entrada = ctk.CTkEntry(pop, placeholder_text="Nuevo nombre", width=340)
    entrada.pack(pady=12)

    def guardar_nombre():
        nombre_actual = seleccion.get()
        nombre_nuevo = entrada.get().strip().upper()
        if not nombre_nuevo:
            messagebox.showwarning("Nombre requerido", "Escribe el nuevo nombre del clúster.", parent=pop)
            return
        if nombre_nuevo == nombre_actual:
            pop.destroy()
            return

        conexion = sqlite3.connect("sistema_gd_v4.db")
        try:
            actualizar_nombre_cluster(conexion, nombre_actual, nombre_nuevo)
            conexion.commit()
            pop.destroy()
            messagebox.showinfo("Clúster actualizado", f"El clúster ahora se llama '{nombre_nuevo}'.")
            mostrar_lista()
        except sqlite3.IntegrityError:
            conexion.rollback()
            messagebox.showwarning("Nombre duplicado", "Ya existe un clúster con ese nombre.", parent=pop)
        except Exception as error:
            conexion.rollback()
            messagebox.showerror("Error", f"No se pudo actualizar el clúster.\n{error}", parent=pop)
        finally:
            conexion.close()

    botones = ctk.CTkFrame(pop, fg_color="transparent")
    botones.pack(pady=(5, 16))
    ctk.CTkButton(botones, text="Guardar", command=guardar_nombre, width=130).pack(side="left", padx=6)
    ctk.CTkButton(botones, text="Cancelar", command=pop.destroy, width=130, fg_color="#7f8c8d", hover_color="#626f70").pack(side="left", padx=6)

# ==========================================
# UTILIDADES DE SOPORTES Y REPLICACIÓN
# ==========================================
def abrir_popup_soportes(id_req, id_proyecto, tipo_columna):
    pop = ctk.CTkToplevel(ventana)
    titulo = "Soportes de Radicación" if tipo_columna == "evidencia_ruta" else "Soportes de Respuesta/Cierre"
    pop.title(titulo)
    pop.geometry("650x400")
    pop.grab_set()
    pop.configure(fg_color="#f4f6f9")
    ctk.CTkLabel(pop, text=titulo, font=("Arial", 18, "bold"), text_color="#2c3e50").pack(pady=(15, 5))
    con = sqlite3.connect("sistema_gd_v4.db")
    ruta_ev = con.execute(f"SELECT {tipo_columna} FROM requisitos WHERE id=?", (id_req,)).fetchone()[0]
    con.close()
    rutas = [r for r in (ruta_ev.split("|") if ruta_ev else []) if r.strip()]
    scroll = ctk.CTkScrollableFrame(pop, fg_color="transparent")
    scroll.pack(fill="both", expand=True, padx=20, pady=10)

    def eliminar_soporte(r_eliminar):
        if messagebox.askyesno("Eliminar", "¿Remover este archivo de las evidencias?"):
            rutas.remove(r_eliminar)
            con_del = sqlite3.connect("sistema_gd_v4.db")
            con_del.execute(f"UPDATE requisitos SET {tipo_columna} = ? WHERE id = ?", ("|".join(rutas), id_req))
            con_del.commit()
            con_del.close()
            pop.destroy()
            if hasattr(ventana, 'actualizar_boton_soporte_inplace'): ventana.actualizar_boton_soporte_inplace(id_req, tipo_columna, len(rutas))

    for r in rutas:
        f = ctk.CTkFrame(scroll, fg_color="#ffffff", corner_radius=8, border_color="#d5d8dc", border_width=1)
        f.pack(fill="x", pady=5)
        nombre_arch = os.path.basename(r)
        ctk.CTkLabel(f, text=nombre_arch[:55] + "..." if len(nombre_arch) > 55 else nombre_arch, font=("Arial", 12), text_color="#2c3e50").pack(side="left", padx=15, pady=10)
        ctk.CTkButton(f, text="X", width=30, fg_color="#e74c3c", hover_color="#c0392b", text_color="white", command=lambda r_el=r: eliminar_soporte(r_el)).pack(side="right", padx=(5, 15))
        ctk.CTkButton(f, text="📄 Abrir", width=70, fg_color="#3498db", hover_color="#2980b9", text_color="white", command=lambda r_ab=r: os.startfile(r_ab)).pack(side="right", padx=5)
    if not rutas: ctk.CTkLabel(scroll, text="(No hay soportes adjuntos)", text_color="gray").pack(pady=20)

def adjuntar_soportes_multiples(id_req, tipo_columna):
    archivos = filedialog.askopenfilenames(title="Seleccionar Soportes (Usa Ctrl para elegir varios)")
    if not archivos: return
    con = sqlite3.connect("sistema_gd_v4.db")
    actual = con.execute(f"SELECT {tipo_columna} FROM requisitos WHERE id=?", (id_req,)).fetchone()[0]
    lista_actual = actual.split("|") if actual else []
    agregados, duplicados, nombres_duplicados = 0, 0, []
    
    for arch in archivos:
        if arch not in lista_actual:
            lista_actual.append(arch)
            agregados += 1
        else:
            duplicados += 1
            nombres_duplicados.append(os.path.basename(arch))
            
    if duplicados > 0: messagebox.showwarning("Duplicados", f"No se adjuntaron {duplicados} archivo(s) porque ya estaban cargados:\n" + "\n".join(nombres_duplicados[:3]) + ("\n..." if len(nombres_duplicados) > 3 else ""))
    if agregados > 0:
        con.execute(f"UPDATE requisitos SET {tipo_columna} = ? WHERE id = ?", ("|".join(lista_actual), id_req))
        con.commit()
        messagebox.showinfo("Éxito", f"Se adjuntaron {agregados} archivo(s).")
        if hasattr(ventana, 'actualizar_boton_soporte_inplace'): ventana.actualizar_boton_soporte_inplace(id_req, tipo_columna, len(lista_actual))
    con.close()

def replicar_requisito_cluster(id_req, id_proyecto, nombre_cluster):
    if not messagebox.askyesno("Confirmar Replicación", f"¿Deseas replicar el estado, fechas y TODOS los soportes de este requisito a los demás proyectos del clúster '{nombre_cluster}'?"): return
    con = sqlite3.connect("sistema_gd_v4.db")
    req_data = con.execute("SELECT categoria, descripcion, estado, fecha_radicacion, fecha_limite, fecha_final, evidencia_ruta, evidencia_respuesta, observaciones FROM requisitos WHERE id=?", (id_req,)).fetchone()
    if not req_data: 
        con.close()
        return
    cat, desc, est, f_rad, f_lim, f_fin, ev_ruta, ev_resp, obs = req_data
    otros_proyectos = con.execute("SELECT id FROM proyectos WHERE cluster=? AND id!=?", (nombre_cluster, id_proyecto)).fetchall()
    count_actualizados, count_omitidos = 0, 0
    
    for (op_id,) in otros_proyectos:
        target_data = con.execute("SELECT estado, fecha_radicacion, fecha_limite, fecha_final, evidencia_ruta, evidencia_respuesta, observaciones FROM requisitos WHERE proyecto_id=? AND categoria=? AND descripcion=?", (op_id, cat, desc)).fetchone()
        if target_data:
            t_est, t_frad, t_flim, t_ffin, t_ev, t_evresp, t_obs = target_data
            norm = lambda val: val if val else ""
            if norm(est) == norm(t_est) and norm(f_rad) == norm(t_frad) and norm(f_lim) == norm(t_flim) and norm(f_fin) == norm(t_ffin) and norm(ev_ruta) == norm(t_ev) and norm(ev_resp) == norm(t_evresp) and norm(obs) == norm(t_obs):
                count_omitidos += 1
                continue
        con.execute("""UPDATE requisitos SET estado=?, fecha_radicacion=?, fecha_limite=?, fecha_final=?, evidencia_ruta=?, evidencia_respuesta=?, observaciones=? WHERE proyecto_id=? AND categoria=? AND descripcion=?""", (est, f_rad, f_lim, f_fin, ev_ruta, ev_resp, obs, op_id, cat, desc))
        count_actualizados += 1
    con.commit()
    con.close()
    if count_actualizados > 0: messagebox.showinfo("Replicación", f"Replicado exitosamente en {count_actualizados} proyecto(s)." + (f"\n(Se omitieron {count_omitidos} que ya estaban idénticos)." if count_omitidos > 0 else ""))
    else: messagebox.showinfo("Sin Cambios", "No se modificaron otros proyectos (ya estaban actualizados).")

# ==========================================
# MÓDULO: RADICADOS OR
# ==========================================
def mostrar_modulo_radicados():
    limpiar_area_principal()
    render_cabecera(area_principal)
    marco_busq = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_busq.pack(fill="x", padx=10)
    ctk.CTkLabel(marco_busq, text="MÓDULO DE RADICADOS Y DATOS OR", font=("Arial", 20, "bold"), text_color="#16A085").pack(side="left", padx=20, pady=15)
    entry_busqueda = ctk.CTkEntry(marco_busq, placeholder_text="Buscar proyecto, radicado, circuito...", width=350, fg_color="#ffffff", text_color="#2c3e50", border_color="#bdc3c7")
    entry_busqueda.pack(side="right", padx=20)
    marco_lista = ctk.CTkFrame(area_principal, fg_color="transparent")
    marco_lista.pack(fill="both", expand=True, pady=10, padx=10)

    def cargar_datos_or(filtro=""):
        for w in marco_lista.winfo_children(): w.destroy()
        con = sqlite3.connect("sistema_gd_v4.db")
        proyectos_or = con.execute("SELECT id, cluster, nombre, radicado, cod_validacion, circuito, coord_conexion, num_paneles, pot_panel, num_inversores, modelos_inversores FROM proyectos ORDER BY cluster ASC, id ASC").fetchall()
        con.close()

        if filtro: proyectos_or = [p for p in proyectos_or if filtro.lower() in f"{p[1]} {p[2]} {p[3]} {p[4]} {p[5]}".lower()]
        if not proyectos_or:
            ctk.CTkLabel(marco_lista, text="No se encontraron datos OR para esta búsqueda.", text_color="#2c3e50", font=("Arial", 16)).pack(pady=30)
            return

        dicc_clusters = {}
        for p in proyectos_or:
            cl = p[1] if p[1] and p[1] != "N/A" else "Individual"
            if cl not in dicc_clusters: dicc_clusters[cl] = []
            dicc_clusters[cl].append(p)

        def toggle_cluster_or(m_proy, btn_h, c_nom, e_abierto):
            txt = f"▶ CLÚSTER: {c_nom}"
            if e_abierto[0]: m_proy.pack_forget(); btn_h.configure(text=txt.replace("▼", "▶")); e_abierto[0] = False
            else: m_proy.pack(fill="x", pady=(0, 10)); btn_h.configure(text=txt.replace("▶", "▼")); e_abierto[0] = True

        for cl_nombre, proys in dicc_clusters.items():
            m_grup = ctk.CTkFrame(marco_lista, fg_color="transparent")
            m_grup.pack(fill="x", pady=5)
            b_cl = ctk.CTkButton(m_grup, text=f"▶ CLÚSTER: {cl_nombre}", font=("Arial", 16, "bold"), anchor="w", height=45, fg_color="#e5e8e8", text_color="#2c3e50", hover_color="#d5d8dc")
            b_cl.pack(fill="x")
            m_pr = ctk.CTkFrame(m_grup, fg_color="transparent")
            estado_ab = [False] 
            b_cl.configure(command=lambda mp=m_pr, b=b_cl, n=cl_nombre, ea=estado_ab: toggle_cluster_or(mp, b, n, ea))
            
            for p in proys:
                p_id, cluster, nombre, rad, cod, circ, coord, pan, pot, n_inv, mod_inv = p
                tarjeta = ctk.CTkFrame(m_pr, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
                tarjeta.pack(fill="x", pady=8, padx=10)
                header = ctk.CTkFrame(tarjeta, fg_color="transparent")
                header.pack(fill="x", padx=15, pady=(10, 5))
                ctk.CTkLabel(header, text=f"Proyecto: {nombre}", font=("Arial", 16, "bold"), text_color="#16a085").pack(side="left")
                ctk.CTkButton(header, text="✏ Editar Radicado OR", width=120, fg_color="#d35400", hover_color="#e67e22", text_color="white", font=("Arial", 12, "bold"), command=lambda i=p_id: abrir_popup_2_2(i)).pack(side="right")
                body = ctk.CTkFrame(tarjeta, fg_color="transparent")
                body.pack(fill="x", padx=15, pady=(0, 10))
                val = lambda v: v if v else "N/A"
                ctk.CTkLabel(body, text=f"Radicado: {val(rad)}  |  Código: {val(cod)}  |  Circuito: {val(circ)}  |  Coordenadas: {val(coord)}", font=("Arial", 14, "bold"), text_color="#2c3e50").pack(anchor="w", pady=(2, 2))
                ctk.CTkLabel(body, text=f"Paneles: {pan} ({pot}W)  |  Inversores: {n_inv}  |  Modelos: {val(mod_inv).replace('|', ', ')}", font=("Arial", 13), text_color="#7f8c8d").pack(anchor="w", pady=(0,5))

    ventana.refrescar_modulo_silencioso = lambda: cargar_datos_or(entry_busqueda.get())
    def on_search_or(event):
        if hasattr(ventana, 'search_or_after_id'): ventana.after_cancel(ventana.search_or_after_id)
        ventana.search_or_after_id = ventana.after(400, lambda: cargar_datos_or(entry_busqueda.get()))
    entry_busqueda.bind("<" + "KeyRelease" + ">", on_search_or)
    cargar_datos_or()

# ==========================================
# PESTAÑA: GESTOR DE SOPORTES EN CASCADA
# ==========================================
def mostrar_pestana_soportes():
    limpiar_area_principal()
    render_cabecera(area_principal)
    marco_top = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_top.pack(fill="x", padx=10, pady=(0,10))
    ctk.CTkLabel(marco_top, text="📂 Repositorio Global de Soportes Documentales", font=("Arial", 20, "bold"), text_color="#d35400").pack(anchor="w", pady=15, padx=20)

    con = sqlite3.connect("sistema_gd_v4.db")
    proyectos_doc = con.execute('''SELECT p.cluster, p.id, p.nombre FROM proyectos p JOIN requisitos r ON p.id = r.proyecto_id WHERE (r.evidencia_ruta IS NOT NULL AND r.evidencia_ruta != '') OR (r.evidencia_respuesta IS NOT NULL AND r.evidencia_respuesta != '') GROUP BY p.id ORDER BY p.cluster, p.id ASC''').fetchall()
    con.close()

    if not proyectos_doc:
        marco_bg = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
        marco_bg.pack(fill="x", pady=30, padx=10)
        ctk.CTkLabel(marco_bg, text="No hay ningún archivo adjunto en la base de datos.", font=("Arial", 16, "bold"), text_color="#2c3e50").pack(pady=30)
        return

    dicc_clusters = {}
    for cl, p_id, p_nom in proyectos_doc:
        c_label = cl if cl and cl != "N/A" else "Individual"
        if c_label not in dicc_clusters: dicc_clusters[c_label] = []
        dicc_clusters[c_label].append((p_id, p_nom))

    marco_filtros = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_filtros.pack(fill="x", padx=10, pady=(0, 20))
    ctk.CTkLabel(marco_filtros, text="Filtro de Clúster:", font=("Arial", 14, "bold"), text_color="#2c3e50").pack(side="left", padx=(15, 10), pady=15)
    combo_cl = ctk.CTkComboBox(marco_filtros, values=sorted(list(dicc_clusters.keys())), width=180, fg_color="#f4f6f9", text_color="#2c3e50", border_color="#bdc3c7")
    combo_cl.pack(side="left", padx=5)
    ctk.CTkLabel(marco_filtros, text="Seleccionar Proyecto:", font=("Arial", 14, "bold"), text_color="#2c3e50").pack(side="left", padx=(25,10))
    combo_pr = ctk.CTkComboBox(marco_filtros, values=["Seleccione Proyecto"], width=250, fg_color="#f4f6f9", text_color="#2c3e50", border_color="#bdc3c7")
    combo_pr.pack(side="left", padx=5)
    ctk.CTkLabel(marco_filtros, text="Tipo de Evidencia:", font=("Arial", 14, "bold"), text_color="#2c3e50").pack(side="left", padx=(25,10))
    combo_tipo = ctk.CTkComboBox(marco_filtros, values=["TODOS", "SÓLO RADICADOS", "SÓLO CIERRES"], width=180, fg_color="#f4f6f9", text_color="#2c3e50", border_color="#bdc3c7")
    combo_tipo.pack(side="left", padx=5)

    marco_resultados = ctk.CTkFrame(area_principal, fg_color="transparent")
    marco_resultados.pack(fill="both", expand=True, pady=10, padx=10)

    def eliminar_doc(req_id, ruta_archivo, proj_name, tipo_columna):
        if not messagebox.askyesno("Confirmar Eliminación", "¿Estás seguro de eliminar este documento del repositorio?"): return
        con = sqlite3.connect("sistema_gd_v4.db")
        ev = con.execute(f"SELECT {tipo_columna} FROM requisitos WHERE id=?", (req_id,)).fetchone()[0]
        rutas = [r for r in ev.split("|") if r.strip()]
        if ruta_archivo in rutas: rutas.remove(ruta_archivo)
        con.execute(f"UPDATE requisitos SET {tipo_columna}=? WHERE id=?", ("|".join(rutas), req_id))
        con.commit()
        con.close()
        cargar_documentos(proj_name) 

    def cargar_documentos(proj_name=None):
        for w in marco_resultados.winfo_children(): w.destroy()
        cl_actual, pr_actual = combo_cl.get(), combo_pr.get()
        if not pr_actual or pr_actual == "Seleccione Proyecto": return
        p_id = next((p[0] for p in dicc_clusters[cl_actual] if p[1] == pr_actual), None)
        if not p_id: return

        con = sqlite3.connect("sistema_gd_v4.db")
        reqs_docs = con.execute("SELECT id, descripcion, evidencia_ruta, evidencia_respuesta FROM requisitos WHERE proyecto_id=? AND ((evidencia_ruta IS NOT NULL AND evidencia_ruta != '') OR (evidencia_respuesta IS NOT NULL AND evidencia_respuesta != ''))", (p_id,)).fetchall()
        con.close()

        tipo_filtro, hay_docs = combo_tipo.get(), False

        def generar_tarjetas(rutas_str, etiqueta, color_etiq, tipo_col, req_id, desc):
            rutas = [r for r in (rutas_str.split("|") if rutas_str else []) if r.strip()]
            for ruta in rutas:
                f_doc = ctk.CTkFrame(marco_resultados, fg_color="#ffffff", corner_radius=8, border_width=1, border_color="#d5d8dc")
                f_doc.pack(fill="x", pady=6)
                nom_arch = os.path.basename(ruta)
                ctk.CTkLabel(f_doc, text=f"[{etiqueta}] ", font=("Arial", 14, "bold"), text_color=color_etiq).pack(side="left", padx=(15, 5), pady=15)
                ctk.CTkLabel(f_doc, text=f"• {desc}   ", font=("Arial", 14, "bold"), text_color="#2c3e50").pack(side="left")
                ctk.CTkLabel(f_doc, text=f"({nom_arch})", font=("Arial", 13), text_color="#7f8c8d").pack(side="left", padx=5)
                ctk.CTkButton(f_doc, text="🗑 Eliminar", width=80, fg_color="#c0392b", hover_color="#922b21", text_color="white", command=lambda ri=req_id, ra=ruta, tc=tipo_col: eliminar_doc(ri, ra, pr_actual, tc)).pack(side="right", padx=(5, 15))
                ctk.CTkButton(f_doc, text="📄 Abrir PDF", width=100, fg_color="#3498db", hover_color="#2980b9", text_color="white", command=lambda r=ruta: os.startfile(r)).pack(side="right", padx=5)

        for req_id, desc, rut_rad, rut_resp in reqs_docs:
            if tipo_filtro in ["TODOS", "SÓLO RADICADOS"] and rut_rad: generar_tarjetas(rut_rad, "Radicado", "#3498db", "evidencia_ruta", req_id, desc); hay_docs = True
            if tipo_filtro in ["TODOS", "SÓLO CIERRES"] and rut_resp: generar_tarjetas(rut_resp, "Cierre", "#27ae60", "evidencia_respuesta", req_id, desc); hay_docs = True
        if not hay_docs: ctk.CTkLabel(marco_resultados, text=f"No existen documentos de la categoría '{tipo_filtro}' para este proyecto.", text_color="#2c3e50", font=("Arial", 15, "bold")).pack(pady=40)

    def on_cl_change(choice):
        proys = [p[1] for p in dicc_clusters[choice]]
        combo_pr.configure(values=proys)
        if proys: combo_pr.set(proys[0]); cargar_documentos()
        else: combo_pr.set(""); [w.destroy() for w in marco_resultados.winfo_children()]

    combo_cl.configure(command=on_cl_change)
    combo_pr.configure(command=lambda _: cargar_documentos())
    combo_tipo.configure(command=lambda _: cargar_documentos())
    clusters_disp = sorted(list(dicc_clusters.keys()))
    if clusters_disp: combo_cl.set(clusters_disp[0]); on_cl_change(clusters_disp[0])

# ==========================================
# 4. POPUP OR
# ==========================================
def abrir_popup_2_2(id_proyecto, id_req=None):
    popup = ctk.CTkToplevel(ventana)
    popup.title("Datos Insumos OR (Req 2.2)")
    popup.geometry("650x750")
    popup.grab_set() 
    popup.configure(fg_color="#f4f6f9") 
    
    con = sqlite3.connect("sistema_gd_v4.db")
    d = con.execute("SELECT radicado, cod_validacion, circuito, coord_conexion, num_paneles, pot_panel, num_inversores, modelos_inversores FROM proyectos WHERE id=?", (id_proyecto,)).fetchone()
    con.close()
    
    scroll_or = ctk.CTkScrollableFrame(popup, fg_color="transparent")
    scroll_or.pack(fill="both", expand=True, padx=20, pady=10)
    ctk.CTkLabel(scroll_or, text="Datos de Radicación OR", font=("Arial", 20, "bold"), text_color="#2c3e50").pack(pady=(10, 20))
    estilo_entry = {"fg_color": "#ffffff", "border_color": "#bdc3c7", "text_color": "#2c3e50", "height": 32}

    def crear_campo(texto, valor_previo=None):
        ctk.CTkLabel(scroll_or, text=texto, text_color="#2c3e50", font=("Arial", 12, "bold")).pack(anchor="w", padx=10)
        e = ctk.CTkEntry(scroll_or, width=500, **estilo_entry)
        e.pack(pady=(0, 10), padx=10)
        if valor_previo: e.insert(0, valor_previo)
        return e

    ent_rad = crear_campo("Número de Solicitud (Radicado):", d[0])
    ent_cod = crear_campo("Código de Validación:", d[1])
    ent_circ = crear_campo("Circuito Asociado:", d[2])

    ctk.CTkLabel(scroll_or, text="Coordenadas del Pto. de Conexión:", text_color="#2c3e50", font=("Arial", 12, "bold")).pack(anchor="w", padx=10)
    coord_frame = ctk.CTkFrame(scroll_or, fg_color="transparent")
    coord_frame.pack(fill="x", padx=10, pady=(0, 10))
    ent_lat_or = ctk.CTkEntry(coord_frame, placeholder_text="Latitud", **estilo_entry)
    ent_lat_or.pack(side="left", expand=True, fill="x", padx=(0, 10))
    ent_lon_or = ctk.CTkEntry(coord_frame, placeholder_text="Longitud", **estilo_entry)
    ent_lon_or.pack(side="right", expand=True, fill="x")

    if d[3]:
        partes = d[3].split(",")
        ent_lat_or.insert(0, partes[0].strip() if len(partes)>0 else d[3])
        if len(partes)>1: ent_lon_or.insert(0, partes[1].strip())

    ctk.CTkLabel(scroll_or, text="Especificaciones Técnicas", font=("Arial", 16, "bold"), text_color="#f39c12").pack(pady=(15, 10))
    frame_tec = ctk.CTkFrame(scroll_or, fg_color="transparent")
    frame_tec.pack(fill="x", padx=10, pady=5)
    
    ctk.CTkLabel(frame_tec, text="# de Paneles:", text_color="#2c3e50").grid(row=0, column=0, sticky="e", pady=5, padx=5)
    ent_pan = ctk.CTkEntry(frame_tec, width=120, **estilo_entry)
    ent_pan.grid(row=0, column=1, sticky="w", padx=(0, 20), pady=5)
    if d[4]: ent_pan.insert(0, str(d[4]))
    
    ctk.CTkLabel(frame_tec, text="Potencia Panel (W):", text_color="#2c3e50").grid(row=0, column=2, sticky="e", pady=5, padx=5)
    ent_pot = ctk.CTkEntry(frame_tec, width=120, **estilo_entry)
    ent_pot.grid(row=0, column=3, sticky="w", padx=(0, 0), pady=5)
    if d[5]: ent_pot.insert(0, str(d[5]))

    ctk.CTkLabel(frame_tec, text="# de Inversores:", text_color="#2c3e50").grid(row=1, column=0, sticky="e", pady=5, padx=5)
    ent_inv = ctk.CTkEntry(frame_tec, width=120, **estilo_entry)
    ent_inv.grid(row=1, column=1, sticky="w", padx=(0, 20), pady=5)
    if d[6]: ent_inv.insert(0, str(d[6]))

    ctk.CTkLabel(scroll_or, text="Modelos de Inversores:", text_color="#2c3e50", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=(10,0))
    frame_modelos = ctk.CTkFrame(scroll_or, fg_color="transparent")
    frame_modelos.pack(fill="x", padx=10, pady=(0, 10))
    lista_modelos = []

    def add_modelo(qty="1", valor=""):
        f_mod = ctk.CTkFrame(frame_modelos, fg_color="transparent")
        f_mod.pack(fill="x", pady=3)
        ctk.CTkLabel(f_mod, text="Cant:", text_color="#2c3e50").pack(side="left", padx=(0, 5))
        e_qty = ctk.CTkEntry(f_mod, width=45, **estilo_entry)
        e_qty.pack(side="left")
        e_qty.insert(0, qty)
        ctk.CTkLabel(f_mod, text="Modelo:", text_color="#2c3e50").pack(side="left", padx=(15, 5))
        e_mod = ctk.CTkEntry(f_mod, width=320, **estilo_entry, placeholder_text="Ej: Huawei SUN2000-100KTL")
        e_mod.pack(side="left")
        e_mod.insert(0, valor)
        lista_modelos.append((e_qty, e_mod))
        def eliminar():
            f_mod.destroy()
            lista_modelos.remove((e_qty, e_mod))
        ctk.CTkButton(f_mod, text="X", width=30, fg_color="#e74c3c", hover_color="#c0392b", text_color="white", command=eliminar).pack(side="left", padx=10)

    ctk.CTkButton(scroll_or, text="+ Adicionar Modelo", fg_color="#8e44ad", hover_color="#732d91", text_color="white", command=add_modelo).pack(anchor="w", padx=10, pady=5)

    if d[7]:
        for mod in str(d[7]).split("|"):
            if mod.strip():
                partes = mod.strip().split("x ", 1)
                if len(partes) == 2 and partes[0].isdigit(): add_modelo(partes[0], partes[1])
                else: add_modelo("1", mod.strip())
    else: add_modelo("1", "")

    def guardar_popup():
        try:
            pan = int(ent_pan.get()) if ent_pan.get() else 0
            pot = float(ent_pot.get().replace(',','.')) if ent_pot.get() else 0.0
            n_inv = int(ent_inv.get()) if ent_inv.get() else 0
        except:
            messagebox.showerror("Error", "Los datos técnicos deben ser numéricos.")
            return

        mods_guardar_list = [f"{eq.get().strip() or '1'}x {em.get().strip()}" for eq, em in lista_modelos if em.get().strip()]
        mods_guardar = "|".join(mods_guardar_list)
        coord_unida = f"{ent_lat_or.get().strip()}, {ent_lon_or.get().strip()}"

        con = sqlite3.connect("sistema_gd_v4.db")
        con.execute('''UPDATE proyectos SET radicado=?, cod_validacion=?, circuito=?, coord_conexion=?, num_paneles=?, pot_panel=?, num_inversores=?, modelos_inversores=? WHERE id=?''', (ent_rad.get(), ent_cod.get(), ent_circ.get(), coord_unida, pan, pot, n_inv, mods_guardar, id_proyecto))
        if id_req: con.execute("UPDATE requisitos SET estado='RADICADO' WHERE id=?", (id_req,))
        con.commit()
        con.close()
        popup.destroy()
        if hasattr(ventana, 'refrescar_modulo_silencioso'): ventana.refrescar_modulo_silencioso()

    ctk.CTkButton(popup, text="Guardar Cambios" if not id_req else "Guardar Datos y Radicar", fg_color="#27ae60", hover_color="#2ecc71", text_color="white", font=("Arial", 15, "bold"), height=40, command=guardar_popup).pack(pady=20)

def pedir_fecha(titulo, callback):
    pop = ctk.CTkToplevel(ventana)
    pop.title(titulo)
    pop.geometry("300x250")
    pop.grab_set()
    pop.configure(fg_color="#f4f6f9")
    ctk.CTkLabel(pop, text=f"Selecciona la fecha:", font=("Arial", 16, "bold"), text_color="#2c3e50").pack(pady=20)
    cal = DateEntry(pop, background='#2980b9', foreground='white', date_pattern='dd/mm/yyyy')
    cal.pack(pady=10)
    def confirmar(): fecha = cal.get_date(); pop.destroy(); callback(fecha)
    def limpiar(): pop.destroy(); callback(None)
    ctk.CTkButton(pop, text="Guardar Fecha", fg_color="#27ae60", hover_color="#2ecc71", text_color="white", font=("Arial", 13, "bold"), command=confirmar).pack(pady=(10, 5))
    ctk.CTkButton(pop, text="Limpiar / Borrar Fecha", fg_color="#e74c3c", hover_color="#c0392b", text_color="white", font=("Arial", 13, "bold"), command=limpiar).pack(pady=5)

# ==========================================
# 5. VISTA DETALLADA DEL PROYECTO
# ==========================================
def editar_proyecto_popup(id_proyecto):
    pop = ctk.CTkToplevel(ventana)
    pop.title("Editar Proyecto")
    pop.geometry("700x620")
    pop.grab_set()
    pop.configure(fg_color="#f4f6f9")
    
    con = sqlite3.connect("sistema_gd_v4.db")
    datos = con.execute("SELECT cluster, nombre, departamento, municipio, direccion, latitud, longitud, area, capacidad_kw FROM proyectos WHERE id=?", (id_proyecto,)).fetchone()
    lista_clusters = ["N/A (Proyecto Individual)"] + [c[0] for c in con.execute("SELECT nombre_cluster FROM clusteres ORDER BY nombre_cluster ASC").fetchall()]
    con.close()

    ctk.CTkLabel(pop, text="Editar Datos del Proyecto", font=("Arial", 20, "bold"), text_color="#2c3e50").grid(row=0, column=0, columnspan=2, pady=(20,20))
    color_caja, borde_caja = "#ffffff", "#bdc3c7"
    
    ctk.CTkLabel(pop, text="Clúster:", text_color="#2c3e50", font=("Arial", 12, "bold")).grid(row=1, column=0, padx=20, pady=5, sticky="e")
    ent_cluster = ctk.CTkComboBox(pop, width=300, values=lista_clusters, fg_color=color_caja, text_color="#2c3e50", border_color=borde_caja)
    ent_cluster.grid(row=1, column=1, padx=20, pady=5, sticky="w")
    ent_cluster.set(datos[0] if datos[0] and datos[0] != "N/A" else "N/A (Proyecto Individual)")

    ctk.CTkLabel(pop, text="Nombre:", text_color="#2c3e50", font=("Arial", 12, "bold")).grid(row=2, column=0, padx=20, pady=5, sticky="e")
    ent_nombre = ctk.CTkEntry(pop, width=300, fg_color=color_caja, text_color="#2c3e50", border_color=borde_caja)
    ent_nombre.grid(row=2, column=1, padx=20, pady=5, sticky="w")
    ent_nombre.insert(0, datos[1] if datos[1] else "")

    ctk.CTkLabel(pop, text="Departamento:", text_color="#2c3e50", font=("Arial", 12, "bold")).grid(row=3, column=0, padx=20, pady=5, sticky="e")
    ent_depto = ctk.CTkComboBox(pop, width=300, values=DEPARTAMENTOS, fg_color=color_caja, text_color="#2c3e50", border_color=borde_caja)
    ent_depto.grid(row=3, column=1, padx=20, pady=5, sticky="w")
    ent_depto.set(datos[2] if datos[2] else "")

    ctk.CTkLabel(pop, text="Municipio:", text_color="#2c3e50", font=("Arial", 12, "bold")).grid(row=4, column=0, padx=20, pady=5, sticky="e")
    ent_muni = ctk.CTkEntry(pop, width=300, fg_color=color_caja, text_color="#2c3e50", border_color=borde_caja)
    ent_muni.grid(row=4, column=1, padx=20, pady=5, sticky="w")
    ent_muni.insert(0, datos[3] if datos[3] else "")

    ctk.CTkLabel(pop, text="Dirección:", text_color="#2c3e50", font=("Arial", 12, "bold")).grid(row=5, column=0, padx=20, pady=5, sticky="e")
    ent_dir = ctk.CTkEntry(pop, width=300, fg_color=color_caja, text_color="#2c3e50", border_color=borde_caja)
    ent_dir.grid(row=5, column=1, padx=20, pady=5, sticky="w")
    ent_dir.insert(0, datos[4] if datos[4] else "")

    ctk.CTkLabel(pop, text="Capacidad (kW):", text_color="#2c3e50", font=("Arial", 12, "bold")).grid(row=6, column=0, padx=20, pady=5, sticky="e")
    ent_cap = ctk.CTkEntry(pop, width=300, fg_color=color_caja, text_color="#2c3e50", border_color=borde_caja)
    ent_cap.grid(row=6, column=1, padx=20, pady=5, sticky="w")
    ent_cap.insert(0, str(datos[8]) if datos[8] else "0")

    ctk.CTkLabel(pop, text="Área (ha):", text_color="#2c3e50", font=("Arial", 12, "bold")).grid(row=7, column=0, padx=20, pady=5, sticky="e")
    ent_area = ctk.CTkEntry(pop, width=300, fg_color=color_caja, text_color="#2c3e50", border_color=borde_caja)
    ent_area.grid(row=7, column=1, padx=20, pady=5, sticky="w")
    ent_area.insert(0, str(datos[7]) if datos[7] else "0")

    ctk.CTkLabel(pop, text="Coordenadas del predio:", text_color="#2c3e50", font=("Arial", 12, "bold")).grid(row=8, column=0, padx=20, pady=5, sticky="e")
    coord_frame = ctk.CTkFrame(pop, fg_color="transparent")
    coord_frame.grid(row=8, column=1, padx=20, pady=5, sticky="w")
    ent_lat = ctk.CTkEntry(coord_frame, width=100, placeholder_text="Latitud", fg_color=color_caja, text_color="#2c3e50", border_color=borde_caja)
    ent_lat.pack(side="left", padx=(0, 8))
    ent_lon = ctk.CTkEntry(coord_frame, width=100, placeholder_text="Longitud", fg_color=color_caja, text_color="#2c3e50", border_color=borde_caja)
    ent_lon.pack(side="left", padx=(0, 8))
    if datos[5]: ent_lat.insert(0, str(datos[5]))
    if datos[6]: ent_lon.insert(0, str(datos[6]))
    ctk.CTkButton(coord_frame, text="📍 Mapa", width=100, command=lambda: abrir_mapa_predio(ent_lat, ent_lon, ent_muni.get(), ent_depto.get())).pack(side="left")

    def guardar_edicion():
        try:
            cap, ar = float(ent_cap.get().replace(',', '.') if ent_cap.get() else "0"), float(ent_area.get().replace(',', '.') if ent_area.get() else "0")
        except:
            messagebox.showerror("Error", "La capacidad y el área deben ser numéricos.")
            return
        c_sel = ent_cluster.get()
        cluster_final = "N/A" if "Individual" in c_sel else c_sel.upper()
        con = sqlite3.connect("sistema_gd_v4.db")
        con.execute('''UPDATE proyectos SET cluster=?, nombre=?, departamento=?, municipio=?, direccion=?, latitud=?, longitud=?, capacidad_kw=?, area=? WHERE id=?''', (cluster_final, ent_nombre.get(), ent_depto.get(), ent_muni.get(), ent_dir.get(), ent_lat.get(), ent_lon.get(), cap, ar, id_proyecto))
        con.commit()
        con.close()
        pop.destroy()
        ventana.after(10, lambda: mostrar_detalles(id_proyecto))

    ctk.CTkButton(pop, text="💾 Guardar Cambios", fg_color="#27ae60", hover_color="#2ecc71", text_color="white", font=("Arial", 14, "bold"), command=guardar_edicion).grid(row=9, column=0, columnspan=2, pady=30)

def mostrar_detalles(id_proyecto, modulos_abiertos=None):
    if modulos_abiertos is None: modulos_abiertos = []
    limpiar_area_principal()
    
    con = sqlite3.connect("sistema_gd_v4.db")
    proyecto = con.execute("SELECT cluster, nombre, radicado, cod_validacion, circuito, coord_conexion, fecha_creacion, estado_general, capacidad_kw, req_servidumbre, req_contrato FROM proyectos WHERE id = ?", (id_proyecto,)).fetchone()
    categorias = [cat[0] for cat in con.execute("SELECT DISTINCT categoria FROM requisitos WHERE proyecto_id = ?", (id_proyecto,)).fetchall()]
    todos_los_requisitos = con.execute("SELECT id, categoria, descripcion, entidad, estado, fecha_radicacion, fecha_limite, fecha_final, evidencia_ruta, evidencia_respuesta, observaciones FROM requisitos WHERE proyecto_id = ?", (id_proyecto,)).fetchall()
    con.close()

    cluster_actual, req_servidumbre, req_contrato = proyecto[0], bool(proyecto[9]), bool(proyecto[10])

    marco_cabecera = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_cabecera.pack(fill="x", pady=(0, 10), padx=10)
    botones_top = ctk.CTkFrame(marco_cabecera, fg_color="transparent")
    botones_top.pack(fill="x", padx=15, pady=15)
    ctk.CTkButton(botones_top, text="← Volver al Consolidado", width=150, fg_color="#e5e8e8", hover_color="#d5d8dc", text_color="#2c3e50", font=("Arial", 14, "bold"), command=mostrar_lista).pack(side="left")

    def eliminar_proyecto():
        if messagebox.askyesno("ELIMINAR PROYECTO", "¿Estás seguro de eliminar permanentemente este proyecto?"):
            con = sqlite3.connect("sistema_gd_v4.db")
            con.execute("DELETE FROM requisitos WHERE proyecto_id = ?", (id_proyecto,))
            con.execute("DELETE FROM proyectos WHERE id = ?", (id_proyecto,))
            con.commit()
            con.close()
            mostrar_lista()
            
    def duplicar_proyecto():
        nuevo_nombre = ctk.CTkInputDialog(text="Ingresa el nombre para el nuevo proyecto:", title="Duplicar Proyecto").get_input()
        if nuevo_nombre:
            con = sqlite3.connect("sistema_gd_v4.db")
            datos = con.execute("SELECT cluster, municipio, departamento, direccion, latitud, longitud, area, capacidad_kw, req_servidumbre, req_contrato FROM proyectos WHERE id = ?", (id_proyecto,)).fetchone()
            if datos:
                cur = con.cursor()
                cur.execute('''INSERT INTO proyectos (cluster, nombre, municipio, departamento, direccion, latitud, longitud, area, capacidad_kw, fecha_creacion, estado_general, req_servidumbre, req_contrato) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVO', ?, ?)''', (datos[0], nuevo_nombre, datos[1], datos[2], datos[3], datos[4], datos[5], datos[6], datos[7], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), datos[8], datos[9]))
                nuevo_id = cur.lastrowid
                for req in REQUISITOS_BASE: cur.execute("INSERT INTO requisitos (proyecto_id, categoria, descripcion, entidad, estado, observaciones) VALUES (?, ?, ?, ?, 'PENDIENTE', '')", (nuevo_id, req[0], req[1], req[2]))
                con.commit()
                messagebox.showinfo("Éxito", f"Proyecto duplicado correctamente.")
                mostrar_lista() 
            con.close()

    if usuario_actual and usuario_actual[2] == "Administrador":
        ctk.CTkButton(botones_top, text="🗑 Eliminar", width=100, fg_color="#e74c3c", hover_color="#c0392b", text_color="white", font=("Arial", 12, "bold"), command=eliminar_proyecto).pack(side="right")
        ctk.CTkButton(botones_top, text="📄 Duplicar", width=100, fg_color="#3498db", hover_color="#2980b9", text_color="white", font=("Arial", 12, "bold"), command=duplicar_proyecto).pack(side="right", padx=(0, 15))
        ctk.CTkButton(botones_top, text="✏ Editar", width=100, fg_color="#f1c40f", hover_color="#d4ac0d", text_color="black", font=("Arial", 12, "bold"), command=lambda: editar_proyecto_popup(id_proyecto)).pack(side="right", padx=(0, 15))

    estado_actual, capacidad = (proyecto[7] if len(proyecto) > 7 and proyecto[7] else "ACTIVO"), (proyecto[8] if len(proyecto) > 8 and proyecto[8] else 0.0)
    marco_titulo_estado = ctk.CTkFrame(marco_cabecera, fg_color="transparent")
    marco_titulo_estado.pack(fill="x", anchor="w", padx=15, pady=(0, 15))
    ctk.CTkLabel(marco_titulo_estado, text=f"[{cluster_actual if cluster_actual and cluster_actual != 'N/A' else 'Individual'}] {proyecto[1]} ({capacidad:,.0f} kW)", font=("Arial", 28, "bold"), text_color="#154360").pack(side="left")

    def cambiar_estado_general(nuevo_estado):
        con = sqlite3.connect("sistema_gd_v4.db")
        con.execute("UPDATE proyectos SET estado_general = ? WHERE id = ?", (nuevo_estado, id_proyecto))
        con.commit()
        con.close()
        lbl_estado_gen.after(10, lambda: lbl_estado_gen.configure(text=f"ESTADO: {nuevo_estado}", text_color={"ACTIVO": "#27ae60", "PAUSADO": "#d4ac0d", "DESCARTADO": "#e74c3c"}.get(nuevo_estado, "gray")))

    lbl_estado_gen = ctk.CTkLabel(marco_titulo_estado, text=f"ESTADO: {estado_actual}", font=("Arial", 16, "bold"), text_color={"ACTIVO": "#27ae60", "PAUSADO": "#d4ac0d", "DESCARTADO": "#e74c3c"}.get(estado_actual, "gray"))
    lbl_estado_gen.pack(side="left", padx=(30, 10))
    
    if usuario_actual and usuario_actual[2] == "Administrador":
        selector_est_gen = ctk.CTkOptionMenu(marco_titulo_estado, values=["ACTIVO", "PAUSADO", "DESCARTADO"], command=cambiar_estado_general, width=130, fg_color="#f4f6f9", text_color="#2c3e50")
        selector_est_gen.set(estado_actual)
        selector_est_gen.pack(side="left")

    if proyecto[2]: 
        marco_or = ctk.CTkFrame(marco_cabecera, fg_color="transparent")
        marco_or.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkLabel(marco_or, text=f"Radicado: {proyecto[2]} | Cód: {proyecto[3]} | Circuito: {proyecto[4]} | Pto. Conex: {proyecto[5]}", font=("Arial", 16, "bold"), text_color="#2980b9").pack(side="left")

    marco_toggles = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_toggles.pack(fill="x", pady=(0, 15), padx=10)
    caja_switches = ctk.CTkFrame(marco_toggles, fg_color="transparent")
    caja_switches.pack(fill="x", padx=15, pady=10)

    ventana.refrescar_modulo_silencioso = lambda: mostrar_detalles(id_proyecto, [c for c, is_open in estados_modulos.items() if is_open])

    def toggle_serv():
        con = sqlite3.connect("sistema_gd_v4.db")
        con.execute("UPDATE proyectos SET req_servidumbre = ? WHERE id = ?", (1 if switch_serv.get() else 0, id_proyecto))
        con.commit()
        con.close()
        mostrar_detalles(id_proyecto, [c for c, is_open in estados_modulos.items() if is_open])

    def toggle_cont():
        con = sqlite3.connect("sistema_gd_v4.db")
        con.execute("UPDATE proyectos SET req_contrato = ? WHERE id = ?", (1 if switch_cont.get() else 0, id_proyecto))
        con.commit()
        con.close()
        mostrar_detalles(id_proyecto, [c for c, is_open in estados_modulos.items() if is_open])

    estado_toggles = "normal" if usuario_actual and usuario_actual[2] == "Administrador" else "disabled"
    switch_serv = ctk.CTkSwitch(caja_switches, text="Requerir Servidumbre", text_color="#2c3e50", font=("Arial", 15, "bold"), command=toggle_serv, progress_color="#3498db", state=estado_toggles)
    switch_serv.pack(side="left", padx=(0, 20))
    if req_servidumbre: switch_serv.select()

    switch_cont = ctk.CTkSwitch(caja_switches, text="Requerir Modelo de Contrato", text_color="#2c3e50", font=("Arial", 15, "bold"), command=toggle_cont, progress_color="#3498db", state=estado_toggles)
    switch_cont.pack(side="left")
    if req_contrato: switch_cont.select()

    botones_modulos, estados_modulos, modulos_cargados, botones_ver_docs = {}, {}, {}, {}

    def actualizar_boton_soporte_inplace(req_id, tipo_columna, num_archivos):
        if f"{req_id}_{tipo_columna}" in botones_ver_docs:
            btn = botones_ver_docs[f"{req_id}_{tipo_columna}"]
            btn.configure(text=f"📂 Ver ({num_archivos})")
            if num_archivos > 0: btn.pack(side="right", padx=5) 
    ventana.actualizar_boton_soporte_inplace = actualizar_boton_soporte_inplace

    def refrescar_porcentaje_modulo(categoria):
        con = sqlite3.connect("sistema_gd_v4.db")
        reqs = con.execute("SELECT estado FROM requisitos WHERE proyecto_id = ? AND categoria = ?", (id_proyecto, categoria)).fetchall()
        con.close()
        
        tot = len(reqs)
        comp = sum(1 for r in reqs if r[0] == "COMPLETADO")
        pend = sum(1 for r in reqs if r[0] == "PENDIENTE")
        atend = tot - comp - pend
        pct = (comp / tot * 100) if tot > 0 else 0
        
        btn = botones_modulos.get(categoria)
        if btn:
            flecha = "▼" if estados_modulos.get(categoria, False) else "▶"
            texto_extra = " (No suma al promedio general)" if categoria in ["Ingeniería Básica", "Análisis Técnico"] else ""
            btn.configure(text=f"{flecha}  {categoria.upper()}   |   Avance: {pct:.0f}%  (Comp: {comp} | Atend: {atend} | Pend: {pend}){texto_extra}")
            btn.configure(fg_color="#27ae60" if pct == 100 else "#3498db" if pct > 0 else "#ffffff", hover_color="#2ecc71" if pct == 100 else "#2980b9" if pct > 0 else "#f4f6f9", text_color="white" if pct > 0 else "#2c3e50")

    def actualizar_estado_local(id_req, descripcion, nuevo_estado, lbl_estado, cat):
        if "2.2" in descripcion and nuevo_estado == "RADICADO":
            ventana.after(10, lambda: abrir_popup_2_2(id_proyecto, id_req))
            return
        con = sqlite3.connect("sistema_gd_v4.db")
        con.execute("UPDATE requisitos SET estado = ? WHERE id = ?", (nuevo_estado, id_req))
        con.commit()
        con.close()
        lbl_estado.configure(text=f"■ {nuevo_estado}", text_color=ESTADOS_COLORES.get(nuevo_estado, "gray50"))
        refrescar_porcentaje_modulo(cat)

    def fijar_radicacion_local(id_req, lbl_limite, btn_radicar):
        def callback(fecha_rad):
            con = sqlite3.connect("sistema_gd_v4.db")
            if fecha_rad is None:
                con.execute("UPDATE requisitos SET fecha_radicacion = '', fecha_limite = '' WHERE id = ?", (id_req,))
                lbl_limite.configure(text="Límite: -")
                btn_radicar.configure(text="📅 Fijar Radicación")
            else:
                fecha_lim = sumar_dias_habiles(fecha_rad, 15)
                con.execute("UPDATE requisitos SET fecha_radicacion = ?, fecha_limite = ? WHERE id = ?", (fecha_rad.strftime("%d/%m/%Y"), fecha_lim.strftime("%d/%m/%Y"), id_req))
                lbl_limite.configure(text=f"Límite (15d): {fecha_lim.strftime('%d/%m/%Y')}")
                btn_radicar.configure(text=f"Radicado: {fecha_rad.strftime('%d/%m/%Y')}")
            con.commit()
            con.close()
        pedir_fecha("Fecha de Radicación", callback)

    def fijar_final_local(id_req, selector_est, lbl_est, btn_fin, cat):
        def callback(fecha_fin):
            con = sqlite3.connect("sistema_gd_v4.db")
            if fecha_fin is None:
                estado_actual = con.execute("SELECT estado FROM requisitos WHERE id = ?", (id_req,)).fetchone()[0]
                nuevo_estado = "EN TRÁMITE" if estado_actual == "COMPLETADO" else estado_actual
                con.execute("UPDATE requisitos SET fecha_final = '', estado = ? WHERE id = ?", (nuevo_estado, id_req))
                btn_fin.configure(text="📅 Fijar Cierre")
                selector_est.set(nuevo_estado)
                lbl_est.configure(text=f"■ {nuevo_estado}", text_color=ESTADOS_COLORES.get(nuevo_estado, "gray50"))
            else:
                fecha_fin_str = fecha_fin.strftime("%d/%m/%Y")
                con.execute("UPDATE requisitos SET fecha_final = ?, estado = 'COMPLETADO' WHERE id = ?", (fecha_fin_str, id_req))
                btn_fin.configure(text=f"Cierre: {fecha_fin_str}")
                selector_est.set("COMPLETADO")
                lbl_est.configure(text=f"■ COMPLETADO", text_color=ESTADOS_COLORES["COMPLETADO"])
            con.commit()
            con.close()
            refrescar_porcentaje_modulo(cat)
        pedir_fecha("Fecha Final / Cierre", callback)

    def guardar_observacion_local(id_req, caja_texto, boton):
        con = sqlite3.connect("sistema_gd_v4.db")
        con.execute("UPDATE requisitos SET observaciones = ? WHERE id = ?", (caja_texto.get("1.0", "end-1c"), id_req))
        con.commit()
        con.close()
        boton.configure(text="✔ Guardado", fg_color="green", text_color="white")
        ventana.after(2000, lambda: boton.configure(text="💾 Guardar", fg_color="#ecf0f1", text_color="#2c3e50"))

    def redirigir_scroll(e):
        try: area_principal._parent_canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        except: pass
        return "break"

    # NUEVO: Función chunking/lazy-loading para cero LAG
    def cargar_contenido_modulo_chunked(categoria, marco_padre):
        reqs_categoria = [r for r in todos_los_requisitos if r[1] == categoria]

        def render_chunk(index):
            if not marco_padre.winfo_exists(): return
            if index < len(reqs_categoria):
                req = reqs_categoria[index]
                id_req, cat, desc, ent, est, f_rad, f_lim, f_fin, ruta_ev_rad, ruta_ev_resp, obs = req
                
                if est not in ["COMPLETADO", "VENCIDO"] and f_lim and f_lim != "Sin definir":
                    try:
                        if datetime.datetime.strptime(f_lim, "%d/%m/%Y").date() < datetime.date.today():
                            est = "VENCIDO"
                            cur2 = sqlite3.connect("sistema_gd_v4.db").cursor()
                            cur2.execute("UPDATE requisitos SET estado = 'VENCIDO' WHERE id = ?", (id_req,))
                            cur2.connection.commit()
                            cur2.close()
                    except: pass

                marco_req = ctk.CTkFrame(marco_padre, fg_color="#ffffff", border_width=1, border_color="#d5d8dc", corner_radius=10) 
                marco_req.pack(fill="x", pady=5, padx=20) 

                marco_superior = ctk.CTkFrame(marco_req, fg_color="transparent")
                marco_superior.pack(fill="x", padx=15, pady=(10,0))
                ctk.CTkLabel(marco_superior, text=desc, font=("Arial", 16, "bold"), text_color="#154360", wraplength=700, justify="left").pack(side="left")
                lbl_est = ctk.CTkLabel(marco_superior, text=f"■ {est}", font=("Arial", 16, "bold"), text_color=ESTADOS_COLORES.get(est, "gray50"))
                lbl_est.pack(side="right")
                ctk.CTkLabel(marco_req, text=f"Entidad: {ent}", font=("Arial", 13), text_color="#7f8c8d").pack(anchor="w", padx=15)

                marco_radicacion = ctk.CTkFrame(marco_req, fg_color="#f8f9f9", corner_radius=5, border_width=1, border_color="#e5e8e8")
                marco_radicacion.pack(fill="x", padx=15, pady=(5, 2))
                
                btn_radicar = ctk.CTkButton(marco_radicacion, text=f"Radicado: {f_rad}" if f_rad else "📅 Fijar Radicación", width=120, fg_color="#34495e", text_color="white")
                lbl_lim = ctk.CTkLabel(marco_radicacion, text=f"Límite (15d): {f_lim}" if f_lim else "Límite: -", text_color="#d35400", font=("Arial", 13, "bold"))
                btn_radicar.configure(command=lambda i=id_req, l=lbl_lim, b=btn_radicar: ventana.after(10, lambda req=i, lbl=l, btn=b: fijar_radicacion_local(req, lbl, btn)))
                btn_radicar.pack(side="left", padx=10, pady=5)
                lbl_lim.pack(side="left", padx=(0, 20))

                if "2.2" in desc: ctk.CTkButton(marco_radicacion, text="✏ Editar Info OR", width=120, fg_color="#d35400", hover_color="#ba4a00", text_color="white", font=("Arial", 12, "bold"), command=lambda i=id_proyecto: abrir_popup_2_2(i)).pack(side="left", padx=10, pady=5)

                rutas_rad_list = [r for r in (ruta_ev_rad.split("|") if ruta_ev_rad else []) if r.strip()]
                btn_ver_rad = ctk.CTkButton(marco_radicacion, text=f"📂 Ver ({len(rutas_rad_list)})", width=70, fg_color="#2980b9", hover_color="#1f618d", text_color="white", command=lambda i=id_req: abrir_popup_soportes(i, id_proyecto, "evidencia_ruta"))
                btn_ver_rad.pack(side="right", padx=5, pady=5)
                botones_ver_docs[f"{id_req}_evidencia_ruta"] = btn_ver_rad
                ctk.CTkButton(marco_radicacion, text="📎 Adjuntar Radicado", width=120, fg_color="#1abc9c", text_color="white", hover_color="#16a085", font=("Arial", 12, "bold"), command=lambda i=id_req: adjuntar_soportes_multiples(i, "evidencia_ruta")).pack(side="right", pady=5)

                marco_cierre = ctk.CTkFrame(marco_req, fg_color="#f8f9f9", corner_radius=5, border_width=1, border_color="#e5e8e8")
                marco_cierre.pack(fill="x", padx=15, pady=(2, 5))

                selector_estado = ctk.CTkOptionMenu(marco_cierre, values=list(ESTADOS_COLORES.keys()), width=160, fg_color="#ffffff", text_color="#2c3e50", command=lambda val, req_id=id_req, d=desc, l_est=lbl_est, c=categoria: ventana.after(10, lambda v=val, i=req_id, de=d, le=l_est, ca=c: actualizar_estado_local(i, de, v, le, ca)))
                selector_estado.set(est)
                selector_estado.pack(side="left", padx=10, pady=5)

                btn_finalizar = ctk.CTkButton(marco_cierre, text=f"Cierre: {f_fin}" if f_fin else "📅 Fijar Cierre", width=100, fg_color="#27ae60", hover_color="#2ecc71", text_color="white")
                btn_finalizar.configure(command=lambda i=id_req, sel=selector_estado, le=lbl_est, bf=btn_finalizar, c=categoria: ventana.after(10, lambda req=i, sele=sel, lest=le, bfin=bf, ca=c: fijar_final_local(req, sele, lest, bfin, ca)))
                btn_finalizar.pack(side="left")

                if cluster_actual and cluster_actual != "N/A" and "Individual" not in cluster_actual:
                    if usuario_actual and usuario_actual[2] == "Administrador":
                        ctk.CTkButton(marco_cierre, text="🔄 Replicar", width=80, fg_color="#8e44ad", hover_color="#732d91", text_color="white", command=lambda i=id_req: replicar_requisito_cluster(i, id_proyecto, cluster_actual)).pack(side="left", padx=10)

                rutas_resp_list = [r for r in (ruta_ev_resp.split("|") if ruta_ev_resp else []) if r.strip()]
                btn_ver_resp = ctk.CTkButton(marco_cierre, text=f"📂 Ver ({len(rutas_resp_list)})", width=70, fg_color="#2980b9", hover_color="#1f618d", text_color="white", command=lambda i=id_req: abrir_popup_soportes(i, id_proyecto, "evidencia_respuesta"))
                btn_ver_resp.pack(side="right", padx=5, pady=5)
                botones_ver_docs[f"{id_req}_evidencia_respuesta"] = btn_ver_resp
                ctk.CTkButton(marco_cierre, text="📎 Adjuntar Respuesta", width=120, fg_color="#f39c12", text_color="white", hover_color="#d35400", font=("Arial", 12, "bold"), command=lambda i=id_req: adjuntar_soportes_multiples(i, "evidencia_respuesta")).pack(side="right", pady=5)

                marco_obs = ctk.CTkFrame(marco_req, fg_color="transparent")
                marco_obs.pack(fill="x", padx=15, pady=(5, 15))
                ctk.CTkLabel(marco_obs, text="Observaciones:", text_color="#2c3e50", font=("Arial", 13, "bold")).pack(side="left", padx=(0, 10))
                
                caja_obs = ctk.CTkTextbox(marco_obs, height=45, fg_color="#ffffff", border_color="#bdc3c7", border_width=1, text_color="black")
                caja_obs.pack(side="left", fill="x", expand=True, padx=(0, 10))
                if obs: caja_obs.insert("1.0", obs)
                try: (caja_obs._textbox if hasattr(caja_obs, '_textbox') else caja_obs).bind("<" + "MouseWheel" + ">", redirigir_scroll)
                except: pass
                    
                btn_guardar_obs = ctk.CTkButton(marco_obs, text="💾 Guardar", width=80, fg_color="#ecf0f1", text_color="#2c3e50", hover_color="#d5d8dc")
                btn_guardar_obs.configure(command=lambda i=id_req, c=caja_obs, b=btn_guardar_obs: guardar_observacion_local(i, c, b))
                btn_guardar_obs.pack(side="right")

                # Carga retardada de la siguiente tarjeta para cero lag
                ventana.after(10, render_chunk, index + 1)
            else:
                modulos_cargados[categoria] = True
                marco_padre.pack(fill="x", pady=(0, 10))
                estados_modulos[categoria] = True
                refrescar_porcentaje_modulo(categoria)

        render_chunk(0)

    def toggle_modulo(categoria, marco_contenido):
        if not modulos_cargados[categoria]:
            btn = botones_modulos.get(categoria)
            if btn: btn.configure(text=f"⏳ Cargando módulo {categoria}...")
            ventana.update_idletasks()
            cargar_contenido_modulo_chunked(categoria, marco_contenido)
        else:
            if estados_modulos[categoria]: 
                marco_contenido.pack_forget()
                estados_modulos[categoria] = False
            else: 
                marco_contenido.pack(fill="x", pady=(0, 10))
                estados_modulos[categoria] = True
            refrescar_porcentaje_modulo(categoria)

    for cat in categorias:
        if (cat == "Servidumbre" and not req_servidumbre) or (cat == "Modelo de Contrato" and not req_contrato): continue
        marco_categoria = ctk.CTkFrame(area_principal, fg_color="transparent")
        marco_categoria.pack(fill="x", pady=5, padx=10)
        btn_header = ctk.CTkButton(marco_categoria, height=50, font=("Arial", 16, "bold"), anchor="w", corner_radius=8, border_width=1, border_color="#d5d8dc")
        btn_header.pack(fill="x")
        marco_contenido = ctk.CTkFrame(marco_categoria, fg_color="transparent")
        botones_modulos[cat], estados_modulos[cat], modulos_cargados[cat] = btn_header, False, False 
        btn_header.configure(command=lambda c=cat, mc=marco_contenido: toggle_modulo(c, mc))
        refrescar_porcentaje_modulo(cat)
        if cat in modulos_abiertos:
            toggle_modulo(cat, marco_contenido)

# ==========================================
# 6. CONSOLIDADO
# ==========================================
def mostrar_lista():
    limpiar_area_principal()
    render_cabecera(area_principal)
    marco_busq = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_busq.pack(fill="x", padx=10)
    ctk.CTkLabel(marco_busq, text="CONSOLIDADO DE PROYECTOS", font=("Arial", 22, "bold"), text_color="#f39c12").pack(side="left", padx=20, pady=15)
    entry_busqueda = ctk.CTkEntry(marco_busq, placeholder_text="Buscar proyecto, municipio, clúster o OR...", width=350, fg_color="#ffffff", text_color="#2c3e50", border_color="#bdc3c7")
    entry_busqueda.pack(side="right", padx=20)
    marco_lista = ctk.CTkFrame(area_principal, fg_color="transparent")
    marco_lista.pack(fill="both", expand=True, pady=10, padx=10)

    def cargar_datos(filtro=""):
        for w in marco_lista.winfo_children(): w.destroy()
        con = sqlite3.connect("sistema_gd_v4.db")
        proyectos_brutos = con.execute("SELECT id, nombre, cluster, estado_general, capacidad_kw, req_servidumbre, req_contrato, municipio, radicado, circuito FROM proyectos ORDER BY cluster ASC, id ASC").fetchall()
        con.close()

        if filtro: proyectos_brutos = [p for p in proyectos_brutos if filtro.lower() in f"{p[1]} {p[2]} {p[7]} {p[8]} {p[9]}".lower()]
        if not proyectos_brutos:
            ctk.CTkLabel(marco_lista, text="No se encontraron proyectos activos para esta búsqueda.", text_color="#2c3e50", font=("Arial", 16)).pack(pady=30)
            return

        diccionario_clusters = {}
        for p in proyectos_brutos:
            cluster_limpio = p[2].strip().upper() if p[2] and p[2] != "N/A" else "Individual"
            if cluster_limpio not in diccionario_clusters: diccionario_clusters[cluster_limpio] = []
            diccionario_clusters[cluster_limpio].append(p)

        def toggle_cluster(marco_proyectos, btn_header, cl_nombre, cant_proys, sum_kw, estado_abierto):
            txt = f"▶ CLÚSTER: {cl_nombre} ({cant_proys} Proyectos)  |  Capacidad: {sum_kw:,.0f} kW"
            if estado_abierto[0]: marco_proyectos.pack_forget(); btn_header.configure(text=txt.replace("▼", "▶")); estado_abierto[0] = False
            else: marco_proyectos.pack(fill="x", pady=(0, 10)); btn_header.configure(text=txt.replace("▶", "▼")); estado_abierto[0] = True

        for nombre_cluster, lista_proyectos in diccionario_clusters.items():
            marco_grupo = ctk.CTkFrame(marco_lista, fg_color="transparent")
            marco_grupo.pack(fill="x", pady=5)
            suma_kw = sum([float(p[4]) if p[4] else 0.0 for p in lista_proyectos])
            cant_proys = len(lista_proyectos)
            btn_cluster = ctk.CTkButton(marco_grupo, text=f"▶ CLÚSTER: {nombre_cluster} ({cant_proys} Proyectos)  |  Capacidad: {suma_kw:,.0f} kW", font=("Arial", 18, "bold"), anchor="w", height=50, fg_color="#e5e8e8", text_color="#2c3e50", border_color="#bdc3c7", border_width=1, hover_color="#d5d8dc")
            btn_cluster.pack(fill="x")
            marco_proyectos = ctk.CTkFrame(marco_grupo, fg_color="transparent")
            estado_abierto = [False] 
            btn_cluster.configure(command=lambda m=marco_proyectos, b=btn_cluster, n=nombre_cluster, c=cant_proys, s=suma_kw, e=estado_abierto: toggle_cluster(m, b, n, c, s, e))
            
            for p in lista_proyectos:
                id_proy, nombre, _, est_gen, cap_kw, r_serv, r_cont, muni, rad, circ = p
                con = sqlite3.connect("sistema_gd_v4.db")
                reqs = con.execute("SELECT categoria, estado FROM requisitos WHERE proyecto_id = ?", (id_proy,)).fetchall()
                con.close()
                reqs_validos = [est for cat, est in reqs if cat not in ["Ingeniería Básica", "Análisis Técnico"] and not (cat == "Servidumbre" and not r_serv) and not (cat == "Modelo de Contrato" and not r_cont)]
                
                total = len(reqs_validos)
                comps = sum(1 for e in reqs_validos if e == "COMPLETADO")
                pend = sum(1 for e in reqs_validos if e == "PENDIENTE")
                atend = total - comps - pend
                porcentaje = (comps / total * 100) if total > 0 else 0
                color_barra = "green" if porcentaje > 70 else "yellow" if porcentaje > 40 else "red"

                tarjeta = ctk.CTkFrame(marco_proyectos, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
                tarjeta.pack(pady=8, padx=(40, 20), fill="x") 
                marco_texto = ctk.CTkFrame(tarjeta, fg_color="transparent")
                marco_texto.pack(fill="x", padx=15, pady=(15, 5))
                
                cap = float(cap_kw) if cap_kw else 0.0
                texto_proyecto = f"Proyecto: {nombre} ({cap:,.0f} kW)" + (f" [{est_gen}]" if est_gen and est_gen != "ACTIVO" else "")
                ctk.CTkLabel(marco_texto, text=texto_proyecto, font=("Arial", 16, "bold"), text_color="#e74c3c" if est_gen == "DESCARTADO" else "#d4ac0d" if est_gen == "PAUSADO" else "#154360").pack(side="left")
                ctk.CTkLabel(marco_texto, text=f"Avance: {porcentaje:.1f}% (Comp: {comps} | Atend: {atend} | Pend: {pend})", font=("Arial", 14, "bold"), text_color=color_barra).pack(side="right")

                barra = ctk.CTkProgressBar(tarjeta, height=12, progress_color=color_barra, fg_color="#ecf0f1")
                barra.pack(fill="x", padx=15, pady=(0, 15))
                barra.set(porcentaje / 100) 
                ctk.CTkButton(tarjeta, text="Abrir Proyecto", width=120, fg_color="#3498db", hover_color="#2980b9", text_color="white", font=("Arial", 12, "bold"), command=lambda id=id_proy: mostrar_detalles(id)).pack(pady=(0,15))

    ventana.search_after_id = None
    def on_search(event):
        if ventana.search_after_id: ventana.after_cancel(ventana.search_after_id)
        ventana.search_after_id = ventana.after(600, lambda: cargar_datos(entry_busqueda.get()))
    entry_busqueda.bind("<" + "KeyRelease" + ">", on_search)
    cargar_datos() 

# ==========================================
# 7. DASHBOARD Y PANEL DE CRONOGRAMA OR
# ==========================================
def mostrar_dashboard():
    plt.close('all') 
    limpiar_area_principal()
    
    con = sqlite3.connect("sistema_gd_v4.db")
    proyectos = con.execute("SELECT id, area, capacidad_kw, req_servidumbre, req_contrato, estado_general, cluster, nombre FROM proyectos ORDER BY id ASC").fetchall()
    todos_reqs = con.execute("SELECT proyecto_id, categoria, estado, entidad, descripcion, fecha_final, fecha_radicacion FROM requisitos").fetchall()
    con.close()

    reqs_by_proj = {p[0]: [] for p in proyectos}
    for r in todos_reqs: reqs_by_proj[r[0]].append(r)

    kw_ejec, kw_proy, ha_ejec, ha_proy, proy_ejec_count, proy_proy_count, proy_desc_count = 0.0, 0.0, 0.0, 0.0, 0, 0, 0
    reqs_validos_globales, clusters_unicos = [], set()

    for p in proyectos:
        pid, area, cap, r_serv, r_cont, est_gen, cluster, nombre = p
        if est_gen == 'DESCARTADO':
            proy_desc_count += 1
            continue
        a, c = float(area) if area else 0.0, float(cap) if cap else 0.0
        cluster_val = cluster if cluster and cluster != "N/A" else "Individual"
        clusters_unicos.add(cluster_val)

        reqs_validos_p = []
        for r in reqs_by_proj.get(pid, []):
            if r[1] not in ["Ingeniería Básica", "Análisis Técnico"] and not (r[1] == "Servidumbre" and not r_serv) and not (r[1] == "Modelo de Contrato" and not r_cont):
                reqs_validos_p.append(r)
                reqs_validos_globales.append((pid, r[1], r[2], r[3], cluster_val))

        tot = len(reqs_validos_p)
        comps = sum(1 for r in reqs_validos_p if r[2] == 'COMPLETADO')

        if tot > 0 and tot == comps: kw_ejec += c; ha_ejec += a; proy_ejec_count += 1
        else: kw_proy += c; ha_proy += a; proy_proy_count += 1

    total_proyectos = proy_ejec_count + proy_proy_count + proy_desc_count
    estados_validos = [r[2] for r in reqs_validos_globales]
    total_req_count, total_completados, total_pendientes = len(estados_validos), estados_validos.count("COMPLETADO"), estados_validos.count("PENDIENTE")
    total_atendidos = total_req_count - total_completados - total_pendientes
    eficiencia = (total_completados / total_req_count * 100) if total_req_count > 0 else 0

    render_cabecera(area_principal)
    marco_dash_bg = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_dash_bg.pack(fill="x", padx=10, pady=(0, 15))
    ctk.CTkLabel(marco_dash_bg, text="📈 Dashboard Analítico Global", font=("Arial", 22, "bold"), text_color="#f39c12").pack(anchor="w", pady=15, padx=20)
    
    marco_kpis = ctk.CTkFrame(marco_dash_bg, fg_color="transparent")
    marco_kpis.pack(fill="x", padx=10, pady=(0, 15))

    def crear_tarjeta_kpi(master, titulo, valor_prin, valor_sec, color_texto):
        tarjeta = ctk.CTkFrame(master, fg_color="#f8f9f9", corner_radius=10, border_width=1, border_color="#d5d8dc")
        tarjeta.pack(side="left", expand=True, fill="both", padx=5)
        ctk.CTkLabel(tarjeta, text=titulo, font=("Arial", 12, "bold"), text_color="#7f8c8d").pack(pady=(10, 2))
        ctk.CTkLabel(tarjeta, text=valor_prin, font=("Arial", 20, "bold"), text_color=color_texto).pack(pady=(0, 2))
        ctk.CTkLabel(tarjeta, text=valor_sec, font=("Arial", 11), text_color="#7f8c8d").pack(pady=(0, 10))

    crear_tarjeta_kpi(marco_kpis, "Proyectos Portafolio", f"{total_proyectos}", f"Ejec: {proy_ejec_count} | Proy: {proy_proy_count} | Desc: {proy_desc_count}", "#3498db")
    crear_tarjeta_kpi(marco_kpis, "Total Clústeres", f"{len(clusters_unicos)}", "Agrupaciones Activas", "#9b59b6")
    crear_tarjeta_kpi(marco_kpis, "Generación (kW)", f"{kw_ejec:,.0f} kW", f"Proyectado: {kw_proy:,.0f} kW", "#2ecc71")
    crear_tarjeta_kpi(marco_kpis, "Área Total (ha)", f"{ha_ejec:,.1f} ha", f"Proyectada: {ha_proy:,.1f} ha", "#f39c12")
    crear_tarjeta_kpi(marco_kpis, "Eficiencia (Reqs)", f"{eficiencia:.1f}% Comp.", f"Atend: {total_atendidos} | Pend: {total_pendientes}", "#e74c3c")

    marco_graficos = ctk.CTkFrame(area_principal, fg_color="transparent")
    marco_graficos.pack(fill="both", expand=True, padx=10)
    bg_color, axes_color, text_color, grid_color = '#ffffff', '#f4f6f9', '#2c3e50', '#d5d8dc'
    fig, axs = plt.subplots(1, 2, figsize=(14, 4), facecolor=bg_color, dpi=90)
    fig.subplots_adjust(wspace=0.3)
    ax1, ax2 = axs[0], axs[1]

    def formatear_eje(ax, titulo):
        ax.set_title(titulo, fontsize=12, fontweight='bold', color='#154360', pad=15)
        ax.set_facecolor(axes_color)
        ax.tick_params(colors=text_color, labelsize=9)
        for spine in ['top', 'right', 'left', 'bottom']: ax.spines[spine].set_color('#bdc3c7')

    formatear_eje(ax1, "Avance Global por Clúster (%)")
    df_cluster = pd.DataFrame(reqs_validos_globales, columns=['pid', 'cat', 'est', 'ent', 'cluster'])
    if not df_cluster.empty:
        df_c = df_cluster.groupby('cluster').agg(total=('est','count'), comp=('est', lambda x: (x=='COMPLETADO').sum())).reset_index()
        clusters = [c if c else "S/C" for c in df_c['cluster']]
        porcentajes = (df_c['comp']/df_c['total']*100).fillna(0)
        bars1 = ax1.bar(clusters, porcentajes, color="#3498db", width=0.4)
        ax1.set_ylim(0, 110)
        ax1.yaxis.grid(True, linestyle='--', alpha=0.5, color=grid_color)
        ax1.set_axisbelow(True)
        for bar in bars1: ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height()+2, f"{bar.get_height():.1f}%", ha='center', color='#2c3e50', fontweight='bold', fontsize=9)
    else:
        ax1.text(0.5, 0.5, "Sin datos", ha='center', color=text_color)
        ax1.axis('off')

    formatear_eje(ax2, "Salud del Portafolio (Requisitos Activos)")
    if total_req_count > 0:
        en_proceso = estados_validos.count("RADICADO") + estados_validos.count("EN TRÁMITE") + estados_validos.count("EN SUBSANACIONES")
        alertas = estados_validos.count("VENCIDO") + estados_validos.count("REITERADO")
        valores, etiquetas, colores = [total_completados, en_proceso, alertas, total_pendientes], ['Completados', 'En Proceso', 'Alertas/Vencidos', 'Pendientes'], ['#2ecc71', '#3498db', '#e74c3c', '#7f8c8d']
        val_f = [v for v in valores if v > 0]
        col_f = [colores[i] for i, v in enumerate(valores) if v > 0]
        eti_f = [etiquetas[i] for i, v in enumerate(valores) if v > 0]
        wedges, texts, autotexts = ax2.pie(val_f, colors=col_f, labels=None, autopct=lambda p: '{:.1f}%'.format(p) if p > 5 else '', startangle=90, textprops={'color':"w", 'fontsize':9, 'weight':'bold'})
        ax2.add_artist(plt.Circle((0,0), 0.65, fc=axes_color)) 
        ax2.legend(wedges, eti_f, loc="center left", bbox_to_anchor=(0.9, 0.5), facecolor=axes_color, edgecolor=axes_color, labelcolor='#2c3e50')
    else:
        ax2.text(0.5, 0.5, "Sin datos", ha='center', color=text_color)
        ax2.axis('off')

    fig.tight_layout(pad=3.0)
    canvas = FigureCanvasTkAgg(fig, master=marco_graficos)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)

    con = sqlite3.connect("sistema_gd_v4.db")
    subsanaciones = con.execute("SELECT p.cluster, p.nombre, r.categoria, r.descripcion, r.entidad, r.observaciones, p.id FROM requisitos r JOIN proyectos p ON r.proyecto_id = p.id WHERE r.estado = 'EN SUBSANACIONES' AND p.estado_general != 'DESCARTADO' ORDER BY p.cluster ASC, p.id ASC").fetchall()
    con.close()

    marco_alertas_sub_bg = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_alertas_sub_bg.pack(fill="x", padx=10, pady=(15, 5))
    ctk.CTkLabel(marco_alertas_sub_bg, text="🚨 Alertas Críticas: Trámites en Subsanaciones", font=("Arial", 20, "bold"), text_color="#c0392b").pack(side="left", padx=20, pady=15)

    marco_subs_lista = ctk.CTkFrame(area_principal, fg_color="transparent")
    marco_subs_lista.pack(fill="x", padx=10, pady=(0, 20))

    if not subsanaciones:
        ctk.CTkLabel(marco_subs_lista, text="No hay trámites en estado de subsanación actualmente. ¡Buen trabajo!", text_color="#27ae60", font=("Arial", 14, "bold")).pack(pady=10)
    else:
        for sub in subsanaciones:
            c_nom = sub[0] if sub[0] and sub[0] != "N/A" else "Individual"
            tarj_sub = ctk.CTkFrame(marco_subs_lista, fg_color="#fdf2e9", corner_radius=8, border_color="#e67e22", border_width=1)
            tarj_sub.pack(fill="x", pady=5, padx=10)
            f_top = ctk.CTkFrame(tarj_sub, fg_color="transparent")
            f_top.pack(fill="x", padx=15, pady=(10, 2))
            ctk.CTkLabel(f_top, text=f"[{c_nom}] {sub[1]} - {sub[2]}", font=("Arial", 14, "bold"), text_color="#d35400").pack(side="left")
            ctk.CTkButton(f_top, text="Ir al Proyecto ➔", width=120, height=28, fg_color="#e67e22", hover_color="#d35400", text_color="white", font=("Arial", 12, "bold"), command=lambda pid=sub[6]: mostrar_detalles(pid)).pack(side="right")
            ctk.CTkLabel(tarj_sub, text=f"Requisito: {sub[3]} | Entidad: {sub[4]}", font=("Arial", 13), text_color="#2c3e50").pack(anchor="w", padx=15, pady=2)
            if sub[5]: ctk.CTkLabel(tarj_sub, text=f"Nota: {str(sub[5]).replace(chr(10), ' ')[:150]}...", font=("Arial", 12, "italic"), text_color="#7f8c8d").pack(anchor="w", padx=15, pady=(2, 10))

    marco_alertas_sup = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_alertas_sup.pack(fill="x", padx=10, pady=(15, 5))
    ctk.CTkLabel(marco_alertas_sup, text="⏱ Cronograma Global de Vencimientos OR (Requisitos 2.1 y 2.3)", font=("Arial", 20, "bold"), text_color="#154360").pack(side="left", padx=20, pady=15)

    marco_filtros = ctk.CTkFrame(area_principal, fg_color="transparent")
    marco_filtros.pack(fill="x", padx=15, pady=5)
    cl_list = sorted(list(set([p[6] if p[6] and p[6]!="N/A" else "Individual" for p in proyectos])))
    
    combo_cl_dash = ctk.CTkComboBox(marco_filtros, values=["TODOS LOS CLÚSTERES"] + cl_list, width=230, fg_color="#ffffff", text_color="#2c3e50", border_color="#bdc3c7")
    combo_cl_dash.pack(side="left", padx=10)
    combo_pr_dash = ctk.CTkComboBox(marco_filtros, values=["TODOS LOS PROYECTOS"], width=300, fg_color="#ffffff", text_color="#2c3e50", border_color="#bdc3c7")
    combo_pr_dash.pack(side="left", padx=10)

    marco_timeline = ctk.CTkFrame(area_principal, fg_color="transparent")
    marco_timeline.pack(fill="x", padx=10, pady=(10, 20))

    def render_timeline(cl_filtro, pr_filtro):
        for w in marco_timeline.winfo_children(): w.destroy()
        datos_timeline, hoy = [], datetime.date.today()
        
        for p in proyectos:
            p_id, _, _, _, _, _, cluster_raw, nombre_pr = p
            c_nom = cluster_raw if cluster_raw and cluster_raw != "N/A" else "Individual"
            if cl_filtro != "TODOS LOS CLÚSTERES" and c_nom != cl_filtro: continue
            if pr_filtro != "TODOS LOS PROYECTOS" and nombre_pr != pr_filtro: continue
            
            for req in [r for r in todos_reqs if r[0] == p_id and ("2.1" in r[4] or "2.3" in r[4])]:
                est, desc, f_fin, f_rad = req[2], req[4], req[5], req[6]
                dias_restantes, f_vence, pct = 999999, None, 0.0
                if est == "COMPLETADO" and f_fin:
                    try:
                        f_cierre = datetime.datetime.strptime(f_fin, "%d/%m/%Y").date()
                        f_vence = sumar_meses(f_cierre, 5)
                        dias_restantes = (f_vence - hoy).days
                        pct = min(max((hoy - f_cierre).days / (f_vence - f_cierre).days, 0.0), 1.0)
                    except: pass
                datos_timeline.append({'p_id': p_id, 'cluster': c_nom, 'proyecto': nombre_pr, 'desc': desc, 'est': est, 'f_rad': f_rad, 'f_fin': f_fin, 'dias_restantes': dias_restantes, 'f_vence': f_vence, 'pct': pct})
                
        datos_timeline.sort(key=lambda x: x['dias_restantes'])
        if not datos_timeline:
            ctk.CTkLabel(marco_timeline, text="No hay registros OR para los filtros seleccionados.", text_color="#2c3e50").pack(pady=10)
            return

        for item in datos_timeline:
            card = ctk.CTkFrame(marco_timeline, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
            card.pack(fill="x", pady=8, padx=10)
            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=15, pady=(10, 5))
            ctk.CTkLabel(header, text=f"[{item['cluster']}] {item['proyecto']} - {item['desc']}", font=("Arial", 15, "bold"), text_color="#154360").pack(side="left")
            ctk.CTkButton(header, text="Ir ➔", width=40, height=24, fg_color="#3498db", hover_color="#2980b9", text_color="white", font=("Arial", 11, "bold"), command=lambda pid=item['p_id']: mostrar_detalles(pid)).pack(side="right", padx=(10, 0))
            ctk.CTkLabel(header, text=f"Estado: {item['est']}", font=("Arial", 13, "bold"), text_color=ESTADOS_COLORES.get(item['est'], "gray")).pack(side="right")
            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(fill="x", padx=15, pady=(0, 10))

            if item['est'] == "COMPLETADO" and item['f_vence']:
                dr = item['dias_restantes']
                color_barra, txt_tiempo = ("#e74c3c", f"VENCIDO HACE {abs(dr)} DÍAS") if dr < 0 else ("#d35400", f"POR VENCER (Faltan {dr} días)") if dr <= 60 else ("#27ae60", f"A TIEMPO (Faltan {dr} días)")
                ctk.CTkLabel(body, text=f"Cierre: {item['f_fin']}", font=("Arial", 13), text_color="#2c3e50").pack(side="left")
                ctk.CTkLabel(body, text=f"Límite (5 Meses): {item['f_vence'].strftime('%d/%m/%Y')}", font=("Arial", 13), text_color="#2c3e50").pack(side="left", padx=25)
                ctk.CTkLabel(body, text=txt_tiempo, font=("Arial", 13, "bold"), text_color=color_barra).pack(side="right")
                barra = ctk.CTkProgressBar(card, height=14, progress_color=color_barra, fg_color="#ecf0f1")
                barra.pack(fill="x", padx=15, pady=(0, 15))
                barra.set(item['pct'])
            else:
                ctk.CTkLabel(body, text=f"Radicado: {item['f_rad']}" if item['f_rad'] else "Aún no se ha finalizado el requisito para iniciar el conteo de vigencia.", font=("Arial", 13), text_color="#7f8c8d").pack(side="left")

    def update_pr_dash(choice):
        noms = ["TODOS LOS PROYECTOS"] if choice == "TODOS LOS CLÚSTERES" else ["TODOS LOS PROYECTOS"] + [p[7] for p in proyectos if (p[6] if p[6] and p[6]!="N/A" else "Individual") == choice]
        combo_pr_dash.configure(values=noms); combo_pr_dash.set(noms[0]); render_timeline(choice, noms[0])

    combo_cl_dash.configure(command=update_pr_dash)
    combo_pr_dash.configure(command=lambda choice: render_timeline(combo_cl_dash.get(), choice))
    combo_cl_dash.set("TODOS LOS CLÚSTERES")
    update_pr_dash("TODOS LOS CLÚSTERES")


# ==========================================
# GESTOR DE USUARIOS Y PERFIL
# ==========================================
def mostrar_gestor_usuarios():
    limpiar_area_principal()
    render_cabecera(area_principal)
    marco_top = ctk.CTkFrame(area_principal, fg_color="#ffffff", corner_radius=10, border_color="#d5d8dc", border_width=1)
    marco_top.pack(fill="x", padx=10, pady=(0, 10))
    ctk.CTkLabel(marco_top, text="👥 GESTIÓN DE USUARIOS", font=("Arial", 22, "bold"), text_color="#8E44AD").pack(side="left", padx=20, pady=15)
    
    def popup_usuario(usr_data=None):
        pop = ctk.CTkToplevel(ventana)
        pop.title("Nuevo Usuario" if not usr_data else "Editar Usuario")
        pop.geometry("450x450")
        pop.grab_set()
        pop.configure(fg_color="#f4f6f9")
        
        ctk.CTkLabel(pop, text="Datos del Usuario", font=("Arial", 18, "bold"), text_color="#2c3e50").pack(pady=20)
        ctk.CTkLabel(pop, text="Nombre Completo:", text_color="#2c3e50", font=("Arial", 12, "bold")).pack(anchor="w", padx=40)
        e_nombre = ctk.CTkEntry(pop, width=370, fg_color="#ffffff", text_color="#2c3e50")
        e_nombre.pack(padx=40, pady=(0, 10))
        ctk.CTkLabel(pop, text="Usuario de Acceso:", text_color="#2c3e50", font=("Arial", 12, "bold")).pack(anchor="w", padx=40)
        e_usuario = ctk.CTkEntry(pop, width=370, fg_color="#ffffff", text_color="#2c3e50")
        e_usuario.pack(padx=40, pady=(0, 10))
        ctk.CTkLabel(pop, text="Contraseña:", text_color="#2c3e50", font=("Arial", 12, "bold")).pack(anchor="w", padx=40)
        e_pass = ctk.CTkEntry(pop, width=370, fg_color="#ffffff", text_color="#2c3e50", show="*")
        e_pass.pack(padx=40, pady=(0, 10))
        ctk.CTkLabel(pop, text="Rol del Sistema:", text_color="#2c3e50", font=("Arial", 12, "bold")).pack(anchor="w", padx=40)
        e_rol = ctk.CTkComboBox(pop, width=370, values=["Administrador", "Invitado"], fg_color="#ffffff", text_color="#2c3e50")
        e_rol.pack(padx=40, pady=(0, 15))
        
        if usr_data:
            e_nombre.insert(0, usr_data[3])
            e_usuario.insert(0, usr_data[1])
            e_pass.insert(0, usr_data[4])
            e_rol.set(usr_data[2])
        else: e_rol.set("Invitado")

        def guardar_usr():
            if not e_nombre.get() or not e_usuario.get() or not e_pass.get():
                messagebox.showwarning("Faltan Datos", "Todos los campos son obligatorios.")
                return
            con = sqlite3.connect("sistema_gd_v4.db")
            try:
                if usr_data: 
                    con.execute("UPDATE usuarios SET usuario=?, nombre=?, password=?, rol=? WHERE id=?", (e_usuario.get(), e_nombre.get(), e_pass.get(), e_rol.get(), usr_data[0]))
                else: 
                    con.execute("INSERT INTO usuarios (usuario, password, rol, nombre) VALUES (?, ?, ?, ?)", (e_usuario.get(), e_pass.get(), e_rol.get(), e_nombre.get()))
                con.commit()
                messagebox.showinfo("Éxito", "Usuario guardado correctamente.\nSi cambiaste tu propio usuario, los cambios se reflejarán en el próximo inicio de sesión.")
                pop.destroy()
                mostrar_gestor_usuarios()
            except sqlite3.IntegrityError: messagebox.showerror("Error", "Ese nombre de usuario ya existe en el sistema.")
            finally: con.close()

        ctk.CTkButton(pop, text="💾 Guardar Usuario", font=("Arial", 14, "bold"), fg_color="#27ae60", hover_color="#2ecc71", text_color="white", command=guardar_usr).pack(pady=10)

    ctk.CTkButton(marco_top, text="+ Nuevo Usuario", fg_color="#27ae60", hover_color="#2ecc71", text_color="white", font=("Arial", 14, "bold"), command=popup_usuario).pack(side="right", padx=20)
    marco_lista = ctk.CTkFrame(area_principal, fg_color="transparent")
    marco_lista.pack(fill="both", expand=True, pady=10, padx=10)
    
    con = sqlite3.connect("sistema_gd_v4.db")
    usuarios = con.execute("SELECT id, usuario, rol, nombre, password FROM usuarios ORDER BY id ASC").fetchall()
    con.close()
    
    def eliminar_usuario(uid):
        if uid == usuario_actual[0]:
            messagebox.showwarning("Atención", "No puedes eliminar tu propio usuario mientras estás en sesión.")
            return
        if messagebox.askyesno("Confirmar", "¿Eliminar este usuario de forma permanente?"):
            c = sqlite3.connect("sistema_gd_v4.db")
            c.execute("DELETE FROM usuarios WHERE id=?", (uid,))
            c.commit()
            c.close()
            mostrar_gestor_usuarios()

    for u in usuarios:
        tarjeta = ctk.CTkFrame(marco_lista, fg_color="#ffffff", corner_radius=8, border_color="#bdc3c7", border_width=1)
        tarjeta.pack(fill="x", pady=5)
        ctk.CTkLabel(tarjeta, text=f"Nombre: {u[3]}   |   Usuario: {u[1]}   |   Rol: {u[2]}", font=("Arial", 14, "bold"), text_color="#2c3e50").pack(side="left", padx=15, pady=15)
        ctk.CTkButton(tarjeta, text="🗑 Eliminar", width=80, fg_color="#e74c3c", hover_color="#c0392b", command=lambda uid=u[0]: eliminar_usuario(uid)).pack(side="right", padx=10)
        ctk.CTkButton(tarjeta, text="✏ Editar", width=80, fg_color="#f39c12", hover_color="#d35400", command=lambda usr=(u[0], u[1], u[2], u[3], u[4]): popup_usuario(usr)).pack(side="right", padx=5)

def mostrar_perfil():
    pop = ctk.CTkToplevel(ventana)
    pop.title("Mi Perfil")
    pop.geometry("450x450")
    pop.grab_set()
    pop.configure(fg_color="#f4f6f9")
    
    ctk.CTkLabel(pop, text="Editar Mis Datos", font=("Arial", 18, "bold"), text_color="#2c3e50").pack(pady=20)
    
    con = sqlite3.connect("sistema_gd_v4.db")
    u_data = con.execute("SELECT id, usuario, password, rol, nombre FROM usuarios WHERE id=?", (usuario_actual[0],)).fetchone()
    con.close()

    ctk.CTkLabel(pop, text="Nombre Completo:", text_color="#2c3e50", font=("Arial", 12, "bold")).pack(anchor="w", padx=40)
    e_nombre = ctk.CTkEntry(pop, width=370, fg_color="#ffffff", text_color="#2c3e50")
    e_nombre.pack(padx=40, pady=(0, 10))
    e_nombre.insert(0, u_data[4])
    
    ctk.CTkLabel(pop, text="Usuario de Acceso:", text_color="#2c3e50", font=("Arial", 12, "bold")).pack(anchor="w", padx=40)
    e_usuario = ctk.CTkEntry(pop, width=370, fg_color="#ffffff", text_color="#2c3e50")
    e_usuario.pack(padx=40, pady=(0, 10))
    e_usuario.insert(0, u_data[1])
    
    ctk.CTkLabel(pop, text="Contraseña:", text_color="#2c3e50", font=("Arial", 12, "bold")).pack(anchor="w", padx=40)
    e_pass = ctk.CTkEntry(pop, width=370, fg_color="#ffffff", text_color="#2c3e50", show="*")
    e_pass.pack(padx=40, pady=(0, 10))
    e_pass.insert(0, u_data[2])
    
    def guardar_perfil():
        if not e_nombre.get() or not e_usuario.get() or not e_pass.get():
            messagebox.showwarning("Faltan Datos", "Todos los campos son obligatorios.")
            return
        con = sqlite3.connect("sistema_gd_v4.db")
        try:
            con.execute("UPDATE usuarios SET usuario=?, nombre=?, password=? WHERE id=?", (e_usuario.get(), e_nombre.get(), e_pass.get(), usuario_actual[0]))
            con.commit()
            messagebox.showinfo("Éxito", "Perfil actualizado correctamente.\nLos cambios se reflejarán por completo en tu próximo inicio de sesión.")
            pop.destroy()
        except sqlite3.IntegrityError:
            messagebox.showerror("Error", "Ese nombre de usuario ya está en uso.")
        finally:
            con.close()
            
    ctk.CTkButton(pop, text="💾 Guardar Cambios", font=("Arial", 14, "bold"), fg_color="#27ae60", hover_color="#2ecc71", text_color="white", command=guardar_perfil).pack(pady=20)


# ==========================================
# 8. FORMULARIO DE CREACIÓN MEJORADO
# ==========================================
def mostrar_formulario():
    limpiar_area_principal()
    render_cabecera(area_principal)
    container = ctk.CTkFrame(area_principal, fg_color="transparent")
    container.pack(expand=True, fill="both")
    form_frame = ctk.CTkFrame(container, fg_color="#ffffff", corner_radius=15, border_width=1, border_color="#d5d8dc")
    form_frame.pack(pady=30, anchor="center")
    
    ctk.CTkLabel(form_frame, text="Añadir Nuevo Proyecto al Portafolio", font=("Arial", 26, "bold"), text_color="#154360").grid(row=1, column=0, columnspan=2, pady=(30, 30))
    estilo_caja, est_label = {"fg_color": "#ffffff", "border_color": "#bdc3c7", "text_color": "#2c3e50", "height": 35}, {"text_color": "#2c3e50", "font": ("Arial", 12, "bold")}

    con = sqlite3.connect("sistema_gd_v4.db")
    lista_clusters = ["N/A (Proyecto Individual)"] + [c[0] for c in con.execute("SELECT nombre_cluster FROM clusteres ORDER BY nombre_cluster ASC").fetchall()]
    con.close()

    ctk.CTkLabel(form_frame, text="Clúster asignado:", **est_label).grid(row=2, column=0, padx=(40, 20), pady=12, sticky="e")
    ent_cluster = ctk.CTkComboBox(form_frame, width=400, values=lista_clusters, **estilo_caja)
    ent_cluster.grid(row=2, column=1, padx=(0, 40), pady=12, sticky="w")
    ent_cluster.set("N/A (Proyecto Individual)")

    ctk.CTkLabel(form_frame, text="Nombre del Proyecto:", **est_label).grid(row=3, column=0, padx=(40, 20), pady=12, sticky="e")
    ent_nombre = ctk.CTkEntry(form_frame, width=400, **estilo_caja)
    ent_nombre.grid(row=3, column=1, padx=(0, 40), pady=12, sticky="w")

    def actualizar_municipios(choice):
        ent_municipio.configure(values=sorted(MUNICIPIOS[choice]) if choice in MUNICIPIOS else ["Escribe aquí..."])
        ent_municipio.set(sorted(MUNICIPIOS[choice])[0] if choice in MUNICIPIOS else "")

    ctk.CTkLabel(form_frame, text="Departamento:", **est_label).grid(row=4, column=0, padx=(40, 20), pady=12, sticky="e")
    ent_depto = ctk.CTkComboBox(form_frame, width=400, values=DEPARTAMENTOS, command=actualizar_municipios, **estilo_caja)
    ent_depto.set("Seleccionar...")
    ent_depto.grid(row=4, column=1, padx=(0, 40), pady=12, sticky="w")

    ctk.CTkLabel(form_frame, text="Municipio:", **est_label).grid(row=5, column=0, padx=(40, 20), pady=12, sticky="e")
    ent_municipio = ctk.CTkComboBox(form_frame, width=400, values=["Selecciona departamento"], **estilo_caja)
    ent_municipio.grid(row=5, column=1, padx=(0, 40), pady=12, sticky="w")

    ctk.CTkLabel(form_frame, text="Dirección del predio:", **est_label).grid(row=6, column=0, padx=(40, 20), pady=12, sticky="e")
    ent_dir = ctk.CTkEntry(form_frame, width=400, **estilo_caja)
    ent_dir.grid(row=6, column=1, padx=(0, 40), pady=12, sticky="w")

    ctk.CTkLabel(form_frame, text="Capacidad (kW):", **est_label).grid(row=7, column=0, padx=(40, 20), pady=12, sticky="e")
    ent_capacidad = ctk.CTkEntry(form_frame, width=400, placeholder_text="Ej: 5000", **estilo_caja)
    ent_capacidad.grid(row=7, column=1, padx=(0, 40), pady=12, sticky="w")

    ctk.CTkLabel(form_frame, text="Área (Hectáreas):", **est_label).grid(row=8, column=0, padx=(40, 20), pady=12, sticky="e")
    ent_area = ctk.CTkEntry(form_frame, width=400, placeholder_text="Ej: 12.5", **estilo_caja)
    ent_area.grid(row=8, column=1, padx=(0, 40), pady=12, sticky="w")

    ctk.CTkLabel(form_frame, text="Latitud / Longitud:", **est_label).grid(row=9, column=0, padx=(40, 20), pady=12, sticky="e")
    coord_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
    coord_frame.grid(row=9, column=1, padx=(0, 40), pady=12, sticky="w")
    ent_lat = ctk.CTkEntry(coord_frame, width=105, placeholder_text="Latitud", **estilo_caja)
    ent_lat.pack(side="left", padx=(0, 10))
    ent_lon = ctk.CTkEntry(coord_frame, width=105, placeholder_text="Longitud", **estilo_caja)
    ent_lon.pack(side="left", padx=(0, 10))
    ctk.CTkButton(coord_frame, text="📍 Mapa del predio", width=145, command=lambda: abrir_mapa_predio(ent_lat, ent_lon, ent_municipio.get(), ent_depto.get())).pack(side="left")

    def guardar():
        if ent_nombre.get() == "":
            messagebox.showerror("Error", "El Nombre del proyecto es obligatorio.")
            return
        try: 
            cap = float(ent_capacidad.get().replace(',', '.') if ent_capacidad.get() else 0.0)
            ar = float(ent_area.get().replace(',', '.') if ent_area.get() else 0.0)
        except: 
            messagebox.showerror("Error", "La capacidad y el área deben ser números válidos.")
            return

        c_sel = ent_cluster.get()
        cluster_final = "N/A" if "Individual" in c_sel else c_sel.upper()

        con = sqlite3.connect("sistema_gd_v4.db")
        cur = con.cursor()
        cur.execute('''INSERT INTO proyectos (cluster, nombre, municipio, departamento, direccion, latitud, longitud, area, capacidad_kw, fecha_creacion) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (cluster_final, ent_nombre.get(), ent_municipio.get(), ent_depto.get(), ent_dir.get(), ent_lat.get(), ent_lon.get(), ar, cap, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        p_id = cur.lastrowid
        for req in REQUISITOS_BASE:
            cur.execute("INSERT INTO requisitos (proyecto_id, categoria, descripcion, entidad, estado, observaciones) VALUES (?, ?, ?, ?, 'PENDIENTE', '')", (p_id, req[0], req[1], req[2]))
        con.commit()
        con.close()
        mostrar_lista()

    ctk.CTkButton(form_frame, text="✅ Guardar Proyecto y Generar Matriz", font=("Arial", 16, "bold"), text_color="white", fg_color="#27ae60", hover_color="#2ecc71", height=45, command=guardar).grid(row=10, column=0, columnspan=2, pady=(20, 40), padx=40, sticky="ew")

# ==========================================
# 9. EXPORTACIÓN EXCEL AVANZADA (CON HILOS)
# ==========================================
def parsear_fecha_gantt(valor):
    if isinstance(valor, datetime.datetime):
        return valor.date()
    if isinstance(valor, datetime.date):
        return valor
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "none", "nat"}:
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None

def alerta_semanal_gantt(estado, fecha_limite, fecha_cierre, hoy):
    if str(estado or "").strip().upper() == "COMPLETADO" or fecha_cierre:
        return "COMPLETADO", "70AD47"
    if not fecha_limite:
        return "SIN FECHA LÍMITE", "A5A5A5"
    dias_restantes = (fecha_limite - hoy).days
    if dias_restantes < 0:
        semanas_vencidas = (abs(dias_restantes) + 6) // 7
        return f"VENCIDO · {semanas_vencidas} sem.", "C00000"
    inicio_semana = hoy - datetime.timedelta(days=hoy.weekday())
    fin_semana = inicio_semana + datetime.timedelta(days=6)
    if fecha_limite <= fin_semana:
        return "VENCE ESTA SEMANA", "ED7D31"
    if fecha_limite <= fin_semana + datetime.timedelta(days=7):
        return "VENCE PRÓXIMA SEMANA", "FFC000"
    semanas_restantes = (dias_restantes + 6) // 7
    return f"A TIEMPO · {semanas_restantes} sem.", "70AD47"

def generar_gantt_xlsx(registros, ruta, tipo, nombre, hoy=None):
    from openpyxl import Workbook

    hoy = hoy or datetime.date.today()
    fechas = [hoy]
    for registro in registros:
        fechas.extend(parsear_fecha_gantt(valor) for valor in registro[4:7])
    fechas = [fecha for fecha in fechas if fecha]
    primera_semana = min(fechas) - datetime.timedelta(days=min(fechas).weekday())
    ultima_fecha = max(fechas)
    ultima_semana = ultima_fecha - datetime.timedelta(days=ultima_fecha.weekday())
    semanas = []
    semana_actual = primera_semana
    while semana_actual <= ultima_semana:
        semanas.append(semana_actual)
        semana_actual += datetime.timedelta(days=7)

    color_estado = {
        "COMPLETADO": "70AD47",
        "VENCIDO": "C00000",
        "EN TRÁMITE": "5B9BD5",
        "RADICADO": "4472C4",
        "EN SUBSANACIONES": "ED7D31",
        "REITERADO": "FFC000",
        "PENDIENTE": "A5A5A5",
    }
    borde = Border(left=Side(style="thin", color="D9E1F2"), right=Side(style="thin", color="D9E1F2"), top=Side(style="thin", color="D9E1F2"), bottom=Side(style="thin", color="D9E1F2"))
    workbook = Workbook()
    hoja = workbook.active
    hoja.title = "Gantt"
    total_columnas = 9 + len(semanas)
    hoja.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_columnas)
    hoja.cell(1, 1, f"DIAGRAMA DE GANTT · {tipo.upper()}: {nombre}")
    hoja.cell(1, 1).font = Font(bold=True, size=16, color="FFFFFF")
    hoja.cell(1, 1).fill = PatternFill("solid", fgColor="203764")
    hoja.cell(1, 1).alignment = Alignment(vertical="center")
    hoja.row_dimensions[1].height = 30
    hoja.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_columnas)
    hoja.cell(2, 1, f"Generado el {hoy.strftime('%d/%m/%Y')}. Las alertas reflejan el estado semanal a la fecha de exportación.")
    hoja.cell(2, 1).font = Font(italic=True, color="404040")
    hoja.cell(2, 1).alignment = Alignment(wrap_text=True)

    encabezados = ["Proyecto", "Clúster", "Módulo", "Requisito", "Estado", "Inicio", "Fecha límite", "Cierre real", "Alerta semanal"]
    inicio_semanas = len(encabezados) + 1
    nombres_meses = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")
    hoja.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(encabezados))
    hoja.cell(3, 1, "DATOS DEL REQUISITO")
    hoja.cell(3, 1).font = Font(bold=True, color="FFFFFF")
    hoja.cell(3, 1).fill = PatternFill("solid", fgColor="203764")
    hoja.cell(3, 1).alignment = Alignment(horizontal="center", vertical="center")
    hoja.cell(3, 1).border = borde
    for columna, encabezado in enumerate(encabezados, start=1):
        celda = hoja.cell(4, columna, encabezado)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="203764")
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celda.border = borde

    inicio_grupo = 0
    mes_anterior = None
    for indice, lunes in enumerate(semanas):
        jueves = lunes + datetime.timedelta(days=3)
        clave_mes = (jueves.year, jueves.month)
        if mes_anterior is not None and clave_mes != mes_anterior:
            columna_inicio = inicio_semanas + inicio_grupo
            columna_fin = inicio_semanas + indice - 1
            hoja.merge_cells(start_row=3, start_column=columna_inicio, end_row=3, end_column=columna_fin)
            celda_mes = hoja.cell(3, columna_inicio, f"{nombres_meses[mes_anterior[1] - 1]} {mes_anterior[0]}")
            celda_mes.font = Font(bold=True, color="FFFFFF")
            celda_mes.fill = PatternFill("solid", fgColor="365F91")
            celda_mes.alignment = Alignment(horizontal="center", vertical="center")
            celda_mes.border = borde
            inicio_grupo = indice
        mes_anterior = clave_mes
    columna_inicio = inicio_semanas + inicio_grupo
    columna_fin = inicio_semanas + len(semanas) - 1
    hoja.merge_cells(start_row=3, start_column=columna_inicio, end_row=3, end_column=columna_fin)
    celda_mes = hoja.cell(3, columna_inicio, f"{nombres_meses[mes_anterior[1] - 1]} {mes_anterior[0]}")
    celda_mes.font = Font(bold=True, color="FFFFFF")
    celda_mes.fill = PatternFill("solid", fgColor="365F91")
    celda_mes.alignment = Alignment(horizontal="center", vertical="center")
    celda_mes.border = borde

    for indice, lunes in enumerate(semanas):
        semana_iso = lunes.isocalendar()
        celda = hoja.cell(4, inicio_semanas + indice, f"S{semana_iso.week:02d}\n{semana_iso.year}")
        celda.font = Font(bold=True, color="FFFFFF", size=9)
        celda.fill = PatternFill("solid", fgColor="203764")
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celda.border = borde
        celda.comment = __import__("openpyxl").comments.Comment(f"Semana del {lunes.strftime('%d/%m/%Y')}", "Sistema GD")
    hoja.row_dimensions[3].height = 22
    hoja.row_dimensions[4].height = 32

    for numero_fila, registro in enumerate(registros, start=5):
        proyecto, cluster, modulo, requisito, inicio_txt, limite_txt, cierre_txt, estado = registro
        inicio = parsear_fecha_gantt(inicio_txt)
        limite = parsear_fecha_gantt(limite_txt)
        cierre = parsear_fecha_gantt(cierre_txt)
        estado_normalizado = str(estado or "PENDIENTE").strip().upper()
        alerta, color_alerta = alerta_semanal_gantt(estado_normalizado, limite, cierre, hoy)
        valores = [proyecto, cluster or "Sin clúster", modulo, requisito, estado_normalizado, inicio, limite, cierre, alerta]
        for columna, valor in enumerate(valores, start=1):
            celda = hoja.cell(numero_fila, columna, valor)
            celda.border = borde
            celda.alignment = Alignment(vertical="center", wrap_text=True)
        for columna in (6, 7, 8):
            hoja.cell(numero_fila, columna).number_format = "dd/mm/yyyy"
        color_estado_fila = color_estado.get(estado_normalizado, "A5A5A5")
        celda_estado = hoja.cell(numero_fila, 5)
        celda_estado.fill = PatternFill("solid", fgColor=color_estado_fila)
        celda_estado.font = Font(color="FFFFFF", bold=True)
        celda_alerta = hoja.cell(numero_fila, 9)
        celda_alerta.fill = PatternFill("solid", fgColor=color_alerta)
        celda_alerta.font = Font(color="FFFFFF" if color_alerta in {"C00000", "70AD47", "A5A5A5"} else "000000", bold=True)
        celda_alerta.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        fecha_inicio_barra = inicio or limite or cierre
        fecha_fin_barra = cierre or limite or fecha_inicio_barra
        if fecha_inicio_barra and fecha_fin_barra:
            if fecha_fin_barra < fecha_inicio_barra:
                fecha_fin_barra = fecha_inicio_barra
            for indice, lunes in enumerate(semanas):
                domingo = lunes + datetime.timedelta(days=6)
                if lunes <= fecha_fin_barra and domingo >= fecha_inicio_barra:
                    celda = hoja.cell(numero_fila, inicio_semanas + indice)
                    celda.fill = PatternFill("solid", fgColor=color_estado_fila)
                    celda.border = borde
                    if fecha_inicio_barra == fecha_fin_barra and lunes <= fecha_inicio_barra <= domingo:
                        celda.value = "◆"
                        celda.font = Font(color="FFFFFF", bold=True)
                        celda.alignment = Alignment(horizontal="center", vertical="center")
        for columna in range(inicio_semanas, total_columnas + 1):
            hoja.cell(numero_fila, columna).border = borde
        hoja.row_dimensions[numero_fila].height = 30

    fila_leyenda = max(4, hoja.max_row + 2)
    hoja.cell(fila_leyenda, 1, "Leyenda de barras")
    hoja.cell(fila_leyenda, 1).font = Font(bold=True)
    for indice, (estado, color) in enumerate(color_estado.items(), start=2):
        celda = hoja.cell(fila_leyenda, indice, estado)
        celda.fill = PatternFill("solid", fgColor=color)
        celda.font = Font(color="FFFFFF", bold=True)
        celda.alignment = Alignment(horizontal="center")
    hoja.freeze_panes = "J5"
    hoja.auto_filter.ref = f"A4:{get_column_letter(total_columnas)}{max(4, hoja.max_row - 2)}"
    hoja.sheet_view.showGridLines = False
    hoja.page_setup.orientation = "landscape"
    hoja.page_setup.fitToWidth = 1
    hoja.page_setup.fitToHeight = 0
    hoja.sheet_properties.pageSetUpPr.fitToPage = True
    hoja.print_title_rows = "1:4"
    for columna, ancho in {"A": 28, "B": 24, "C": 27, "D": 52, "E": 22, "F": 14, "G": 14, "H": 14, "I": 26}.items():
        hoja.column_dimensions[columna].width = ancho
    for columna in range(inicio_semanas, total_columnas + 1):
        hoja.column_dimensions[get_column_letter(columna)].width = 11
    workbook.save(ruta)

def exportar_gantt_excel():
    con = sqlite3.connect("sistema_gd_v4.db")
    proyectos = con.execute("SELECT id, nombre, COALESCE(NULLIF(cluster, ''), 'Sin clúster') FROM proyectos ORDER BY cluster, nombre").fetchall()
    clusters = [fila[0] for fila in con.execute("SELECT DISTINCT cluster FROM proyectos WHERE cluster IS NOT NULL AND TRIM(cluster) != '' ORDER BY cluster").fetchall()]
    con.close()
    if not proyectos:
        messagebox.showwarning("Sin proyectos", "No hay proyectos para generar diagramas de Gantt.")
        return

    opciones_proyecto = [f"{proyecto_id} · {nombre} · {cluster}" for proyecto_id, nombre, cluster in proyectos]
    pop = ctk.CTkToplevel(ventana)
    pop.title("Exportar diagrama de Gantt")
    pop.geometry("540x300")
    pop.resizable(False, False)
    pop.transient(ventana)
    pop.grab_set()
    ctk.CTkLabel(pop, text="Exportar diagrama de Gantt", font=("Arial", 20, "bold")).pack(pady=(22, 10))
    tipo_var = ctk.StringVar(value="Proyecto")
    opciones = opciones_proyecto if proyectos else clusters
    seleccion_var = ctk.StringVar(value=opciones[0] if opciones else "")
    selector_tipo = ctk.CTkSegmentedButton(pop, values=["Proyecto", "Clúster"], variable=tipo_var)
    selector_tipo.pack(pady=8)
    selector = ctk.CTkOptionMenu(pop, values=opciones, variable=seleccion_var, width=480)
    selector.pack(pady=10)
    ctk.CTkLabel(pop, text="El archivo incluirá requisitos, fechas, barras semanales y alertas.", wraplength=470).pack(pady=5)

    def actualizar_opciones(tipo):
        valores = opciones_proyecto if tipo == "Proyecto" else clusters
        selector.configure(values=valores or ["No hay clústeres"])
        seleccion_var.set(valores[0] if valores else "No hay clústeres")

    selector_tipo.configure(command=actualizar_opciones)

    def iniciar_exportacion():
        tipo = tipo_var.get()
        seleccion = seleccion_var.get()
        if tipo == "Clúster" and not clusters:
            messagebox.showwarning("Sin clústeres", "No hay clústeres para exportar.", parent=pop)
            return
        nombre = seleccion.split(" · ", 2)[1] if tipo == "Proyecto" else seleccion
        nombre_archivo = "".join(caracter if caracter.isalnum() or caracter in "-_ " else "_" for caracter in nombre).strip()
        ruta = filedialog.asksaveasfilename(
            parent=pop,
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"Gantt_{tipo}_{nombre_archivo}.xlsx",
            title="Guardar diagrama de Gantt",
        )
        if not ruta:
            return
        pop.destroy()
        pop_carga = ctk.CTkToplevel(ventana)
        pop_carga.title("Generando Gantt...")
        pop_carga.geometry("360x140")
        pop_carga.grab_set()
        ctk.CTkLabel(pop_carga, text="Generando diagrama de Gantt...", font=("Arial", 15, "bold")).pack(pady=(35, 10))
        ctk.CTkLabel(pop_carga, text="Preparando cronograma semanal y alertas").pack()

        def tarea_gantt():
            try:
                conexion = sqlite3.connect("sistema_gd_v4.db")
                consulta = """SELECT p.nombre, p.cluster, r.categoria, r.descripcion,
                    r.fecha_radicacion, r.fecha_limite, r.fecha_final, r.estado
                    FROM proyectos p JOIN requisitos r ON r.proyecto_id=p.id"""
                if tipo == "Proyecto":
                    proyecto_id = int(seleccion.split(" · ", 1)[0])
                    registros = conexion.execute(consulta + " WHERE p.id=? ORDER BY r.categoria, r.descripcion", (proyecto_id,)).fetchall()
                else:
                    registros = conexion.execute(consulta + " WHERE p.cluster=? ORDER BY p.nombre, r.categoria, r.descripcion", (seleccion,)).fetchall()
                conexion.close()
                if not registros:
                    ventana.after(0, lambda: messagebox.showwarning("Sin requisitos", "La selección no tiene requisitos para graficar."))
                    return
                generar_gantt_xlsx(registros, ruta, tipo, nombre)
                ventana.after(0, lambda: messagebox.showinfo("Gantt generado", f"Diagrama de Gantt guardado en:\n{ruta}"))
            except Exception as error:
                ventana.after(0, lambda error=error: messagebox.showerror("Error de exportación", f"No se pudo generar el Gantt.\n{error}"))
            finally:
                ventana.after(0, pop_carga.destroy)

        threading.Thread(target=tarea_gantt, daemon=True).start()

    botones = ctk.CTkFrame(pop, fg_color="transparent")
    botones.pack(pady=15)
    ctk.CTkButton(botones, text="Exportar XLSX", command=iniciar_exportacion, width=150).pack(side="left", padx=6)
    ctk.CTkButton(botones, text="Cancelar", command=pop.destroy, width=130, fg_color="#7f8c8d", hover_color="#626f70").pack(side="left", padx=6)

def exportar_excel():
    ruta = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")], title="Guardar Informe Ejecutivo Excel")
    if not ruta: return

    pop_carga = ctk.CTkToplevel(ventana)
    pop_carga.title("Exportando...")
    pop_carga.geometry("350x150")
    pop_carga.grab_set()
    ctk.CTkLabel(pop_carga, text="⏳ Generando Excel...", font=("Arial", 16, "bold"), text_color="#2c3e50").pack(pady=(40, 10))
    ctk.CTkLabel(pop_carga, text="Procesando datos, por favor espera...", font=("Arial", 12)).pack()

    def tarea_excel():
        try:
            con = sqlite3.connect("sistema_gd_v4.db")
            df_proy = pd.read_sql_query("SELECT id as proyecto_id, cluster as Clúster, nombre as Proyecto, departamento as Departamento, municipio as Municipio, direccion as Dirección, radicado as Num_Solicitud, cod_validacion as Codigo_Val, circuito as Circuito, coord_conexion as Coordenadas, capacidad_kw as Capacidad_kW, estado_general as Estado_Global, req_servidumbre, req_contrato FROM proyectos ORDER BY cluster ASC, id ASC", con)
            df_req = pd.read_sql_query("SELECT proyecto_id, categoria as Módulo, descripcion as Requisito, entidad as Entidad, estado as Estado, fecha_limite as Límite, fecha_final as Cierre, observaciones as Observaciones FROM requisitos", con)
            df_or = pd.read_sql_query("SELECT cluster as Clúster, nombre as Proyecto, direccion as Predio, municipio as Municipio, departamento as Departamento, radicado as Num_Solicitud, circuito as Circuito, coord_conexion as Coordenadas FROM proyectos ORDER BY cluster ASC, id ASC", con)
            con.close()

            if df_proy.empty or df_req.empty:
                ventana.after(0, lambda: messagebox.showwarning("Vacío", "No hay datos suficientes para exportar."))
                return

            def calc_estado_vencimiento(fecha_cierre_str):
                if not fecha_cierre_str or pd.isna(fecha_cierre_str): return "PENDIENTE", "N/A"
                try:
                    f = datetime.datetime.strptime(fecha_cierre_str, "%d/%m/%Y").date()
                    vence = sumar_meses(f, 5)
                    hoy = datetime.date.today()
                    dias = (vence - hoy).days
                    if dias < 0: est = "VENCIDO"
                    elif dias <= 60: est = "POR VENCER"
                    else: est = "A TIEMPO"
                    return est, vence.strftime("%d/%m/%Y")
                except: 
                    return "PENDIENTE", "N/A"

            df_23 = df_req[df_req['Requisito'].str.startswith('2.3')][['proyecto_id', 'Cierre']].rename(columns={'Cierre': 'Cierre 2.3'})
            df_21 = df_req[df_req['Requisito'].str.startswith('2.1')][['proyecto_id', 'Cierre']].rename(columns={'Cierre': 'Cierre 2.1'})
            
            df_or_full = df_proy[['proyecto_id', 'Clúster', 'Proyecto', 'Municipio', 'Departamento', 'Dirección', 'Num_Solicitud', 'Codigo_Val', 'Circuito', 'Coordenadas']].copy()
            df_or_full = df_or_full.merge(df_23, on='proyecto_id', how='left').merge(df_21, on='proyecto_id', how='left')
            
            df_or_full[['Estado ECS', 'Vencimiento ECS']] = df_or_full['Cierre 2.3'].apply(lambda x: pd.Series(calc_estado_vencimiento(x)))
            df_or_full[['Estado Aprobación OR', 'Vencimiento Aprobación OR']] = df_or_full['Cierre 2.1'].apply(lambda x: pd.Series(calc_estado_vencimiento(x)))
            
            df_or_full['Num_Solicitud'] = df_or_full['Num_Solicitud'].replace('', 'Sin Radicar').fillna('Sin Radicar')
            
            df_or_full = df_or_full[['Clúster', 'Proyecto', 'Municipio', 'Departamento', 'Dirección', 'Num_Solicitud', 'Codigo_Val', 'Circuito', 'Coordenadas', 'Estado ECS', 'Vencimiento ECS', 'Estado Aprobación OR', 'Vencimiento Aprobación OR']]
            
            df_merge = pd.merge(df_req, df_proy[['proyecto_id', 'req_servidumbre', 'req_contrato']], on='proyecto_id')
            
            def req_valido(row):
                if row['Módulo'] in ['Ingeniería Básica', 'Análisis Técnico']: return False
                if row['Módulo'] == 'Servidumbre' and not row['req_servidumbre']: return False
                if row['Módulo'] == 'Modelo de Contrato' and not row['req_contrato']: return False
                return True

            df_validos = df_merge[df_merge.apply(req_valido, axis=1)].copy()
            df_validos['is_comp'] = df_validos['Estado'].apply(lambda x: 1 if x == 'COMPLETADO' else 0)
            df_validos['is_pend'] = df_validos['Estado'].apply(lambda x: 1 if x == 'PENDIENTE' else 0)
            df_validos['is_atend'] = df_validos['Estado'].apply(lambda x: 1 if x not in ['COMPLETADO', 'PENDIENTE'] else 0)

            resumen_reqs = df_validos.groupby('proyecto_id').agg(Req_Completados=('is_comp', 'sum'), Req_Atendidos=('is_atend', 'sum'), Req_Pendientes=('is_pend', 'sum'), Req_Total=('Requisito', 'count')).reset_index()
            resumen_reqs['Avance (%)'] = (resumen_reqs['Req_Completados'] / resumen_reqs['Req_Total']).fillna(0)

            df_visible = df_merge[df_merge.apply(lambda r: not (r['Módulo'] == 'Servidumbre' and not r['req_servidumbre']) and not (r['Módulo'] == 'Modelo de Contrato' and not r['req_contrato']), axis=1)].copy()
            df_visible['completado'] = df_visible['Estado'].apply(lambda x: 1 if x == 'COMPLETADO' else 0)
            df_agrupado = df_visible.groupby(['proyecto_id', 'Módulo']).agg(t=('Requisito','count'), c=('completado','sum')).reset_index()
            
            df_agrupado['Avn'] = (df_agrupado['c'] / df_agrupado['t']).fillna(0)
            df_pivot = df_agrupado.pivot(index='proyecto_id', columns='Módulo', values='Avn').reset_index()
            
            orden_oficial = ['Trámites de Terreno', 'Trámites OR', 'Servidumbre', 'Modelo de Contrato', 'Análisis Técnico', 'Ingeniería Básica', 'Antecedentes']
            cols_existentes = [c for c in orden_oficial if c in df_pivot.columns]
            df_pivot = df_pivot[['proyecto_id'] + cols_existentes]

            df_proy_final = pd.merge(df_proy.drop(columns=['req_servidumbre', 'req_contrato', 'Dirección', 'Num_Solicitud', 'Codigo_Val', 'Circuito', 'Coordenadas']), resumen_reqs, on='proyecto_id', how='left')
            df_matriz = pd.merge(df_proy_final, df_pivot, on='proyecto_id', how='left').drop(columns=['proyecto_id'])

            df_chequeo = pd.merge(df_proy[['proyecto_id', 'Clúster', 'Proyecto', 'Capacidad_kW']], df_req, on='proyecto_id').drop(columns=['proyecto_id'])

            def limpiar_fechas(row):
                lim = row['Límite'] if pd.notna(row['Límite']) else ""
                cie = row['Cierre'] if pd.notna(row['Cierre']) else ""
                if cie and str(cie).strip() != "": row['Límite'] = "-"
                elif lim and str(lim).strip() != "": row['Cierre'] = "-"
                return row
                
            df_chequeo = df_chequeo.apply(limpiar_fechas, axis=1)

            with pd.ExcelWriter(ruta, engine='openpyxl') as writer:
                df_chequeo.to_excel(writer, sheet_name='Lista de Chequeo', index=False)
                df_matriz.to_excel(writer, sheet_name='Matriz Seguimiento GD', index=False)
                df_or_full.to_excel(writer, sheet_name='Datos OR', index=False)
                
                workbook = writer.book
                colores_estado = {
                    "PENDIENTE": "D9D9D9", "RADICADO": "9BC2E6", "EN TRÁMITE": "F4B084", 
                    "EN SUBSANACIONES": "C65911", "REITERADO": "FFD966", "COMPLETADO": "A9D08E", 
                    "VENCIDO": "FF9999", "ACTIVO": "A9D08E", "PAUSADO": "FFD966", 
                    "DESCARTADO": "FF9999", "A TIEMPO": "A9D08E", "POR VENCER": "F4B084"
                }
                borde_delgado = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

                regla_escala_colores = ColorScaleRule(start_type='num', start_value=0, start_color='F8696B', mid_type='num', mid_value=0.5, mid_color='FFEB84', end_type='num', end_value=1, end_color='63BE7B')

                for sheet_name in workbook.sheetnames:
                    ws = workbook[sheet_name]
                    ws.freeze_panes = 'A2' 
                    ws.auto_filter.ref = ws.dimensions 
                    
                    for col in range(1, ws.max_column + 1):
                        celda_cabecera = ws.cell(row=1, column=col)
                        celda_cabecera.font = Font(bold=True, color="FFFFFF")
                        celda_cabecera.fill = PatternFill(start_color="203764", end_color="203764", fill_type="solid") 
                        celda_cabecera.alignment = Alignment(horizontal="center", vertical="center")
                        celda_cabecera.border = borde_delgado
                        ws.column_dimensions[get_column_letter(col)].width = 20 if sheet_name == 'Matriz Seguimiento GD' else 25

                    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
                        for cell in row:
                            cell.border = borde_delgado
                            cell.alignment = Alignment(vertical="center", wrap_text=True)
                            if str(cell.value) in colores_estado:
                                color_hex = colores_estado[str(cell.value)]
                                cell.fill = PatternFill(start_color=color_hex, end_color=color_hex, fill_type="solid")
                                cell.alignment = Alignment(horizontal="center", vertical="center")
                                if str(cell.value) in ["VENCIDO", "EN SUBSANACIONES"]: 
                                    cell.font = Font(bold=True, color="7F0000") 
                    
                    if sheet_name == 'Lista de Chequeo':
                        ws.column_dimensions['D'].width = 45 
                        ws.column_dimensions['I'].width = 50 
                    elif sheet_name == 'Datos OR':
                        ws.column_dimensions['B'].width = 30 
                        ws.column_dimensions['E'].width = 30 
                        ws.column_dimensions['F'].width = 20 
                        ws.column_dimensions['I'].width = 30 
                    elif sheet_name == 'Matriz Seguimiento GD':
                        for col in range(1, ws.max_column + 1):
                            cabecera_val = ws.cell(row=1, column=col).value
                            if cabecera_val == 'Avance (%)' or cabecera_val in orden_oficial:
                                letra = get_column_letter(col)
                                ws.conditional_formatting.add(f"{letra}2:{letra}{ws.max_row}", regla_escala_colores)
                                for r_idx in range(2, ws.max_row + 1):
                                    cell = ws.cell(row=r_idx, column=col)
                                    if isinstance(cell.value, (int, float)):
                                        cell.number_format = '0.0%'

            ventana.after(0, lambda: messagebox.showinfo("Éxito", f"Informe Ejecutivo generado exitosamente en:\n{ruta}"))

        except Exception as e:
            ventana.after(0, lambda e=e: messagebox.showerror("Error", f"Problema al exportar Excel.\nDetalle: {str(e)}"))
        finally:
            ventana.after(0, pop_carga.destroy)

    threading.Thread(target=tarea_excel, daemon=True).start()


# ==========================================
# 10. EXPORTACIÓN PDF GERENCIAL AVANZADA Y SELECTIVA
# ==========================================
NOMBRE_PLANTILLA_PDF = "COM-FT-15 V1 INFORME DE GESTION COMERCIAL.docx"

def extraer_logo_plantilla_pdf():
    import zipfile
    from xml.etree import ElementTree

    rutas_plantilla = [
        resource_path(NOMBRE_PLANTILLA_PDF),
        resource_path(os.path.join("dist", NOMBRE_PLANTILLA_PDF)),
    ]
    for ruta_plantilla in rutas_plantilla:
        if not os.path.exists(ruta_plantilla):
            continue
        try:
            with zipfile.ZipFile(ruta_plantilla) as plantilla:
                relaciones = ElementTree.fromstring(plantilla.read("word/_rels/header1.xml.rels"))
                relacion_imagen = next(
                    relacion for relacion in relaciones
                    if relacion.attrib.get("Type", "").endswith("/image")
                )
                parte_imagen = os.path.normpath(os.path.join("word", relacion_imagen.attrib["Target"]))
                parte_imagen = parte_imagen.replace("\\", "/")
                extension = os.path.splitext(parte_imagen)[1] or ".png"
                with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as archivo_logo:
                    archivo_logo.write(plantilla.read(parte_imagen))
                    return archivo_logo.name
        except (OSError, KeyError, StopIteration, zipfile.BadZipFile, ElementTree.ParseError):
            continue
    return None

BasePDF = FPDF if HAS_FPDF else object

class PDFReporte(BasePDF):
    def __init__(self, logo_path=None):
        super().__init__(orientation="P", unit="mm", format="letter")
        self.logo_path = logo_path
        self.set_margins(30, 49, 20)
        self.set_auto_page_break(auto=True, margin=20)
        self.alias_nb_pages()

    def header(self):
        if not HAS_FPDF: return
        if self.logo_path and os.path.exists(self.logo_path):
            self.image(self.logo_path, x=17, y=12, w=38)

        self.set_text_color(0, 0, 0)
        self.set_xy(59, 13)
        self.set_font("Arial", "B", 10)
        self.cell(98, 6, safe_txt("SISTEMA DE GESTIÓN INTEGRAL"), 0, 2, "C")
        self.cell(98, 6, safe_txt("GESTIÓN COMERCIAL"), 0, 2, "C")
        self.set_font("Arial", "B", 9)
        self.cell(98, 6, safe_txt("INFORME DE GESTION COMERCIAL"), 0, 0, "C")

        self.set_xy(158, 12)
        self.set_font("Arial", "", 7)
        self.cell(49, 5, safe_txt("Código: COM-FT-15"), 0, 2, "L")
        self.cell(49, 5, safe_txt("Fecha: 17/02/2025"), 0, 2, "L")
        self.cell(49, 5, safe_txt("Versión: 01"), 0, 2, "L")
        self.cell(49, 5, safe_txt(f"Página {self.page_no()} de {{nb}}"), 0, 0, "L")

        self.set_draw_color(146, 208, 80)
        self.set_line_width(0.8)
        self.line(17, 43, 207, 43)
        self.set_line_width(0.25)
        self.line(17, 44.3, 207, 44.3)
        self.set_y(50)

    def footer(self):
        if not HAS_FPDF: return
        self.set_draw_color(146, 208, 80)
        self.set_line_width(0.6)
        self.line(17, self.h - 17, self.w - 9, self.h - 17)
        self.set_y(-15)
        self.set_font("Arial", "", 8)
        self.set_text_color(0, 0, 0)
        self.cell(0, 8, safe_txt(f"Página {self.page_no()} de {{nb}}"), 0, 0, "C")
        
    def draw_table(self, header, data, col_widths):
        ancho_disponible = self.w - self.l_margin - self.r_margin
        ancho_total = sum(col_widths)
        if ancho_total > ancho_disponible:
            escala = ancho_disponible / ancho_total
            col_widths = [ancho * escala for ancho in col_widths]
        self.set_fill_color(32, 55, 100)
        self.set_text_color(255, 255, 255)
        self.set_font('Arial', 'B', 9)
        for i in range(len(header)):
            self.cell(col_widths[i], 8, safe_txt(header[i]), border=1, fill=True, align='C')
        self.ln()
        self.set_text_color(0, 0, 0)
        self.set_font('Arial', '', 8)
        fill = False
        for row in data:
            if self.get_y() + 15 > self.h - self.b_margin:
                self.add_page()
                self.set_fill_color(32, 55, 100)
                self.set_text_color(255, 255, 255)
                self.set_font('Arial', 'B', 9)
                for i in range(len(header)):
                    self.cell(col_widths[i], 8, safe_txt(header[i]), border=1, fill=True, align='C')
                self.ln()
                self.set_text_color(0, 0, 0)
                self.set_font('Arial', '', 8)
                
            if fill: self.set_fill_color(240, 240, 240)
            else: self.set_fill_color(255, 255, 255)
            for i in range(len(row)):
                text = str(row[i])[:85] + "..." if len(str(row[i])) > 88 else str(row[i])
                self.cell(col_widths[i], 7, safe_txt(text), border=1, fill=fill, align='C' if i != 0 else 'L')
            self.ln()
            fill = not fill

# NUEVO: Popup para seleccionar clústeres a exportar
def popup_exportar_pdf():
    if not HAS_FPDF:
        messagebox.showerror("Librería faltante", "Para generar el PDF necesitas instalar la librería FPDF.\nAbre tu consola y ejecuta:\npip install fpdf")
        return

    pop = ctk.CTkToplevel(ventana)
    pop.title("Configurar Exportación PDF")
    pop.geometry("450x550")
    pop.grab_set()
    pop.configure(fg_color="#f4f6f9")

    ctk.CTkLabel(pop, text="Selecciona los Clústeres a exportar", font=("Arial", 16, "bold"), text_color="#2c3e50").pack(pady=15)

    con = sqlite3.connect("sistema_gd_v4.db")
    clusters_db = con.execute("SELECT DISTINCT cluster FROM proyectos WHERE estado_general != 'DESCARTADO'").fetchall()
    con.close()

    cl_list = sorted(list(set([c[0] if c[0] and c[0] != "N/A" else "Individual" for c in clusters_db])))

    if not cl_list:
        ctk.CTkLabel(pop, text="No hay proyectos activos.", font=("Arial", 14)).pack(pady=30)
        return

    scroll = ctk.CTkScrollableFrame(pop, width=350, height=350, fg_color="#ffffff", border_width=1, border_color="#bdc3c7")
    scroll.pack(pady=10, padx=20, fill="both", expand=True)

    vars_clusters = {}
    var_todos = ctk.BooleanVar(value=True)

    def on_todos():
        val = var_todos.get()
        for v in vars_clusters.values():
            v.set(val)

    def check_individual():
        all_checked = all(v.get() for v in vars_clusters.values())
        var_todos.set(all_checked)

    cb_todos = ctk.CTkCheckBox(scroll, text="Seleccionar Todos", variable=var_todos, command=on_todos, font=("Arial", 13, "bold"), text_color="#d35400", fg_color="#d35400")
    cb_todos.pack(anchor="w", pady=(10, 15), padx=10)

    for cl in cl_list:
        var = ctk.BooleanVar(value=True)
        vars_clusters[cl] = var
        ctk.CTkCheckBox(scroll, text=cl, variable=var, command=check_individual, font=("Arial", 13), text_color="#2c3e50").pack(anchor="w", pady=5, padx=20)

    def ejecutar_exportacion():
        seleccionados = [cl for cl, var in vars_clusters.items() if var.get()]
        if not seleccionados:
            messagebox.showwarning("Atención", "Debes seleccionar al menos un clúster.")
            return
        pop.destroy()
        generar_pdf_ejecutivo(seleccionados)

    ctk.CTkButton(pop, text="Siguiente ➔", font=("Arial", 14, "bold"), fg_color="#C0392B", hover_color="#922B21", command=ejecutar_exportacion).pack(pady=20)

def generar_pdf_ejecutivo(clusters_seleccionados):
    ruta_pdf = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")], title="Guardar Reporte Directivo PDF")
    if not ruta_pdf: return

    pop_carga = ctk.CTkToplevel(ventana)
    pop_carga.title("Exportando...")
    pop_carga.geometry("350x150")
    pop_carga.grab_set()
    ctk.CTkLabel(pop_carga, text="⏳ Generando PDF Selectivo...", font=("Arial", 16, "bold"), text_color="#2c3e50").pack(pady=(40, 10))
    ctk.CTkLabel(pop_carga, text="Procesando gráficas y mapas.\nEsto puede tomar unos segundos...", font=("Arial", 12)).pack()

    def tarea_pdf():
        archivos_temporales = []
        try:
            con = sqlite3.connect("sistema_gd_v4.db")
            df_proy = pd.read_sql_query("SELECT * FROM proyectos WHERE estado_general != 'DESCARTADO' ORDER BY cluster ASC, id ASC", con)
            df_req = pd.read_sql_query("SELECT * FROM requisitos", con)
            con.close()

            # Filtrado selectivo según los clústeres elegidos por el usuario
            df_proy['cluster_calc'] = df_proy['cluster'].apply(lambda x: x if x and x != "N/A" else "Individual")
            df_proy = df_proy[df_proy['cluster_calc'].isin(clusters_seleccionados)]

            if df_proy.empty:
                ventana.after(0, lambda: messagebox.showwarning("Sin Datos", "No hay proyectos en los clústeres seleccionados."))
                return

            reqs_filtrados = []
            for _, p in df_proy.iterrows():
                p_id = p['id']
                p_serv = p['req_servidumbre']
                p_cont = p['req_contrato']
                p_reqs = df_req[df_req['proyecto_id'] == p_id]
                for _, r in p_reqs.iterrows():
                    if r['categoria'] in ["Ingeniería Básica", "Análisis Técnico"]: continue
                    if r['categoria'] == "Servidumbre" and not p_serv: continue
                    if r['categoria'] == "Modelo de Contrato" and not p_cont: continue
                    reqs_filtrados.append(r)
                    
            reqs_validos = pd.DataFrame(reqs_filtrados)

            total_proys = len(df_proy)
            clusters = len(clusters_seleccionados)
            cap_total = df_proy['capacidad_kw'].sum()
            area_total = df_proy['area'].sum()

            plt.switch_backend('Agg')
            
            fig1, ax1 = plt.subplots(figsize=(7, 4))
            cl_names = sorted(df_proy['cluster_calc'].unique())
            cl_vals = []
            
            for c in cl_names:
                p_ids = df_proy[df_proy['cluster_calc'] == c]['id'].tolist()
                reqs_c = reqs_validos[reqs_validos['proyecto_id'].isin(p_ids)]
                t = len(reqs_c)
                comp = len(reqs_c[reqs_c['estado'] == 'COMPLETADO'])
                cl_vals.append((comp/t*100) if t > 0 else 0)
                
            display_names = [c[:12]+"..." if len(c)>12 else c for c in cl_names]
            ax1.bar(display_names, cl_vals, color='#3498db')
            ax1.set_title("Eficiencia de Legalización por Clúster (%)", fontweight='bold')
            ax1.set_ylim(0, 105)
            for i, v in enumerate(cl_vals): 
                ax1.text(i, v + 2, f"{v:.1f}%", ha='center', fontweight='bold')
                
            tmp1 = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
            archivos_temporales.append(tmp1)
            fig1.tight_layout()
            fig1.savefig(tmp1)
            plt.close(fig1)

            fig3, ax3 = plt.subplots(figsize=(7, 4))
            cap_por_cluster = df_proy.groupby('cluster_calc')['capacidad_kw'].sum().reset_index()
            disp_cap = [c[:12]+"..." if len(c)>12 else c for c in cap_por_cluster['cluster_calc']]
            
            ax3.bar(disp_cap, cap_por_cluster['capacidad_kw'], color='#f39c12')
            ax3.set_title("Capacidad Proyectada por Clúster (kW)", fontweight='bold')
            for i, v in enumerate(cap_por_cluster['capacidad_kw']): 
                ax3.text(i, v + (v*0.02), f"{v:,.0f}", ha='center', fontweight='bold')
                
            tmp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
            archivos_temporales.append(tmp3)
            fig3.tight_layout()
            fig3.savefig(tmp3)
            plt.close(fig3)

            logo_plantilla = extraer_logo_plantilla_pdf()
            if logo_plantilla:
                archivos_temporales.append(logo_plantilla)
            pdf = PDFReporte(logo_plantilla)
            pdf.add_page()
            pdf.set_font('Arial', 'B', 15)
            pdf.set_text_color(32, 55, 100)
            pdf.cell(0, 10, safe_txt('1. RESUMEN EJECUTIVO (CLÚSTERES SELECCIONADOS)'), 0, 1, 'L')
            
            pdf.set_font('Arial', '', 11)
            pdf.set_text_color(0, 0, 0)
            
            texto_resumen = f"Este documento presenta el estado de avance técnico, legal y predial del portafolio. Según la selección solicitada, el reporte incluye {total_proys} proyectos activos estructurados en {clusters} clústeres.\n\nLa capacidad proyectada de esta selección asciende a {cap_total:,.0f} kW, abarcando una extensión superficial de {area_total:,.1f} hectáreas."
            pdf.multi_cell(0, 7, safe_txt(texto_resumen), align='J')
            pdf.ln(5)
            
            pdf.image(tmp3, x=35, w=140)
            pdf.ln(5)

            pdf.set_font('Arial', 'B', 15)
            pdf.set_text_color(32, 55, 100)
            pdf.cell(0, 10, safe_txt('2. TOP 5 PROYECTOS POR CAPACIDAD (SELECCIÓN)'), 0, 1, 'L')
            pdf.ln(2)
            
            df_top = df_proy.sort_values(by='capacidad_kw', ascending=False).head(5)
            data_top = []
            for _, r in df_top.iterrows():
                data_top.append([str(r['nombre']), str(r['cluster_calc']), str(r['municipio']), f"{r['capacidad_kw']:,.0f} kW", f"{r['area']} ha"])
            
            pdf.draw_table(["Proyecto", "Clúster", "Municipio", "Capacidad", "Área"], data_top, [60, 35, 40, 30, 25])

            cat_radar = ['Trámites de Terreno', 'Trámites OR', 'Servidumbre', 'Modelo de Contrato', 'Antecedentes']
            cat_db = ['Trámites de Terreno', 'Trámites OR', 'Servidumbre', 'Modelo de Contrato', 'Antecedentes']

            for c_name in cl_names:
                pdf.add_page()
                pdf.set_font('Arial', 'B', 15)
                pdf.set_text_color(32, 55, 100)
                
                pdf.cell(0, 10, safe_txt(f'ANÁLISIS DE CLÚSTER: {c_name}'), 0, 1, 'L')
                
                pdf.set_font('Arial', '', 10)
                pdf.set_text_color(0, 0, 0)
                
                p_ids = df_proy[df_proy['cluster_calc'] == c_name]['id'].tolist()
                proys_cl = df_proy[df_proy['cluster_calc'] == c_name]
                cap_cl = proys_cl['capacidad_kw'].sum()
                area_cl = proys_cl['area'].sum()
                num_cl = len(proys_cl)
                
                p_ref_id = p_ids[0]

                pdf.multi_cell(0, 6, safe_txt(f"Resumen: Este segmento cuenta con {num_cl} proyectos activos. Capacidad total de {cap_cl:,.0f} kW en un área de {area_cl:,.1f} ha."), align='J')
                pdf.ln(3)

                data_cl = []
                for _, r in proys_cl.iterrows():
                    data_cl.append([str(r['nombre'])[:30], str(r['direccion']), str(r['municipio']), str(r['departamento'])[:15], f"{r['capacidad_kw']:,.0f} kW"])
                
                pdf.draw_table(["Proyecto", "Dirección Predio", "Municipio", "Depto", "Capacidad"], data_cl, [35, 85, 25, 15, 25])
                pdf.ln(5)
                
                m_path = None
                coordenadas_disponibles = False
                for _, r in proys_cl.iterrows():
                    l_lat, l_lon = str(r['latitud']).strip(), str(r['longitud']).strip()
                    try:
                        latitud, longitud = float(l_lat.replace(',', '.')), float(l_lon.replace(',', '.'))
                    except ValueError:
                        continue
                    if -85.05112878 <= latitud <= 85.05112878 and -180 <= longitud <= 180:
                        coordenadas_disponibles = True
                        m_path = descargar_mapa_google(l_lat, l_lon)
                        if m_path:
                            archivos_temporales.append(m_path)
                            break
                
                if m_path:
                    if pdf.get_y() > 140: 
                        pdf.add_page()
                    pdf.set_font('Arial', 'B', 12)
                    pdf.set_text_color(32, 55, 100)
                    pdf.cell(0, 10, safe_txt("Ubicación Satelital (Google Maps / respaldo Esri - Zoom Nivel 14)"), 0, 1, 'C')
                    pdf.image(m_path, x=45, y=pdf.get_y() + 2, w=120, h=120) 
                    pdf.set_y(pdf.get_y() + 125) 
                else:
                    pdf.set_font('Arial', 'I', 10)
                    mensaje_mapa = "(No fue posible descargar el mapa satelital; revise la conexión a internet)" if coordenadas_disponibles else "(No hay coordenadas válidas registradas en este clúster)"
                    pdf.cell(0, 10, safe_txt(mensaje_mapa), 0, 1, 'C')
                    pdf.ln(5)

                if pdf.get_y() > 170:
                    pdf.add_page()

                reqs_ref = reqs_validos[reqs_validos['proyecto_id'] == p_ref_id]
                c_comp = len(reqs_ref[reqs_ref['estado'] == 'COMPLETADO'])
                c_pend = len(reqs_ref[reqs_ref['estado'] == 'PENDIENTE'])
                c_venc = len(reqs_ref[reqs_ref['estado'] == 'VENCIDO'])
                c_proc = len(reqs_ref[reqs_ref['estado'].isin(['EN TRÁMITE', 'RADICADO', 'EN SUBSANACIONES'])])
                
                pdf.set_font('Arial', 'B', 11)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(0, 8, safe_txt(f"Estado Legal Global (Basado en Proyecto Referencia): {c_comp} Completados | {c_proc} En Proceso | {c_venc} Vencidos | {c_pend} Pendientes"), 0, 1, 'L')
                
                pcts = []
                for cat_str in cat_db:
                    rc = reqs_ref[reqs_ref['categoria'] == cat_str]
                    if len(rc) > 0: 
                        pcts.append((len(rc[rc['estado'] == 'COMPLETADO']) / len(rc)) * 100)
                    else: 
                        pcts.append(0)
                
                valores_radar = pcts + [pcts[0]]
                angulos = [n / float(len(cat_radar)) * 2 * np.pi for n in range(len(cat_radar))]
                angulos += angulos[:1]

                fig_r, ax_r = plt.subplots(figsize=(4, 4), subplot_kw=dict(polar=True))
                ax_r.plot(angulos, valores_radar, linewidth=2, linestyle='solid', color='#3498db')
                ax_r.fill(angulos, valores_radar, '#3498db', alpha=0.25)
                ax_r.set_xticks(angulos[:-1])
                ax_r.set_xticklabels(cat_radar, fontsize=8)
                ax_r.set_ylim(0, 100)
                ax_r.set_yticks([20, 40, 60, 80])
                ax_r.set_yticklabels(['20', '40', '60', '80'], color='gray', size=7)
                
                tmp_radar = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
                archivos_temporales.append(tmp_radar)
                fig_r.tight_layout()
                fig_r.savefig(tmp_radar)
                plt.close(fig_r)

                pos_y_radar = pdf.get_y()
                pdf.image(tmp_radar, x=10, w=85)
                
                pdf.set_xy(105, pos_y_radar + 5)
                pdf.set_font('Arial', 'B', 12)
                pdf.set_text_color(192, 57, 43)
                pdf.cell(0, 6, safe_txt("Análisis de Ruta Crítica y Cuellos de Botella:"), 0, 1, 'L')
                
                pdf.set_font('Arial', '', 9)
                pdf.set_text_color(0, 0, 0)
                pdf.set_x(105)

                reqs_vencidos = reqs_ref[reqs_ref['estado'] == 'VENCIDO']
                if not reqs_vencidos.empty:
                    sug = f"ALERTA: Se detecta(n) {len(reqs_vencidos)} trámite(s) crítico(s) VENCIDO(S) afectando a todo el clúster:\n\n"
                    for _, rv in reqs_vencidos.iterrows():
                        try:
                            f_lim = datetime.datetime.strptime(rv['fecha_limite'], "%d/%m/%Y").date()
                            dias_v = (datetime.date.today() - f_lim).days
                            txt_v = f"hace {dias_v} días" if dias_v > 0 else "hoy"
                        except:
                            txt_v = "fecha límite desconocida"
                        sug += f"- {rv['descripcion']} ({rv['entidad']}) - Vencido {txt_v}.\n"
                    
                    sug += "\nSUGERENCIA ESTRATÉGICA:\nPriorizar de inmediato la gestión documental de los trámites listados. Se recomienda radicar Derechos de Petición reiterativos y agendar mesa de seguimiento urgente con la(s) respectiva(s) entidad(es) para evitar multas o bloqueos definitivos en el clúster."
                elif c_proc > 0:
                    cat_prob = reqs_ref[reqs_ref['estado'].isin(['EN TRÁMITE', 'RADICADO', 'EN SUBSANACIONES'])]['categoria'].mode()[0]
                    sug = f"No existen trámites vencidos. Sin embargo, hay {c_proc} procesos atascados o en trámite.\n\nSUGERENCIA ESTRATÉGICA:\nConcentrar el esfuerzo operativo y jurídico en el módulo de '{cat_prob}' para asegurar que las aprobaciones pendientes fluyan y no se conviertan próximamente en alertas de ruta crítica para el clúster."
                else:
                    sug = "El clúster presenta un estado de legalización óptimo. No se registran vencimientos ni trámites atrapados en ruta crítica.\n\nSUGERENCIA ESTRATÉGICA:\nMantener la vigilancia pasiva sobre los requisitos pendientes antes de dar vía libre a la fase constructiva EPC completa."
                
                pdf.multi_cell(95, 4.5, safe_txt(sug), align='J')

                y_despues_texto = pdf.get_y()
                y_despues_imagen = pos_y_radar + 85
                pdf.set_y(max(y_despues_texto, y_despues_imagen) + 5)

                reqs_cronograma = reqs_ref[(reqs_ref['fecha_radicacion'].notnull() & (reqs_ref['fecha_radicacion'] != '')) | (reqs_ref['fecha_final'].notnull() & (reqs_ref['fecha_final'] != ''))]
                
                if not reqs_cronograma.empty:
                    if pdf.get_y() > 240: 
                        pdf.add_page()
                    pdf.set_font('Arial', 'B', 12)
                    pdf.set_text_color(32, 55, 100)
                    pdf.cell(0, 10, safe_txt("CRONOGRAMA DE TRÁMITES ACTIVOS (Ruta Crítica)"), 0, 1, 'L')
                    
                    crono_data = []
                    for _, rc in reqs_cronograma.iterrows():
                        f_rad = rc['fecha_radicacion'] if pd.notnull(rc['fecha_radicacion']) and rc['fecha_radicacion'] else "-"
                        f_lim = rc['fecha_limite'] if pd.notnull(rc['fecha_limite']) and rc['fecha_limite'] else "-"
                        f_fin = rc['fecha_final'] if pd.notnull(rc['fecha_final']) and rc['fecha_final'] else "-"
                        
                        fecha_mostrar = f_fin if rc['estado'] == 'COMPLETADO' else f_lim
                        crono_data.append([str(rc['descripcion'])[:45], str(rc['entidad'])[:15], f_rad, fecha_mostrar, rc['estado']])
                    
                    pdf.draw_table(["Requisito Afectado", "Entidad", "Radicado", "Límite/Cierre", "Estado"], crono_data, [75, 30, 25, 25, 35])

            pdf.output(ruta_pdf)
            ventana.after(0, lambda: messagebox.showinfo("Éxito", "Reporte Directivo PDF generado exitosamente."))
            ventana.after(0, lambda: os.startfile(ruta_pdf))

        except Exception as e:
            ventana.after(0, lambda e=e: messagebox.showerror("Error", f"No se pudo generar el PDF.\n{str(e)}"))

        finally:
            for f in archivos_temporales:
                try: os.remove(f)
                except: pass
            ventana.after(0, pop_carga.destroy)

    threading.Thread(target=tarea_pdf, daemon=True).start()

# ==========================================
# 11. MENÚ LATERAL AGRUPADO, LOGIN Y CIERRE
# ==========================================
COLORES_OSCUROS = {
    "#f4f6f9": "#1c2128",
    "#ffffff": "#252a31",
    "#e5e8e8": "#343b44",
    "#d5d8dc": "#454e58",
    "#bdc3c7": "#5e6872",
    "#ecf0f1": "#2b3138",
    "#f8f9f9": "#20262d",
    "#fdf2e9": "#3b424b",
    "#626f70": "#525b66",
    "#2c3e50": "#e6edf3",
    "#154360": "#c9e4ff",
}
COLORES_CLAROS = {oscuro: claro for claro, oscuro in COLORES_OSCUROS.items()}
COLORES_TEXTO_OSCUROS = {
    "#2c3e50": "#e6edf3",
    "#154360": "#c9e4ff",
    "#34495e": "#d0d7de",
    "#7f8c8d": "#a6b0ba",
    "#ffffff": "#ffffff",
}
COLORES_TEXTO_CLAROS = {oscuro: claro for claro, oscuro in COLORES_TEXTO_OSCUROS.items()}

def aplicar_tema(widget, oscuro):
    global modo_oscuro
    modo_oscuro = oscuro
    ctk.set_appearance_mode("dark" if oscuro else "light")
    mapa_fondos = COLORES_OSCUROS if oscuro else COLORES_CLAROS
    mapa_textos = COLORES_TEXTO_OSCUROS if oscuro else COLORES_TEXTO_CLAROS

    def aplicar_a_widget(actual):
        for atributo in ("fg_color", "bg_color", "border_color", "hover_color", "text_color", "text_color_disabled"):
            try:
                color_actual = actual.cget(atributo)
                if not isinstance(color_actual, str):
                    continue
                mapa = mapa_textos if atributo.startswith("text_color") else mapa_fondos
                color_nuevo = mapa.get(color_actual.lower())
                if color_nuevo:
                    actual.configure(**{atributo: color_nuevo})
            except Exception:
                pass
        for hijo in actual.winfo_children():
            aplicar_a_widget(hijo)

    aplicar_a_widget(widget)

def bloquear_sesion():
    global usuario_actual, barra_lateral, contenedor_principal, area_principal, marco_login
    usuario_actual = None
    for widget in ventana.winfo_children():
        widget.destroy()
    barra_lateral = contenedor_principal = area_principal = marco_login = None
    mostrar_login()
    aplicar_tema(ventana, modo_oscuro)

def cerrar_aplicacion(): 
    try:
        if not os.path.exists("backups"): 
            os.makedirs("backups")
        fecha_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2("sistema_gd_v4.db", f"backups/sistema_gd_v4_autoclose_{fecha_str}.db")
    except: 
        pass
    os._exit(0)

ventana.protocol("WM_DELETE_WINDOW", cerrar_aplicacion)

# NUEVO: Barra Lateral agrupada por módulos desplegables
def construir_menu_lateral():
    global barra_lateral
    marco_botones_lat = ctk.CTkFrame(barra_lateral, fg_color="transparent")
    marco_botones_lat.place(x=0, y=0, relwidth=1, relheight=1)

    ctk.CTkLabel(marco_botones_lat, text="MÓDULOS", font=("Arial", 28, "bold"), text_color="#154360").pack(pady=20, padx=20)

    btn_style_header = {"width": 210, "height": 45, "font": ("Arial", 14, "bold"), "corner_radius": 8, "text_color": "white", "anchor": "w"}
    btn_style_sub = {"width": 190, "height": 32, "font": ("Arial", 12, "bold"), "corner_radius": 8, "text_color": "#2c3e50", "fg_color": "#e5e8e8", "hover_color": "#d5d8dc"}

    def crear_acordeon(padre, titulo, color, comandos, controles=None):
        f_grupo = ctk.CTkFrame(padre, fg_color="transparent")
        f_grupo.pack(fill="x", padx=15, pady=5)

        b_head = ctk.CTkButton(f_grupo, text=f"▶  {titulo}", fg_color=color, hover_color=color, **btn_style_header)
        b_head.pack(fill="x")

        f_sub = ctk.CTkFrame(f_grupo, fg_color="transparent")
        estado = [False]

        def toggle():
            if estado[0]:
                f_sub.pack_forget()
                b_head.configure(text=f"▶  {titulo}")
                estado[0] = False
            else:
                f_sub.pack(fill="x", pady=(5,0))
                b_head.configure(text=f"▼  {titulo}")
                estado[0] = True

        b_head.configure(command=toggle)

        for texto, cmd in comandos:
            ctk.CTkButton(f_sub, text=texto, command=cmd, **btn_style_sub).pack(pady=2)

        for texto, variable, comando in controles or []:
            ctk.CTkSwitch(f_sub, text=texto, variable=variable, onvalue="dark", offvalue="light", command=comando).pack(pady=6, padx=10, anchor="w")

        return toggle

    # 1. GESTIÓN
    cmds_gestion = []
    if usuario_actual and usuario_actual[2] == "Administrador":
        cmds_gestion.extend([("+ Nuevo Clúster", mostrar_crear_cluster), ("✏ Editar nombre del clúster", mostrar_renombrar_cluster), ("+ Nuevo Proyecto", mostrar_formulario)])
    cmds_gestion.extend([("📋 Consolidado", mostrar_lista), ("📂 Gestor de Soportes", mostrar_pestana_soportes), ("📡 Radicados OR", mostrar_modulo_radicados)])
    toggle_gestion = crear_acordeon(marco_botones_lat, "GESTIÓN", "#2980b9", cmds_gestion)
    toggle_gestion() # Abrir por defecto

    # 2. EXPORTACIÓN
    cmds_export = [("📥 Exportar Excel", exportar_excel), ("📊 Exportar Gantt", exportar_gantt_excel), ("📑 Exportar PDF", popup_exportar_pdf)]
    crear_acordeon(marco_botones_lat, "EXPORTACIÓN", "#27AE60", cmds_export)

    # 3. DASHBOARD (Botón Único)
    ctk.CTkButton(marco_botones_lat, text="📊 DASHBOARD", command=mostrar_dashboard, width=210, height=45, font=("Arial", 14, "bold"), corner_radius=8, text_color="white", fg_color="#6C3483", hover_color="#512E5F", anchor="w").pack(pady=5, padx=15, fill="x")

    # 4. CONFIGURACIÓN
    cmds_conf = []
    if usuario_actual and usuario_actual[2] == "Administrador":
        cmds_conf.append(("👥 Gestor de Usuarios", mostrar_gestor_usuarios))
    cmds_conf.extend([("👤 Mi Perfil", mostrar_perfil), ("💾 Crear Backup BD", respaldar_base_datos), ("🔄 Restaurar BD", restaurar_base_datos), ("🔒 Bloquear sesión", bloquear_sesion)])
    modo_oscuro_var = ctk.StringVar(value="dark" if modo_oscuro else "light")
    crear_acordeon(
        marco_botones_lat,
        "CONFIGURACIÓN",
        "#7f8c8d",
        cmds_conf,
        controles=[("Modo oscuro", modo_oscuro_var, lambda: aplicar_tema(ventana, modo_oscuro_var.get() == "dark"))],
    )

    # SALIR
    ctk.CTkButton(marco_botones_lat, text="🚪 Salir del Sistema", command=cerrar_aplicacion, width=210, height=40, font=("Arial", 14, "bold"), corner_radius=8, text_color="white", fg_color="#212F3D", hover_color="#17202A").pack(side="bottom", pady=25, padx=15, fill="x")

def construir_ui_principal():
    global barra_lateral, contenedor_principal, area_principal
    ventana.grid_columnconfigure(0, weight=0) 
    ventana.grid_columnconfigure(1, weight=1) 
    ventana.grid_rowconfigure(0, weight=1)
    
    barra_lateral = ctk.CTkFrame(ventana, width=240, corner_radius=0, fg_color="transparent")
    barra_lateral.grid(row=0, column=0, sticky="nsew")
    render_gradiente_lateral(barra_lateral)
    construir_menu_lateral()
    
    contenedor_principal = ctk.CTkFrame(ventana, corner_radius=0, fg_color="#f4f6f9")
    contenedor_principal.grid(row=0, column=1, sticky="nsew")
    
    area_principal = ctk.CTkScrollableFrame(contenedor_principal, corner_radius=0, fg_color="#f4f6f9")
    area_principal.pack(fill="both", expand=True)
    
    mostrar_lista()

def mostrar_login():
    global marco_login
    marco_login = ctk.CTkFrame(ventana)
    marco_login.pack(fill="both", expand=True)

    rutas_fondo = [
        resource_path("chaparrera.png"),
        resource_path("fondo_login.jpg"),
        resource_path("fondo_login.png"),
    ]
    ruta_fondo = next((ruta for ruta in rutas_fondo if os.path.exists(ruta)), None)

    if ruta_fondo:
        try:
            img_f = Image.open(ruta_fondo)
            img_bg = ctk.CTkImage(light_image=img_f, dark_image=img_f, size=(1400, 900))
            lbl_bg = ctk.CTkLabel(marco_login, image=img_bg, text="")
            lbl_bg.place(x=0, y=0, relwidth=1, relheight=1)
        except Exception:
            marco_login.configure(fg_color="#e5e8e8")
    else:
        marco_login.configure(fg_color="#e5e8e8")

    caja_central = ctk.CTkFrame(marco_login, fg_color="#ffffff", corner_radius=15, width=450, height=550, border_color="#d5d8dc", border_width=1)
    caja_central.place(relx=0.5, rely=0.5, anchor="center")
    
    lbl_log_tit = ctk.CTkLabel(caja_central, text="GESTOR DE PROYECTOS\nGENERACIÓN DISTRIBUIDA GD", font=("Arial", 22, "bold"), text_color="#154360", justify="center")
    lbl_log_tit.pack(pady=(40, 5))
    
    lbl_log_ver = ctk.CTkLabel(caja_central, text="VERSIÓN V1.0", font=("Arial", 14, "bold"), text_color="#e67e22")
    lbl_log_ver.pack(pady=(0, 30))
    
    lbl_log_usr = ctk.CTkLabel(caja_central, text="Usuario:", font=("Arial", 14, "bold"), text_color="#2c3e50")
    lbl_log_usr.pack(anchor="w", padx=50, pady=(10, 0))
    
    ent_user = ctk.CTkEntry(caja_central, width=350, height=40, fg_color="#f4f6f9", text_color="#2c3e50", border_color="#bdc3c7")
    ent_user.pack(padx=50, pady=(5, 15))
    
    lbl_log_pass = ctk.CTkLabel(caja_central, text="Contraseña:", font=("Arial", 14, "bold"), text_color="#2c3e50")
    lbl_log_pass.pack(anchor="w", padx=50, pady=(10, 0))
    
    ent_pass = ctk.CTkEntry(caja_central, width=350, height=40, show="*", fg_color="#f4f6f9", text_color="#2c3e50", border_color="#bdc3c7")
    ent_pass.pack(padx=50, pady=(5, 25))
    
    def intentar_login(e=None):
        u = ent_user.get()
        p = ent_pass.get()
        con = sqlite3.connect("sistema_gd_v4.db")
        cur = con.cursor()
        cur.execute("SELECT id, nombre, rol, usuario FROM usuarios WHERE usuario=? AND password=?", (u, p))
        user = cur.fetchone()
        con.close()
        
        if user:
            global usuario_actual
            usuario_actual = user
            marco_login.destroy()
            construir_ui_principal()
            aplicar_tema(ventana, modo_oscuro)
        else:
            messagebox.showerror("Acceso Denegado", "Usuario o contraseña incorrectos.\n(Intenta con admin / admin123)")
            
    evento_enter = "<" + "Return" + ">"
    ent_pass.bind(evento_enter, intentar_login)
    
    btn_ingresar = ctk.CTkButton(caja_central, text="Ingresar al Sistema", height=45, width=350, font=("Arial", 16, "bold"), fg_color="#2980b9", hover_color="#1f618d", text_color="white", command=intentar_login)
    btn_ingresar.pack(padx=50, pady=10)
    
    lbl_log_cred = ctk.CTkLabel(caja_central, text="(Credenciales iniciales: admin / admin123)", font=("Arial", 11, "italic"), text_color="#7f8c8d")
    lbl_log_cred.pack(pady=(0, 20))
    
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    hoy = datetime.date.today()
    fecha_str = f"{hoy.day:02d} de {meses[hoy.month - 1]} de {hoy.year}"
    
    footer = ctk.CTkFrame(caja_central, fg_color="transparent")
    footer.pack(side="bottom", fill="x", pady=20)
    
    lbl_foot_1 = ctk.CTkLabel(footer, text="Programado por: Fernando Useche Arevalo", font=("Arial", 12, "bold"), text_color="#34495e")
    lbl_foot_1.pack()
    
    lbl_foot_2 = ctk.CTkLabel(footer, text=f"Fecha: {fecha_str}", font=("Arial", 11), text_color="#7f8c8d")
    lbl_foot_2.pack()

iniciar_base_datos()
mostrar_login()
ventana.mainloop()