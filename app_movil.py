from __future__ import annotations

import asyncio
import hashlib
import os
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import flet as ft
import requests


ROOT = Path(__file__).resolve().parent
PROJECT_COLUMNS = (
    "id,cluster,nombre,municipio,departamento,direccion,latitud,longitud,"
    "coord_conexion,circuito,radicado,area,capacidad_kw,estado_general,"
    "req_servidumbre,req_contrato,num_paneles,pot_panel,num_inversores"
)
REQUIREMENT_COLUMNS = (
    "categoria,descripcion,entidad,estado,fecha_radicacion,fecha_limite,"
    "fecha_final,observaciones"
)
SECTIONS = ("Resumen", "Proyectos")


class PortalError(RuntimeError):
    pass


@dataclass
class MobileSession:
    access_token: str
    refresh_token: str
    expires_at: float
    profile: dict[str, Any]


def correo_interno(usuario: str) -> str:
    digest = hashlib.sha256(usuario.strip().encode("utf-8")).hexdigest()
    return f"u{digest}@login.gestor-gd.invalid"


def valor_numerico(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def flag_activo(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().casefold() in {"1", "true", "sí", "si", "yes"}


def calcular_indicadores(
    proyectos: list[dict[str, Any]],
    requisitos: list[dict[str, Any]],
) -> dict[str, Any]:
    requisitos_por_proyecto: dict[int, list[dict[str, Any]]] = {}
    for requisito in requisitos:
        try:
            proyecto_id = int(requisito["proyecto_id"])
        except (KeyError, TypeError, ValueError):
            continue
        requisitos_por_proyecto.setdefault(proyecto_id, []).append(requisito)

    clusters: dict[str, dict[str, int]] = {}
    estados_validos: list[str] = []
    clusters_activos: set[str] = set()
    capacidad_ejecutada = 0.0
    capacidad_proyectada = 0.0
    area_ejecutada = 0.0
    area_proyectada = 0.0
    proyectos_ejecutados = 0
    proyectos_proyectados = 0
    proyectos_descartados = 0

    for proyecto in proyectos:
        estado_general = str(proyecto.get("estado_general") or "").strip().upper()
        if estado_general == "DESCARTADO":
            proyectos_descartados += 1
            continue

        cluster = str(proyecto.get("cluster") or "").strip()
        cluster = cluster if cluster and cluster.upper() != "N/A" else "Individual"
        clusters_activos.add(cluster)

        proyecto_id = int(proyecto["id"])
        requisitos_validos: list[dict[str, Any]] = []
        for requisito in requisitos_por_proyecto.get(proyecto_id, []):
            categoria = str(requisito.get("categoria") or "").strip()
            if categoria in {"Ingeniería Básica", "Análisis Técnico"}:
                continue
            if categoria == "Servidumbre" and not flag_activo(proyecto.get("req_servidumbre")):
                continue
            if categoria == "Modelo de Contrato" and not flag_activo(proyecto.get("req_contrato")):
                continue
            requisitos_validos.append(requisito)

        estados_proyecto = [
            str(requisito.get("estado") or "").strip().upper()
            for requisito in requisitos_validos
        ]
        estados_validos.extend(estados_proyecto)
        capacidad = valor_numerico(proyecto.get("capacidad_kw"))
        area = valor_numerico(proyecto.get("area"))

        if requisitos_validos and all(estado == "COMPLETADO" for estado in estados_proyecto):
            capacidad_ejecutada += capacidad
            area_ejecutada += area
            proyectos_ejecutados += 1
        else:
            capacidad_proyectada += capacidad
            area_proyectada += area
            proyectos_proyectados += 1

        cluster_stats = clusters.setdefault(cluster, {"total": 0, "completados": 0})
        cluster_stats["total"] += len(estados_proyecto)
        cluster_stats["completados"] += sum(
            estado == "COMPLETADO" for estado in estados_proyecto
        )

    total_requisitos = len(estados_validos)
    completados = estados_validos.count("COMPLETADO")
    pendientes = estados_validos.count("PENDIENTE")
    en_proceso = sum(
        estado in {"RADICADO", "EN TRÁMITE", "EN SUBSANACIONES"}
        for estado in estados_validos
    )
    alertas = sum(estado in {"VENCIDO", "REITERADO"} for estado in estados_validos)

    return {
        "proyectos_total": len(proyectos),
        "proyectos_ejecutados": proyectos_ejecutados,
        "proyectos_proyectados": proyectos_proyectados,
        "proyectos_descartados": proyectos_descartados,
        "clusters_total": len(clusters_activos),
        "capacidad_ejecutada": capacidad_ejecutada,
        "capacidad_proyectada": capacidad_proyectada,
        "area_ejecutada": area_ejecutada,
        "area_proyectada": area_proyectada,
        "requisitos_total": total_requisitos,
        "requisitos_completados": completados,
        "requisitos_en_proceso": en_proceso,
        "requisitos_alertas": alertas,
        "requisitos_pendientes": pendientes,
        "requisitos_atendidos": total_requisitos - completados - pendientes,
        "eficiencia": completados / total_requisitos if total_requisitos else 0.0,
        "avance_clusters": [
            {
                "nombre": nombre,
                "total": stats["total"],
                "completados": stats["completados"],
                "avance": stats["completados"] / stats["total"] if stats["total"] else 0.0,
            }
            for nombre, stats in sorted(clusters.items())
            if stats["total"]
        ],
    }


def cargar_configuracion() -> tuple[str, str]:
    try:
        import mobile_config
    except ModuleNotFoundError as error:
        if error.name != "mobile_config":
            raise
        mobile_config = None

    if mobile_config:
        url = getattr(mobile_config, "SUPABASE_URL", "")
        anon_key = getattr(mobile_config, "SUPABASE_ANON_KEY", "")
    else:
        url = os.environ.get("SUPABASE_URL", "")
        anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
        secrets_path = ROOT / ".streamlit" / "secrets.toml"
        if not url or not anon_key:
            try:
                supabase = tomllib.loads(secrets_path.read_text(encoding="utf-8")).get(
                    "supabase", {}
                )
            except FileNotFoundError:
                supabase = {}
            except tomllib.TOMLDecodeError as error:
                raise PortalError("El archivo local de configuración Supabase no es válido.") from error
            except OSError as error:
                raise PortalError("No se pudo leer la configuración local de Supabase.") from error
            url = url or supabase.get("url", "")
            anon_key = anon_key or supabase.get("anon_key", "")

    if not url or not anon_key:
        raise PortalError(
            "Falta la configuración pública de Supabase. Genera el paquete móvil "
            "desde el proyecto configurado."
        )
    if not url.startswith("https://"):
        raise PortalError("La URL de Supabase debe usar HTTPS.")
    return url.rstrip("/"), anon_key


class SupabaseClient:
    def __init__(self, base_url: str, anon_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.anon_key = anon_key
        self.session: MobileSession | None = None

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        token: str | None = None,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        headers = {"apikey": self.anon_key}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = requests.request(
                method,
                f"{self.base_url}{endpoint}",
                headers=headers,
                params=params,
                json=payload,
                timeout=(8, 25),
            )
        except requests.RequestException as error:
            raise PortalError(
                "No se pudo conectar con Supabase. Verifica tu conexión a internet."
            ) from error

        if not response.ok:
            if endpoint == "/auth/v1/token" and response.status_code in (400, 401):
                if params and params.get("grant_type") == "refresh_token":
                    self.session = None
                    raise PortalError("La sesión expiró. Inicia sesión de nuevo.")
                raise PortalError("Usuario o contraseña incorrectos.")
            if endpoint == "/rest/v1/web_profiles" and response.status_code == 400:
                raise PortalError(
                    "Supabase no reconoce web_profiles. Ejecuta supabase/schema.sql."
                )
            if endpoint.startswith("/rest/v1/") and response.status_code in (
                400,
                401,
                403,
                404,
            ):
                raise PortalError(
                    "Supabase rechazó la consulta. Verifica el esquema y las políticas RLS."
                )
            raise PortalError(
                f"El servicio de datos respondió con el código {response.status_code}."
            )

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise PortalError("Supabase devolvió una respuesta no válida.") from error

    def iniciar_sesion(self, usuario: str, password: str) -> dict[str, Any]:
        auth = self._request(
            "POST",
            "/auth/v1/token",
            params={"grant_type": "password"},
            payload={"email": correo_interno(usuario), "password": password},
        )
        if not isinstance(auth, dict):
            raise PortalError("Supabase devolvió una respuesta de autenticación no válida.")
        user = auth.get("user")
        access_token = auth.get("access_token")
        refresh_token = auth.get("refresh_token")
        if not isinstance(user, dict) or not user.get("id") or not access_token or not refresh_token:
            raise PortalError("No se pudo completar el inicio de sesión.")

        perfiles = self._request(
            "GET",
            "/rest/v1/web_profiles",
            token=access_token,
            params={
                "select": "auth_user_id,username,display_name,role,enabled",
                "auth_user_id": f"eq.{user['id']}",
                "limit": "1",
            },
        )
        if not isinstance(perfiles, list) or not perfiles or not perfiles[0].get("enabled"):
            raise PortalError("La cuenta no está habilitada para consultar el portal.")

        self.session = MobileSession(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.monotonic() + int(auth.get("expires_in", 3600)),
            profile=perfiles[0],
        )
        return perfiles[0]

    def cerrar_sesion(self) -> None:
        session = self.session
        if session is None:
            return
        try:
            self._request(
                "POST",
                "/auth/v1/logout",
                token=self._token_vigente(),
            )
        finally:
            self.session = None

    def _token_vigente(self) -> str:
        if self.session is None:
            raise PortalError("La sesión terminó. Inicia sesión de nuevo.")
        if self.session.expires_at - time.monotonic() > 60:
            return self.session.access_token

        auth = self._request(
            "POST",
            "/auth/v1/token",
            params={"grant_type": "refresh_token"},
            payload={"refresh_token": self.session.refresh_token},
        )
        if not isinstance(auth, dict) or not auth.get("access_token"):
            self.session = None
            raise PortalError("La sesión expiró. Inicia sesión de nuevo.")
        self.session.access_token = auth["access_token"]
        self.session.refresh_token = auth.get("refresh_token", self.session.refresh_token)
        self.session.expires_at = time.monotonic() + int(auth.get("expires_in", 3600))
        return self.session.access_token

    def cargar_proyectos(self) -> list[dict[str, Any]]:
        return self._cargar_paginas(
            "proyectos",
            PROJECT_COLUMNS,
            {"order": "cluster.asc,nombre.asc"},
        )

    def cargar_requisitos_globales(self) -> list[dict[str, Any]]:
        return self._cargar_paginas(
            "requisitos",
            "proyecto_id,categoria,estado",
            {"order": "proyecto_id.asc"},
        )

    def cargar_requisitos(self, proyecto_id: int) -> list[dict[str, Any]]:
        return self._cargar_paginas(
            "requisitos",
            REQUIREMENT_COLUMNS,
            {
                "proyecto_id": f"eq.{proyecto_id}",
                "order": "categoria.asc,descripcion.asc",
            },
        )

    def _cargar_paginas(
        self,
        tabla: str,
        columnas: str,
        filtros: dict[str, str],
    ) -> list[dict[str, Any]]:
        page_size = 1000
        offset = 0
        registros: list[dict[str, Any]] = []
        while True:
            pagina = self._request(
                "GET",
                f"/rest/v1/{tabla}",
                token=self._token_vigente(),
                params={
                    "select": columnas,
                    **filtros,
                    "limit": str(page_size),
                    "offset": str(offset),
                },
            )
            if not isinstance(pagina, list):
                raise PortalError(f"Supabase devolvió datos no válidos para {tabla}.")
            registros.extend(pagina)
            if len(pagina) < page_size:
                return registros
            offset += len(pagina)


def main(page: ft.Page) -> None:
    page.title = "Gestor GD"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = "#f4f6f9"
    page.padding = 0

    try:
        base_url, anon_key = cargar_configuracion()
        client = SupabaseClient(base_url, anon_key)
    except PortalError as error:
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.CLOUD_OFF, size=56, color=ft.Colors.BLUE_GREY_500),
                        ft.Text("Gestor de proyectos GD", size=24, weight=ft.FontWeight.BOLD),
                        ft.Text(str(error), text_align=ft.TextAlign.CENTER),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                expand=True,
                alignment=ft.Alignment(0, 0),
                padding=24,
            )
        )
        return

    projects: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    search_value = ""
    content = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=12)
    navigation = ft.NavigationBar(
        selected_index=0,
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.DASHBOARD_OUTLINED, label="Resumen"),
            ft.NavigationBarDestination(icon=ft.Icons.FOLDER_OUTLINED, label="Proyectos"),
        ],
    )
    current_view = "Resumen"

    def show_message(message: str, *, error: bool = False) -> None:
        page.show_dialog(
            ft.AlertDialog(
                title=ft.Text("No se pudo completar la operación" if error else "Aviso"),
                content=ft.Text(message),
                actions=[
                    ft.TextButton("Cerrar", on_click=lambda _: page.pop_dialog())
                ],
            )
        )

    def metric_card(
        title: str,
        value: str,
        detail: str,
        color: str,
    ) -> ft.Card:
        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(title, size=13, color=ft.Colors.BLUE_GREY_700),
                        ft.Text(value, size=23, weight=ft.FontWeight.BOLD, color=color),
                        ft.Text(detail, size=11, color=ft.Colors.BLUE_GREY_600),
                    ],
                    spacing=5,
                    tight=True,
                ),
                padding=14,
                expand=True,
            ),
            elevation=1,
            expand=True,
        )

    def chart_card(title: str, subtitle: str = "") -> ft.Container:
        controls = [ft.Text(title, size=17, weight=ft.FontWeight.BOLD, color="#154360")]
        if subtitle:
            controls.append(
                ft.Text(subtitle, size=11, color=ft.Colors.BLUE_GREY_600)
            )
        return ft.Container(
            content=ft.Column(controls, spacing=8),
            bgcolor=ft.Colors.WHITE,
            padding=14,
            border=ft.Border.all(1, "#d5d8dc"),
            border_radius=10,
        )

    def add_legend_row(
        controls: list[ft.Control],
        color: str,
        label: str,
        count: int,
        total: int,
    ) -> None:
        percent = count / total * 100 if total else 0
        controls.append(
            ft.Row(
                [
                    ft.Container(width=10, height=10, bgcolor=color, border_radius=5),
                    ft.Text(label, size=12, expand=True),
                    ft.Text(f"{count:,} · {percent:.0f}%", size=12, weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
            )
        )

    def render_content() -> None:
        content.controls.clear()
        if current_view == "Resumen":
            metrics = calcular_indicadores(projects, requirements)
            capacidad_total = (
                metrics["capacidad_ejecutada"] + metrics["capacidad_proyectada"]
            )
            area_total = metrics["area_ejecutada"] + metrics["area_proyectada"]
            activos = (
                metrics["proyectos_ejecutados"] + metrics["proyectos_proyectados"]
            )
            total_requisitos = metrics["requisitos_total"]

            content.controls.extend(
                [
                    ft.Text("Dashboard analítico", size=24, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        f"Portafolio actualizado desde Supabase · "
                        f"{metrics['proyectos_total']} proyectos registrados",
                        size=12,
                        color=ft.Colors.BLUE_GREY_600,
                    ),
                    ft.Row(
                        [
                            metric_card(
                                "Proyectos activos",
                                str(activos),
                                f"{metrics['proyectos_descartados']} descartados",
                                "#2980b9",
                            ),
                            metric_card(
                                "Clústeres activos",
                                str(metrics["clusters_total"]),
                                "Sin contar descartados",
                                "#8e44ad",
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Row(
                        [
                            metric_card(
                                "Capacidad ejecutada",
                                f"{metrics['capacidad_ejecutada']:,.0f} kW",
                                f"{metrics['proyectos_ejecutados']} proyectos completos",
                                "#27ae60",
                            ),
                            metric_card(
                                "Capacidad proyectada",
                                f"{metrics['capacidad_proyectada']:,.0f} kW",
                                f"{metrics['proyectos_proyectados']} proyectos en curso",
                                "#f39c12",
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        content=ft.Text(
                            "Criterio: un proyecto cuenta como ejecutado cuando todos sus "
                            "requisitos aplicables están COMPLETADOS, igual que en el "
                            "dashboard de escritorio. Es capacidad de proyectos, no una "
                            "medición de energía producida.",
                            size=11,
                            color=ft.Colors.BLUE_GREY_700,
                        ),
                        bgcolor="#eaf2f8",
                        padding=12,
                        border_radius=8,
                    ),
                ]
            )

            capacity_chart = chart_card(
                "Capacidad del portafolio",
                f"Total activo: {capacidad_total:,.0f} kW",
            )
            for label, amount, color in (
                (
                    "Ejecutada",
                    metrics["capacidad_ejecutada"],
                    "#27ae60",
                ),
                (
                    "Proyectada",
                    metrics["capacidad_proyectada"],
                    "#f39c12",
                ),
            ):
                fraction = amount / capacidad_total if capacidad_total else 0
                capacity_chart.content.controls.extend(
                    [
                        ft.Row(
                            [
                                ft.Text(label, size=12, expand=True),
                                ft.Text(f"{amount:,.0f} kW", size=12, weight=ft.FontWeight.BOLD),
                            ],
                            spacing=8,
                        ),
                        ft.ProgressBar(
                            value=fraction,
                            color=color,
                            bgcolor="#e5e8e8",
                            bar_height=10,
                        ),
                    ]
                )
            area_detail = (
                f"Área ejecutada: {metrics['area_ejecutada']:,.1f} ha · "
                f"Proyectada: {metrics['area_proyectada']:,.1f} ha · "
                f"Total: {area_total:,.1f} ha"
            )
            capacity_chart.content.controls.append(
                ft.Text(area_detail, size=11, color=ft.Colors.BLUE_GREY_700)
            )
            content.controls.append(capacity_chart)

            efficiency = metrics["eficiencia"]
            efficiency_chart = chart_card(
                "Eficiencia de requisitos",
                f"{efficiency:.1%} completados · {total_requisitos:,} requisitos aplicables",
            )
            efficiency_chart.content.controls.extend(
                [
                    ft.ProgressBar(
                        value=efficiency,
                        color="#27ae60",
                        bgcolor="#e5e8e8",
                        bar_height=12,
                    ),
                    ft.Text(
                        f"{metrics['requisitos_completados']:,} completados · "
                        f"{metrics['requisitos_atendidos']:,} atendidos · "
                        f"{metrics['requisitos_pendientes']:,} pendientes",
                        size=11,
                        color=ft.Colors.BLUE_GREY_700,
                    ),
                ]
            )
            content.controls.append(efficiency_chart)

            cluster_chart = chart_card(
                "Avance por clúster",
                "Porcentaje de requisitos completados por agrupación.",
            )
            if metrics["avance_clusters"]:
                for cluster in metrics["avance_clusters"]:
                    cluster_chart.content.controls.extend(
                        [
                            ft.Row(
                                [
                                    ft.Text(cluster["nombre"], size=12, expand=True),
                                    ft.Text(
                                        f"{cluster['avance']:.1%} · "
                                        f"{cluster['completados']}/{cluster['total']}",
                                        size=11,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.ProgressBar(
                                value=cluster["avance"],
                                color="#3498db",
                                bgcolor="#e5e8e8",
                                bar_height=9,
                            ),
                        ]
                    )
            else:
                cluster_chart.content.controls.append(
                    ft.Text("No hay requisitos aplicables para graficar.")
                )
            content.controls.append(cluster_chart)

            status_chart = chart_card(
                "Estado de los requisitos",
                f"{total_requisitos:,} requisitos activos en el portafolio.",
            )
            status_values = [
                ("Completados", metrics["requisitos_completados"], "#27ae60"),
                ("En proceso", metrics["requisitos_en_proceso"], "#3498db"),
                ("Alertas / vencidos", metrics["requisitos_alertas"], "#e74c3c"),
                ("Pendientes", metrics["requisitos_pendientes"], "#7f8c8d"),
            ]
            segments = [
                ft.Container(
                    expand=count,
                    height=14,
                    bgcolor=color,
                    tooltip=f"{label}: {count}",
                )
                for label, count, color in status_values
                if count > 0
            ]
            if segments:
                status_chart.content.controls.append(
                    ft.Row(segments, spacing=2, height=14)
                )
            else:
                status_chart.content.controls.append(
                    ft.Text("No hay requisitos activos para graficar.")
                )
            for label, count, color in status_values:
                add_legend_row(
                    status_chart.content.controls,
                    color,
                    label,
                    count,
                    total_requisitos,
                )
            content.controls.append(status_chart)
            content.controls.append(
                ft.Text(
                    "Los datos se consultan en línea. Los cambios hechos en el escritorio "
                    "solo aparecen después de sincronizarlos con Supabase.",
                    size=11,
                    color=ft.Colors.BLUE_GREY_600,
                )
            )
        else:
            buscador = ft.TextField(
                label="Buscar proyecto, municipio o clúster",
                prefix_icon=ft.Icons.SEARCH,
                value=search_value,
                on_change=buscar_proyectos,
            )
            content.controls.extend(
                [
                    ft.Text("Proyectos", size=24, weight=ft.FontWeight.BOLD),
                    buscador,
                ]
            )
            termino = search_value.strip().casefold()
            filtrados = [
                project
                for project in projects
                if str(project.get("estado_general") or "").strip().upper() != "DESCARTADO"
                if not termino
                or termino
                in " ".join(
                    str(project.get(key) or "")
                    for key in ("nombre", "municipio", "cluster", "radicado", "circuito")
                ).casefold()
            ]
            if not filtrados:
                content.controls.append(ft.Text("No hay proyectos que coincidan con la búsqueda."))
            for project in filtrados:
                cluster = (project.get("cluster") or "").strip() or "Individual"
                estado = project.get("estado_general") or "Sin estado"
                subtitulo = " · ".join(
                    part
                    for part in (project.get("municipio") or "Sin municipio", cluster, estado)
                    if part
                )
                content.controls.append(
                    ft.Card(
                        content=ft.ListTile(
                            leading=ft.Icon(ft.Icons.SOLAR_POWER, color=ft.Colors.BLUE_700),
                            title=ft.Text(str(project.get("nombre") or "Proyecto sin nombre")),
                            subtitle=ft.Text(
                                f"{subtitulo}\n"
                                f"{float(project.get('capacidad_kw') or 0):,.0f} kW"
                            ),
                            is_three_line=True,
                            trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT),
                            on_click=crear_manejador_detalle(project),
                        ),
                        elevation=1,
                    )
                )
        page.update()

    def crear_manejador_detalle(
        project: dict[str, Any],
    ) -> Any:
        async def abrir_seleccionado(_: ft.ControlEvent) -> None:
            await abrir_detalle(project)

        return abrir_seleccionado

    def buscar_proyectos(event: ft.ControlEvent) -> None:
        nonlocal search_value
        search_value = event.control.value or ""
        render_content()

    async def abrir_detalle(project: dict[str, Any]) -> None:
        content.controls.clear()
        content.controls.append(
            ft.Row(
                [
                    ft.ProgressRing(width=22, height=22),
                    ft.Text("Cargando requisitos…"),
                ]
            )
        )
        page.navigation_bar = None
        page.appbar = ft.AppBar(
            leading=ft.IconButton(
                icon=ft.Icons.ARROW_BACK,
                on_click=lambda _: volver_a_proyectos(),
            ),
            title=ft.Text(str(project.get("nombre") or "Detalle del proyecto")),
            bgcolor="#154360",
            color=ft.Colors.WHITE,
        )
        page.update()

        try:
            requisitos = await asyncio.to_thread(
                client.cargar_requisitos, int(project["id"])
            )
        except PortalError as error:
            if client.session is None:
                render_login()
            else:
                show_message(str(error), error=True)
                volver_a_proyectos()
            return

        content.controls.clear()
        content.controls.append(
            ft.Text(str(project.get("nombre") or "Proyecto"), size=24, weight=ft.FontWeight.BOLD)
        )
        content.controls.append(
            ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(f"Clúster: {project.get('cluster') or 'Individual'}"),
                            ft.Text(f"Estado: {project.get('estado_general') or 'Sin estado'}"),
                            ft.Text(
                                f"Ubicación: {project.get('municipio') or 'Sin municipio'}, "
                                f"{project.get('departamento') or '—'}"
                            ),
                            ft.Text(f"Dirección: {project.get('direccion') or '—'}"),
                            ft.Text(f"Circuito: {project.get('circuito') or '—'}"),
                            ft.Text(
                                f"Capacidad: {float(project.get('capacidad_kw') or 0):,.0f} kW"
                            ),
                            ft.Text(f"Área: {float(project.get('area') or 0):,.1f} ha"),
                            ft.Text(f"Radicado: {project.get('radicado') or '—'}"),
                        ],
                        spacing=8,
                    ),
                    padding=16,
                ),
                elevation=1,
            )
        )
        content.controls.append(
            ft.Text(f"Requisitos ({len(requisitos)})", size=20, weight=ft.FontWeight.BOLD)
        )
        if not requisitos:
            content.controls.append(ft.Text("Este proyecto no tiene requisitos registrados."))
        for requirement in requisitos:
            estado = requirement.get("estado") or "Sin estado"
            color = (
                ft.Colors.GREEN_700
                if estado == "COMPLETADO"
                else ft.Colors.ORANGE_800
                if estado == "PENDIENTE"
                else ft.Colors.BLUE_GREY_700
            )
            fechas = " · ".join(
                str(requirement[key])
                for key in ("fecha_radicacion", "fecha_limite", "fecha_final")
                if requirement.get(key)
            )
            content.controls.append(
                ft.Card(
                    content=ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(
                                            str(requirement.get("descripcion") or "Requisito"),
                                            expand=True,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Text(estado, color=color, size=12),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                ft.Text(
                                    " · ".join(
                                        str(value)
                                        for value in (
                                            requirement.get("categoria"),
                                            requirement.get("entidad"),
                                        )
                                        if value
                                    ),
                                    size=12,
                                    color=ft.Colors.BLUE_GREY_700,
                                ),
                                ft.Text(fechas, size=12) if fechas else ft.Container(),
                                ft.Text(
                                    str(requirement["observaciones"]),
                                    size=12,
                                )
                                if requirement.get("observaciones")
                                else ft.Container(),
                            ],
                            spacing=6,
                        ),
                        padding=14,
                    ),
                    elevation=1,
                )
            )
        page.update()

    def volver_a_proyectos() -> None:
        nonlocal current_view
        current_view = "Proyectos"
        navigation.selected_index = 1
        page.navigation_bar = navigation
        configurar_barra_principal()
        render_content()

    async def actualizar_datos(
        _: ft.ControlEvent | None = None, *, notify: bool = True
    ) -> None:
        try:
            nuevos_proyectos = await asyncio.to_thread(client.cargar_proyectos)
            nuevos_requisitos = await asyncio.to_thread(client.cargar_requisitos_globales)
        except PortalError as error:
            if client.session is None:
                render_login()
            else:
                show_message(str(error), error=True)
            return
        projects.clear()
        projects.extend(nuevos_proyectos)
        requirements.clear()
        requirements.extend(nuevos_requisitos)
        render_content()
        if notify:
            show_message("Los proyectos se actualizaron.")

    async def cerrar_sesion(_: ft.ControlEvent) -> None:
        logout_error = None
        try:
            await asyncio.to_thread(client.cerrar_sesion)
        except PortalError as error:
            client.session = None
            logout_error = error
        render_login()
        if logout_error:
            show_message(
                f"La sesión se cerró en este dispositivo, pero Supabase no pudo "
                f"revocarla: {logout_error}",
                error=True,
            )

    def cambiar_seccion(event: ft.ControlEvent) -> None:
        nonlocal current_view, search_value
        current_view = SECTIONS[event.control.selected_index]
        search_value = ""
        configurar_barra_principal()
        render_content()

    def configurar_barra_principal() -> None:
        profile = client.session.profile if client.session else {}
        page.appbar = ft.AppBar(
            title=ft.Text("Gestor de proyectos GD"),
            bgcolor="#154360",
            color=ft.Colors.WHITE,
            actions=[
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="Actualizar",
                    on_click=actualizar_datos,
                ),
                ft.IconButton(
                    icon=ft.Icons.LOGOUT,
                    tooltip=f"Cerrar sesión · {profile.get('username', '')}",
                    on_click=cerrar_sesion,
                ),
            ],
        )
        page.navigation_bar = navigation

    def render_home(profile: dict[str, Any]) -> None:
        page.clean()
        page.appbar = None
        page.navigation_bar = None
        navigation.on_change = cambiar_seccion
        navigation.selected_index = 0
        nonlocal current_view, search_value
        current_view = "Resumen"
        search_value = ""
        configurar_barra_principal()
        page.add(
            ft.Container(
                content=content,
                padding=16,
                expand=True,
            )
        )
        content.controls.clear()
        content.controls.append(ft.Text(f"Hola, {profile.get('display_name', '')}"))
        content.controls.append(ft.ProgressRing())
        page.update()

    async def login_clicked(
        username: ft.TextField,
        password: ft.TextField,
        button: ft.FilledButton,
        error_text: ft.Text,
    ) -> None:
        if not (username.value or "").strip() or not password.value:
            error_text.value = "Escribe tu usuario y contraseña."
            page.update()
            return

        button.disabled = True
        error_text.value = ""
        page.update()
        try:
            profile = await asyncio.to_thread(
                client.iniciar_sesion,
                username.value or "",
                password.value or "",
            )
            password.value = ""
            render_home(profile)
            await actualizar_datos(notify=False)
        except PortalError as error:
            client.session = None
            error_text.value = str(error)
            button.disabled = False
            page.update()

    def render_login() -> None:
        page.clean()
        page.appbar = None
        page.navigation_bar = None
        username = ft.TextField(
            label="Usuario",
            prefix_icon=ft.Icons.PERSON_OUTLINE,
            autofocus=True,
            width=360,
        )
        password = ft.TextField(
            label="Contraseña web",
            prefix_icon=ft.Icons.LOCK_OUTLINE,
            password=True,
            can_reveal_password=True,
            width=360,
        )
        error_text = ft.Text(color=ft.Colors.RED_700, text_align=ft.TextAlign.CENTER)

        async def submit_login(_: ft.ControlEvent) -> None:
            await login_clicked(
                username,
                password,
                button,
                error_text,
            )

        button = ft.FilledButton(
            "Ingresar",
            icon=ft.Icons.LOGIN,
            width=360,
            on_click=submit_login,
        )
        username.on_submit = submit_login
        password.on_submit = submit_login
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.SOLAR_POWER, size=72, color=ft.Colors.BLUE_700),
                        ft.Text(
                            "Gestor de proyectos GD",
                            size=25,
                            weight=ft.FontWeight.BOLD,
                            color="#154360",
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            "Consulta del portafolio",
                            color=ft.Colors.BLUE_GREY_600,
                        ),
                        ft.Container(height=12),
                        username,
                        password,
                        button,
                        error_text,
                        ft.Text(
                            "Requiere conexión a internet. Usa la contraseña configurada "
                            "para la web.",
                            size=12,
                            color=ft.Colors.BLUE_GREY_600,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=14,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=440,
                padding=24,
                alignment=ft.Alignment(0, 0),
            )
        )

    render_login()


if __name__ == "__main__":
    ft.run(main)
