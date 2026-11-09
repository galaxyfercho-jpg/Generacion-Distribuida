import hashlib
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from web_dashboard import calcular_avance_por_cluster, crear_grafico_avance


st.set_page_config(page_title="Portafolio GD", page_icon=":material/solar_power:", layout="wide")
PORTAFOLIO_REFRESH_INTERVAL = "30s"
LOGO_PATH = Path(__file__).with_name("logo_INGEV.png")

st.markdown(
    """
    <style>
    :root {
        --gd-navy: #154360;
        --gd-blue: #2874a6;
        --gd-green: #63a63a;
        --gd-ink: #263746;
        --gd-muted: #687b89;
        --gd-surface: #ffffff;
        --gd-canvas: #f3f6f8;
    }

    [data-testid="stAppViewContainer"] {
        background: var(--gd-canvas);
    }

    [data-testid="stHeader"] {
        background: transparent;
    }

    [data-testid="stMainBlockContainer"] {
        max-width: 1440px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #154360 0%, #1d5b79 100%);
    }

    [data-testid="stSidebar"] [data-testid="stImage"] {
        background: #ffffff;
        border-radius: 12px;
        padding: 8px;
        margin-bottom: 0.75rem;
    }

    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        color: #f5f8fa;
    }

    [data-testid="stSidebar"] [data-testid="stRadio"] label {
        border-radius: 8px;
        padding: 0.25rem 0.4rem;
    }

    [data-testid="stMetric"] {
        background: var(--gd-surface);
        border: 1px solid #dfe7ec;
        border-radius: 12px;
        padding: 1rem 1.1rem;
        box-shadow: 0 2px 8px rgba(21, 67, 96, 0.04);
    }

    [data-testid="stMetricLabel"] {
        color: var(--gd-muted);
    }

    [data-testid="stMetricValue"] {
        color: var(--gd-navy);
        font-weight: 700;
    }

    [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: #dfe7ec;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(21, 67, 96, 0.035);
    }

    [data-testid="stBaseButton-primary"] {
        background: var(--gd-blue);
        border-color: var(--gd-blue);
    }

    @media (max-width: 700px) {
        [data-testid="stMainBlockContainer"] {
            padding: 1rem 1rem 2rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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


def mostrar_encabezado(titulo: str, descripcion: str, perfil: dict | None = None):
    with st.container(border=True):
        logo, nombre, usuario = st.columns([0.75, 3.2, 1.5], vertical_alignment="center")
        if LOGO_PATH.is_file():
            logo.image(str(LOGO_PATH), width=112)
        else:
            logo.markdown("## **INGEV**")
        nombre.markdown(
            f"<div style='color:#154360;font-size:1.75rem;font-weight:750;"
            f"line-height:1.15'>{titulo}</div>"
            f"<div style='color:#687b89;margin-top:.35rem'>{descripcion}</div>",
            unsafe_allow_html=True,
        )
        if perfil:
            usuario.markdown(f"**{perfil.get('display_name', 'Usuario')}**")
            usuario.caption(f"{perfil.get('role', '')} · {perfil.get('username', '')}")


def mostrar_login():
    mostrar_encabezado(
        "Gestor de proyectos GD",
        "Generación distribuida · Portafolio de consulta",
    )
    bienvenida, acceso = st.columns([1.15, 1], gap="large")
    with bienvenida.container(border=True):
        st.markdown("### Bienvenido")
        st.write(
            "Consulta el avance de los proyectos, sus requisitos y la capacidad "
            "del portafolio desde un solo lugar."
        )
        st.divider()
        st.markdown("**Una vista clara para el seguimiento diario**")
        st.markdown(
            "- Avance de requisitos por clúster\n"
            "- Información y capacidad por proyecto\n"
            "- Actualización automática cada 30 segundos"
        )
    with acceso.container(border=True):
        st.markdown("### Iniciar sesión")
        st.caption("Usa el mismo usuario y contraseña de la aplicación.")
        with st.form("login_form"):
            usuario = st.text_input("Usuario", autocomplete="username")
            password = st.text_input("Contraseña", type="password", autocomplete="current-password")
            enviar = st.form_submit_button(
                "Ingresar al portafolio",
                type="primary",
                width="stretch",
                icon=":material/login:",
            )
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
    st.caption("Explora el portafolio por clúster y abre cada proyecto para consultar sus requisitos.")
    if proyectos.empty:
        st.info("No hay proyectos disponibles para esta cuenta.")
        return

    proyectos = proyectos.copy()
    proyectos["cluster"] = proyectos["cluster"].fillna("").astype(str).str.strip()
    proyectos.loc[
        proyectos["cluster"].str.casefold().isin({"", "n/a", "individual"}),
        "cluster",
    ] = "Proyectos individuales"
    with st.container(border=True):
        st.markdown("**Filtros del portafolio**")
        filtro_col, estado_col, busqueda_col = st.columns([1, 1, 1.4])
        filtro_cluster = filtro_col.selectbox(
            "Clúster",
            ["Todos"] + sorted(proyectos["cluster"].unique().tolist()),
        )
        filtro_estado = estado_col.selectbox(
            "Estado",
            ["Todos"] + sorted(proyectos["estado_general"].fillna("Sin estado").unique().tolist()),
        )
        busqueda = busqueda_col.text_input("Buscar proyecto o municipio", type="search")

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

    st.caption(f"Mostrando **{len(filtrados)}** de {len(proyectos)} proyectos")
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
            expanded=False,
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


def mostrar_dashboard(proyectos: pd.DataFrame, requisitos: pd.DataFrame):
    st.caption("Indicadores clave y avance de requisitos aplicables en cada agrupación.")
    if proyectos.empty:
        st.info("No hay proyectos disponibles para calcular indicadores.")
        return

    datos = proyectos.copy()
    datos["capacidad_kw"] = pd.to_numeric(datos["capacidad_kw"], errors="coerce").fillna(0)
    datos["area"] = pd.to_numeric(datos["area"], errors="coerce").fillna(0)
    datos["cluster"] = datos["cluster"].fillna("").astype(str).str.strip()
    total_capacidad = datos["capacidad_kw"].sum()
    total_area = datos["area"].sum()
    datos["cluster"] = datos["cluster"].fillna("").astype(str).str.strip()
    datos.loc[
        datos["cluster"].str.casefold().isin({"", "n/a", "individual"}),
        "cluster",
    ] = "Proyectos individuales"
    clusters_reales = datos.loc[
        datos["cluster"] != "Proyectos individuales", "cluster"
    ].nunique()

    with st.container(horizontal=True):
        st.metric("Proyectos", f"{len(datos):,}", border=True)
        st.metric("Capacidad total", f"{total_capacidad:,.0f} kW", border=True)
        st.metric("Área total", f"{total_area:,.1f} ha", border=True)
        st.metric("Clústeres", f"{clusters_reales:,}", border=True)

    avance = calcular_avance_por_cluster(datos, requisitos)
    with st.container(border=True):
        titulo, ayuda = st.columns([2, 1], vertical_alignment="center")
        titulo.markdown("### Avance por clúster")
        ayuda.caption("Porcentaje de requisitos aplicables completados · ordenado de mayor a menor")
        if avance.empty:
            st.info("No hay requisitos aplicables para construir el gráfico.")
            return

        st.altair_chart(
            crear_grafico_avance(avance),
            width="stretch",
            theme=None,
        )
        st.caption(
            "Cada barra representa requisitos completados ÷ requisitos aplicables. "
            "La cifra al final muestra completados/total. Los proyectos pausados y "
            "descartados no afectan el avance; los proyectos individuales se agrupan "
            "en una sola barra."
        )


def mostrar_detalle(proyectos: pd.DataFrame, token: str):
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


@st.fragment(run_every=PORTAFOLIO_REFRESH_INTERVAL)
def mostrar_portafolio_actualizado(pagina: str, perfil: dict) -> None:
    token_actual = obtener_token_vigente()
    if not token_actual:
        st.rerun()

    st.caption("Los datos se actualizan automáticamente cada 30 segundos.")
    try:
        proyectos = cargar_tabla(
            "proyectos",
            token_actual,
            "id,cluster,nombre,municipio,departamento,direccion,latitud,longitud,coord_conexion,circuito,radicado,area,capacidad_kw,estado_general,req_servidumbre,req_contrato",
            {"estado_general": "neq.DESCARTADO", "order": "cluster.asc,nombre.asc"},
        )
    except PortalError as error:
        proyectos = st.session_state.get("portal_cached_projects")
        if proyectos is None:
            st.error(str(error), title="No se pudieron cargar los proyectos")
            return
        st.warning(
            f"No se pudo actualizar; se muestran los últimos datos cargados. {error}"
        )
    else:
        st.session_state["portal_cached_projects"] = proyectos

    titulos = {
        "Resumen": ("Resumen del portafolio", "Indicadores y avance del portafolio"),
        "Consolidado": ("Consolidado de proyectos", "Proyectos agrupados por clúster"),
        "Detalle de proyecto": ("Detalle de proyecto", "Información y requisitos"),
        "Gestor de soportes": ("Gestor de soportes", "Repositorio documental"),
    }
    titulo, descripcion = titulos.get(
        pagina,
        ("Gestor de proyectos GD", "Consulta del portafolio de generación distribuida"),
    )
    mostrar_encabezado(titulo, descripcion, perfil)

    requisitos_resumen = st.session_state.get("portal_cached_requirements")
    if pagina in {"Consolidado", "Resumen"}:
        try:
            requisitos_resumen = cargar_tabla(
                "requisitos",
                token_actual,
                "proyecto_id,categoria,estado",
            )
        except PortalError as error:
            requisitos_resumen = st.session_state.get(
                "portal_cached_requirements"
            )
            if requisitos_resumen is None:
                st.error(str(error), title="No se pudieron cargar los requisitos")
                return
            st.warning(
                f"No se pudieron actualizar los requisitos; "
                f"se muestran los últimos datos cargados. {error}"
            )
        else:
            st.session_state["portal_cached_requirements"] = requisitos_resumen

    if pagina == "Consolidado":
        mostrar_consolidado(proyectos, requisitos_resumen)
    elif pagina == "Resumen":
        mostrar_dashboard(proyectos, requisitos_resumen)
    elif pagina == "Detalle de proyecto":
        mostrar_detalle(proyectos, token_actual)
    else:
        mostrar_repositorio_documental_pendiente()


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
    if LOGO_PATH.is_file():
        st.image(str(LOGO_PATH), width=180)
    st.markdown("### Portafolio GD")
    st.caption("Generación distribuida")
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

mostrar_portafolio_actualizado(pagina, perfil)