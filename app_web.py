import hashlib
import time

import pandas as pd
import requests
import streamlit as st


st.set_page_config(page_title="Portafolio GD", page_icon=":material/solar_power:", layout="wide")

try:
    SUPABASE_URL = st.secrets["supabase"]["url"].rstrip("/")
    SUPABASE_ANON_KEY = st.secrets["supabase"]["anon_key"]
except Exception:
    st.title("Gestor de proyectos GD")
    st.error(
        "La aplicación web todavía no está configurada.",
        icon=":material/lock:",
    )
    st.caption("Agrega la URL y la clave pública anon del proyecto en los secretos de Streamlit.")
    st.stop()


class PortalError(RuntimeError):
    pass


def correo_interno(usuario: str) -> str:
    digest = hashlib.sha256(usuario.strip().encode("utf-8")).hexdigest()
    return f"u{digest}@login.gestor-gd.invalid"


def solicitar_supabase(method, endpoint, token=None, params=None, payload=None):
    headers = {"apikey": SUPABASE_ANON_KEY}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.request(
            method,
            f"{SUPABASE_URL}{endpoint}",
            headers=headers,
            params=params,
            json=payload,
            timeout=(8, 25),
        )
    except requests.RequestException as error:
        raise PortalError("No se pudo conectar con el servicio de datos.") from error
    if not response.ok:
        raise PortalError(f"El servicio de datos respondió con el código {response.status_code}.")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as error:
        raise PortalError("El servicio devolvió una respuesta no válida.") from error


def borrar_sesion():
    for key in ("access_token", "refresh_token", "expires_at", "user_profile"):
        st.session_state.pop(key, None)


def iniciar_sesion(usuario: str, password: str):
    auth = solicitar_supabase(
        "POST",
        "/auth/v1/token",
        params={"grant_type": "password"},
        payload={"email": correo_interno(usuario), "password": password},
    )
    if not isinstance(auth, dict) or not auth.get("access_token") or not auth.get("user", {}).get("id"):
        raise PortalError("Usuario o contraseña incorrectos.")

    perfil = solicitar_supabase(
        "GET",
        "/rest/v1/web_profiles",
        token=auth["access_token"],
        params={
            "select": "auth_user_id,username,display_name,role,enabled",
            "auth_user_id": f"eq.{auth['user']['id']}",
            "limit": "1",
        },
    )
    if not perfil or not perfil[0].get("enabled"):
        raise PortalError("La cuenta web no está habilitada. Consulta al administrador.")

    st.session_state["access_token"] = auth["access_token"]
    st.session_state["refresh_token"] = auth.get("refresh_token")
    st.session_state["expires_at"] = time.time() + int(auth.get("expires_in", 3600))
    st.session_state["user_profile"] = perfil[0]


def obtener_token_vigente():
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    expires_at = st.session_state.get("expires_at", 0)
    if not access_token or not refresh_token:
        borrar_sesion()
        return None
    if expires_at - time.time() > 60:
        return access_token

    try:
        auth = solicitar_supabase(
            "POST",
            "/auth/v1/token",
            params={"grant_type": "refresh_token"},
            payload={"refresh_token": refresh_token},
        )
    except PortalError:
        borrar_sesion()
        return None
    if not isinstance(auth, dict) or not auth.get("access_token"):
        borrar_sesion()
        return None

    st.session_state["access_token"] = auth["access_token"]
    st.session_state["refresh_token"] = auth.get("refresh_token", refresh_token)
    st.session_state["expires_at"] = time.time() + int(auth.get("expires_in", 3600))
    return auth["access_token"]


def cargar_tabla(tabla: str, token: str, columnas: str, params=None) -> pd.DataFrame:
    filtros = {"select": columnas, "limit": "5000"}
    if params:
        filtros.update(params)
    datos = solicitar_supabase("GET", f"/rest/v1/{tabla}", token=token, params=filtros)
    return pd.DataFrame(datos or [])


def mostrar_login():
    st.title("Gestor de proyectos GD")
    st.caption("Consulta del portafolio de generación distribuida")
    with st.container(border=True):
        with st.form("login_form"):
            usuario = st.text_input("Usuario", autocomplete="username")
            password = st.text_input("Contraseña", type="password", autocomplete="current-password")
            enviar = st.form_submit_button("Ingresar", type="primary", width="stretch")
        if enviar:
            if not usuario.strip() or not password:
                st.warning("Escribe tu usuario y contraseña.")
            else:
                try:
                    iniciar_sesion(usuario, password)
                    st.rerun()
                except PortalError as error:
                    st.error(str(error), title="No se pudo iniciar sesión")


def mostrar_consolidado(proyectos: pd.DataFrame):
    st.title("Consolidado de proyectos")
    if proyectos.empty:
        st.info("No hay proyectos disponibles para esta cuenta.")
        return

    proyectos = proyectos.copy()
    proyectos["cluster"] = proyectos["cluster"].fillna("Individual").replace("", "Individual")
    filtro_cluster = st.selectbox("Clúster", ["Todos"] + sorted(proyectos["cluster"].unique().tolist()))
    filtro_estado = st.selectbox(
        "Estado",
        ["Todos"] + sorted(proyectos["estado_general"].fillna("Sin estado").unique().tolist()),
    )
    busqueda = st.text_input("Buscar proyecto o municipio", type="search")

    filtrados = proyectos
    if filtro_cluster != "Todos":
        filtrados = filtrados[filtrados["cluster"] == filtro_cluster]
    if filtro_estado != "Todos":
        filtrados = filtrados[filtrados["estado_general"].fillna("Sin estado") == filtro_estado]
    if busqueda.strip():
        termino = busqueda.strip().casefold()
        coincidencia = (
            filtrados["nombre"].fillna("").str.casefold().str.contains(termino, regex=False)
            | filtrados["municipio"].fillna("").str.casefold().str.contains(termino, regex=False)
        )
        filtrados = filtrados[coincidencia]

    columnas = ["cluster", "nombre", "municipio", "departamento", "capacidad_kw", "area", "estado_general"]
    visibles = filtrados[columnas].rename(
        columns={
            "cluster": "Clúster",
            "nombre": "Proyecto",
            "municipio": "Municipio",
            "departamento": "Departamento",
            "capacidad_kw": "Capacidad (kW)",
            "area": "Área (ha)",
            "estado_general": "Estado",
        }
    )
    st.dataframe(visibles, hide_index=True, alt="Proyectos filtrados por clúster, estado o municipio")
    st.caption(f"{len(filtrados)} de {len(proyectos)} proyectos")


def mostrar_dashboard(proyectos: pd.DataFrame):
    st.title("Resumen del portafolio")
    if proyectos.empty:
        st.info("No hay proyectos disponibles para calcular indicadores.")
        return

    datos = proyectos.copy()
    datos["capacidad_kw"] = pd.to_numeric(datos["capacidad_kw"], errors="coerce").fillna(0)
    datos["area"] = pd.to_numeric(datos["area"], errors="coerce").fillna(0)
    datos["cluster"] = datos["cluster"].fillna("Individual").replace("", "Individual")
    total_capacidad = datos["capacidad_kw"].sum()
    total_area = datos["area"].sum()

    total_col, capacidad_col, area_col = st.columns(3)
    total_col.metric("Proyectos", f"{len(datos):,}")
    capacidad_col.metric("Capacidad total", f"{total_capacidad:,.0f} kW")
    area_col.metric("Área total", f"{total_area:,.1f} ha")

    por_cluster = (
        datos.groupby("cluster", as_index=False)["capacidad_kw"]
        .sum()
        .sort_values("capacidad_kw", ascending=False)
    )
    st.subheader("Capacidad por clúster")
    st.bar_chart(por_cluster, x="cluster", y="capacidad_kw", alt="Capacidad instalada agrupada por clúster")


def mostrar_detalle(proyectos: pd.DataFrame, token: str):
    st.title("Detalle de proyecto")
    if proyectos.empty:
        st.info("No hay proyectos disponibles.")
        return

    opciones = {
        int(fila["id"]): f"{fila['nombre']} · {fila.get('municipio') or 'Sin municipio'} · {fila.get('cluster') or 'Individual'}"
        for _, fila in proyectos.iterrows()
    }
    proyecto_id = st.selectbox("Proyecto", list(opciones), format_func=lambda value: opciones[value])
    proyecto = proyectos.loc[proyectos["id"] == proyecto_id].iloc[0]
    datos_proyecto = pd.DataFrame(
        [{
            "Clúster": proyecto.get("cluster"),
            "Dirección del predio": proyecto.get("direccion"),
            "Municipio": proyecto.get("municipio"),
            "Departamento": proyecto.get("departamento"),
            "Latitud del predio": proyecto.get("latitud"),
            "Longitud del predio": proyecto.get("longitud"),
            "Coordenadas OR": proyecto.get("coord_conexion"),
            "Capacidad (kW)": proyecto.get("capacidad_kw"),
            "Área (ha)": proyecto.get("area"),
            "Estado": proyecto.get("estado_general"),
        }]
    )
    st.dataframe(datos_proyecto, hide_index=True, alt="Datos generales y coordenadas del proyecto seleccionado")

    requisitos = cargar_tabla(
        "requisitos",
        token,
        "categoria,descripcion,entidad,estado,fecha_radicacion,fecha_limite,fecha_final,observaciones",
        {"proyecto_id": f"eq.{proyecto_id}", "order": "categoria.asc,descripcion.asc"},
    )
    st.subheader("Requisitos")
    if requisitos.empty:
        st.info("Este proyecto no tiene requisitos registrados.")
    else:
        requisitos = requisitos.rename(
            columns={
                "categoria": "Módulo",
                "descripcion": "Requisito",
                "entidad": "Entidad",
                "estado": "Estado",
                "fecha_radicacion": "Radicación",
                "fecha_limite": "Fecha límite",
                "fecha_final": "Cierre",
                "observaciones": "Observaciones",
            }
        )
        st.dataframe(requisitos, hide_index=True, alt="Requisitos y fechas del proyecto seleccionado")


st.title("Gestor de proyectos GD")
st.caption("Consulta web del portafolio")

if "access_token" not in st.session_state:
    st.session_state["access_token"] = None

if not st.session_state["access_token"]:
    mostrar_login()
    st.stop()

token = obtener_token_vigente()
if not token:
    st.rerun()

perfil = st.session_state["user_profile"]
with st.sidebar:
    st.markdown(f"**{perfil['display_name']}**")
    st.caption(f"{perfil['role']} · {perfil['username']}")
    pagina = st.radio(
        "Sección",
        ["Consolidado", "Resumen", "Detalle de proyecto"],
        key="portal_page",
    )
    if st.button("Cerrar sesión", icon=":material/logout:", width="stretch"):
        try:
            solicitar_supabase("POST", "/auth/v1/logout", token=token)
        except PortalError:
            pass
        borrar_sesion()
        st.rerun()

try:
    proyectos = cargar_tabla(
        "proyectos",
        token,
        "id,cluster,nombre,municipio,departamento,direccion,latitud,longitud,coord_conexion,area,capacidad_kw,estado_general",
        {"estado_general": "neq.DESCARTADO", "order": "cluster.asc,nombre.asc"},
    )
except PortalError as error:
    st.error(str(error), title="No se pudieron cargar los proyectos")
    st.stop()

if pagina == "Consolidado":
    mostrar_consolidado(proyectos)
elif pagina == "Resumen":
    mostrar_dashboard(proyectos)
else:
    mostrar_detalle(proyectos, token)