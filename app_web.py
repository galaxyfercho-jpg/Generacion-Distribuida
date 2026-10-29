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
        if endpoint == "/auth/v1/token" and response.status_code in (400, 401):
            raise PortalError(
                "Supabase no aceptó esas credenciales. Verifica usuario y contraseña, "
                "y confirma que ejecutaste la migración de usuarios a Supabase Auth."
            )
        if endpoint == "/rest/v1/web_profiles" and response.status_code == 400:
            raise PortalError(
                "Supabase no reconoce web_profiles. Ejecuta supabase/schema.sql "
                "en el SQL Editor del proyecto."
            )
        if endpoint.startswith("/rest/v1/") and response.status_code in (400, 401, 403, 404):
            raise PortalError(
                "Supabase rechazó la lectura de datos. Verifica que ejecutaste "
                "supabase/schema.sql y que las políticas RLS estén activas."
            )
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
    st.title("Gestor de proyectos")
    st.caption("Generación distribuida GD · Consulta web del portafolio")
    bienvenida, acceso = st.columns([1.2, 1], gap="large")
    with bienvenida.container(border=True):
        st.subheader("Bienvenido")
        st.write(
            "Consulta los proyectos, su avance y los requisitos registrados "
            "en el portafolio."
        )
        st.caption("Acceso seguro para usuarios habilitados.")
    with acceso.container(border=True):
        st.subheader("Iniciar sesión")
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


def mostrar_consolidado(proyectos: pd.DataFrame, requisitos: pd.DataFrame):
    st.subheader("Consolidado de proyectos")
    st.caption("Portafolio organizado por clúster, con avance y datos principales.")
    if proyectos.empty:
        st.info("No hay proyectos disponibles para esta cuenta.")
        return

    proyectos = proyectos.copy()
    proyectos["cluster"] = (
        proyectos["cluster"].fillna("Individual").replace(["", "N/A"], "Individual")
    )
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
            | filtrados["cluster"].fillna("").str.casefold().str.contains(termino, regex=False)
            | filtrados["radicado"].fillna("").str.casefold().str.contains(termino, regex=False)
            | filtrados["circuito"].fillna("").str.casefold().str.contains(termino, regex=False)
        )
        filtrados = filtrados[coincidencia]

    st.caption(f"{len(filtrados)} de {len(proyectos)} proyectos")
    if filtrados.empty:
        st.info("No hay proyectos que coincidan con los filtros seleccionados.")
        return

    requisitos = requisitos.copy()
    requisitos["categoria"] = requisitos["categoria"].fillna("")
    requisitos["estado"] = requisitos["estado"].fillna("")

    for cluster, proyectos_cluster in filtrados.groupby("cluster", sort=True, dropna=False):
        nombre_cluster = cluster or "Individual"
        capacidad_cluster = pd.to_numeric(
            proyectos_cluster["capacidad_kw"], errors="coerce"
        ).fillna(0).sum()
        with st.expander(
            f"{nombre_cluster} · {len(proyectos_cluster)} proyectos · "
            f"{capacidad_cluster:,.0f} kW",
            expanded=True,
        ):
            for _, proyecto in proyectos_cluster.iterrows():
                proyecto_id = int(proyecto["id"])
                avance = requisitos[requisitos["proyecto_id"] == proyecto_id].copy()
                avance = avance[
                    ~avance["categoria"].isin(["Ingeniería Básica", "Análisis Técnico"])
                ]
                if not proyecto.get("req_servidumbre"):
                    avance = avance[avance["categoria"] != "Servidumbre"]
                if not proyecto.get("req_contrato"):
                    avance = avance[avance["categoria"] != "Modelo de Contrato"]

                total = len(avance)
                completados = int((avance["estado"] == "COMPLETADO").sum())
                pendientes = int((avance["estado"] == "PENDIENTE").sum())
                atendidos = total - completados - pendientes
                porcentaje = completados / total if total else 0

                with st.container(border=True):
                    titulo, estado = st.columns([3, 1])
                    titulo.markdown(f"#### {proyecto['nombre']}")
                    if proyecto.get("estado_general") and proyecto["estado_general"] != "ACTIVO":
                        estado.badge(str(proyecto["estado_general"]), color="orange")
                    municipio = proyecto.get("municipio") or "Sin municipio"
                    circuito = proyecto.get("circuito") or "Sin circuito"
                    st.caption(f"{municipio} · {proyecto.get('departamento') or 'Sin departamento'} · {circuito}")
                    st.progress(
                        porcentaje,
                        text=(
                            f"Avance: {porcentaje:.1%} · {completados} completos · "
                            f"{atendidos} atendidos · {pendientes} pendientes"
                        ),
                    )
                    datos = st.columns(3)
                    datos[0].metric("Capacidad", f"{float(proyecto.get('capacidad_kw') or 0):,.0f} kW")
                    datos[1].metric("Área", f"{float(proyecto.get('area') or 0):,.1f} ha")
                    datos[2].metric("Requisitos", total)
                    if st.button(
                        "Abrir proyecto",
                        key=f"open_project_{proyecto_id}",
                        icon=":material/open_in_new:",
                    ):
                        st.session_state["project_detail_id"] = proyecto_id
                        st.session_state["portal_page_v2"] = "Detalle de proyecto"
                        st.rerun()


def mostrar_dashboard(proyectos: pd.DataFrame):
    st.subheader("Resumen del portafolio")
    st.caption("Indicadores generales de los proyectos visibles en el sistema.")
    if proyectos.empty:
        st.info("No hay proyectos disponibles para calcular indicadores.")
        return

    datos = proyectos.copy()
    datos["capacidad_kw"] = pd.to_numeric(datos["capacidad_kw"], errors="coerce").fillna(0)
    datos["area"] = pd.to_numeric(datos["area"], errors="coerce").fillna(0)
    datos["cluster"] = datos["cluster"].fillna("Individual").replace("", "Individual")
    total_capacidad = datos["capacidad_kw"].sum()
    total_area = datos["area"].sum()

    total_col, capacidad_col, area_col, clusters_col = st.columns(4)
    total_col.metric("Proyectos", f"{len(datos):,}")
    capacidad_col.metric("Capacidad total", f"{total_capacidad:,.0f} kW")
    area_col.metric("Área total", f"{total_area:,.1f} ha")
    clusters_col.metric("Clústeres", datos["cluster"].nunique())

    por_cluster = (
        datos.groupby("cluster", as_index=False)["capacidad_kw"]
        .sum()
        .sort_values("capacidad_kw", ascending=False)
    )
    st.subheader("Capacidad por clúster")
    st.bar_chart(por_cluster, x="cluster", y="capacidad_kw", alt="Capacidad instalada agrupada por clúster")


def mostrar_detalle(proyectos: pd.DataFrame, token: str):
    st.subheader("Detalle de proyecto")
    st.caption("Información general y requisitos del proyecto seleccionado.")
    if proyectos.empty:
        st.info("No hay proyectos disponibles.")
        return

    opciones = {
        int(fila["id"]): f"{fila['nombre']} · {fila.get('municipio') or 'Sin municipio'} · {fila.get('cluster') or 'Individual'}"
        for _, fila in proyectos.iterrows()
    }
    proyecto_id = st.selectbox(
        "Proyecto",
        list(opciones),
        format_func=lambda value: opciones[value],
        key="project_detail_id",
    )
    proyecto = proyectos.loc[proyectos["id"] == proyecto_id].iloc[0]
    st.markdown(f"### {proyecto['nombre']}")
    metricas = st.columns(3)
    metricas[0].metric("Capacidad", f"{float(proyecto.get('capacidad_kw') or 0):,.0f} kW")
    metricas[1].metric("Área", f"{float(proyecto.get('area') or 0):,.1f} ha")
    metricas[2].badge(str(proyecto.get("estado_general") or "Sin estado"), color="blue")
    with st.container(border=True):
        izquierda, derecha = st.columns(2)
        izquierda.markdown("**Ubicación**")
        izquierda.write(f"**Clúster:** {proyecto.get('cluster') or 'Individual'}")
        izquierda.write(f"**Municipio:** {proyecto.get('municipio') or 'Sin municipio'}")
        izquierda.write(f"**Departamento:** {proyecto.get('departamento') or 'Sin departamento'}")
        izquierda.write(f"**Dirección:** {proyecto.get('direccion') or 'Sin dirección'}")
        derecha.markdown("**Datos técnicos**")
        derecha.write(f"**Latitud:** {proyecto.get('latitud') or '—'}")
        derecha.write(f"**Longitud:** {proyecto.get('longitud') or '—'}")
        derecha.write(f"**Coordenadas OR:** {proyecto.get('coord_conexion') or '—'}")
        derecha.write(f"**Circuito:** {proyecto.get('circuito') or '—'}")

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
        st.dataframe(
            requisitos,
            hide_index=True,
            alt="Requisitos y fechas del proyecto seleccionado",
            width="stretch",
        )


def mostrar_repositorio_documental_pendiente():
    st.subheader("Gestor de soportes")
    st.caption("Repositorio global de soportes documentales")
    with st.container(border=True):
        st.badge("En preparación", icon=":material/hourglass_top:", color="orange")
        st.markdown("### Conexión privada a los documentos pendiente")
        st.write(
            "Los adjuntos actuales están vinculados a rutas locales del equipo de escritorio. "
            "El portal no puede abrir esas rutas. La conexión con SharePoint todavía requiere "
            "acceso aprobado por el administrador de Microsoft 365."
        )
        st.info(
            "No se han creado enlaces públicos ni se han subido documentos. "
            "Cuando se habilite el acceso privado, aquí podrás filtrar los soportes por "
            "clúster, proyecto y tipo de evidencia."
        )


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
    st.markdown("## Gestor GD")
    st.caption("Generación distribuida")
    st.markdown("**Módulos de consulta**")
    pagina = st.radio(
        "Sección",
        ["Resumen", "Consolidado", "Detalle de proyecto", "Gestor de soportes"],
        key="portal_page_v2",
        label_visibility="collapsed",
    )
    st.caption(f"Sesión: {perfil['display_name']} · {perfil['role']}")
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
        "id,cluster,nombre,municipio,departamento,direccion,latitud,longitud,coord_conexion,circuito,radicado,area,capacidad_kw,estado_general,req_servidumbre,req_contrato",
        {"estado_general": "neq.DESCARTADO", "order": "cluster.asc,nombre.asc"},
    )
except PortalError as error:
    st.error(str(error), title="No se pudieron cargar los proyectos")
    st.stop()

with st.container(border=True):
    encabezado, usuario = st.columns([3, 1])
    encabezado.markdown("### Gestor de proyectos GD")
    encabezado.caption("Consulta del portafolio de generación distribuida")
    usuario.markdown(f"**{perfil['display_name']}**")
    usuario.caption(f"{perfil['role']} · {perfil['username']}")

if pagina == "Consolidado":
    try:
        requisitos_resumen = cargar_tabla(
            "requisitos",
            token,
            "proyecto_id,categoria,estado",
        )
    except PortalError as error:
        st.error(str(error), title="No se pudieron cargar los requisitos")
        st.stop()
    mostrar_consolidado(proyectos, requisitos_resumen)
elif pagina == "Resumen":
    mostrar_dashboard(proyectos)
elif pagina == "Detalle de proyecto":
    mostrar_detalle(proyectos, token)
else:
    mostrar_repositorio_documental_pendiente()