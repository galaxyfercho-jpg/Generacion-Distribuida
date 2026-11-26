"""Migra la base SQLite seleccionada a Supabase y sincroniza soportes con Cloudflare R2."""

from __future__ import annotations

import argparse
from contextlib import closing
import getpass
import hashlib
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import threading
import tomllib
import unicodedata
from typing import Any

import boto3
from botocore.config import Config
import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = (
    ROOT / "sistema_gd_v4.db"
    if (ROOT / "sistema_gd_v4.db").is_file()
    else ROOT / "dist" / "sistema_gd_v4.db"
)
BATCH_SIZE = 250
MIN_WEB_PASSWORD_LENGTH = 12

# Carpeta local donde están los adjuntos en tu PC
CARPETA_BASE_ONEDRIVE = r"C:\Users\feusa\OneDrive\1. Gestor GD_Adjuntos"
R2_PREFIX = "r2://"

PROJECT_COLUMNS = (
    "id", "cluster", "nombre", "municipio", "departamento", "direccion", "latitud",
    "longitud", "area", "radicado", "cod_validacion", "circuito", "coord_conexion",
    "fecha_creacion", "estado_general", "capacidad_kw", "req_servidumbre", "req_contrato",
    "num_paneles", "pot_panel", "num_inversores", "modelos_inversores", "en_operacion",
)
REQUIREMENT_COLUMNS = (
    "id", "proyecto_id", "categoria", "descripcion", "entidad", "estado",
    "fecha_radicacion", "fecha_limite", "fecha_final", "observaciones",
    "evidencia_ruta", "evidencia_respuesta",
)

_thread_local = threading.local()


class MigrationError(RuntimeError):
    pass


def limpiar_nombre_archivo(nombre: str) -> str:
    base, ext = os.path.splitext(nombre)
    base_norm = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base_limpio = re.sub(r"[^A-Za-z0-9._-]+", "_", base_norm).strip("._-")
    if not base_limpio:
        base_limpio = "documento"
    ext_limpia = re.sub(r"[^A-Za-z0-9.]+", "", ext).lower()
    return f"{base_limpio[:120]}{ext_limpia}"


def resolver_ruta_local(ruta_bd: str, carpeta_base: str) -> str:
    ruta = ruta_bd.strip()
    if ruta.startswith("onedrive-gd:"):
        relativa = ruta[len("onedrive-gd:"):].lstrip("/\\")
        return os.path.normpath(os.path.join(carpeta_base, relativa))
    return os.path.normpath(ruta)


def obtener_cliente_r2(r2_cfg: dict[str, str]):
    if not hasattr(_thread_local, "r2_client"):
        _thread_local.r2_client = boto3.client(
            "s3",
            endpoint_url=f"https://{r2_cfg['account_id']}.r2.cloudflarestorage.com",
            aws_access_key_id=r2_cfg["access_key_id"],
            aws_secret_access_key=r2_cfg["secret_access_key"],
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=20,
                read_timeout=120,
            ),
        )
    return _thread_local.r2_client


def subir_archivo_r2(r2_cfg: dict[str, str], ruta_local: str, ruta_objeto: str) -> None:
    mime_type, _ = mimetypes.guess_type(ruta_local)
    cliente = obtener_cliente_r2(r2_cfg)
    cliente.upload_file(
        ruta_local,
        r2_cfg["bucket"],
        ruta_objeto,
        ExtraArgs={"ContentType": mime_type or "application/octet-stream"},
    )


def email_interno(usuario: str) -> str:
    usuario = usuario.strip()
    if not usuario:
        raise MigrationError("La base contiene un nombre de usuario vacío.")
    digest = hashlib.sha256(usuario.encode("utf-8")).hexdigest()
    return f"u{digest}@login.gestor-gd.invalid"


def solicitar_password_web() -> str:
    while True:
        password = getpass.getpass(
            f"La contraseña local es corta. Define una contraseña web de "
            f"al menos {MIN_WEB_PASSWORD_LENGTH} caracteres (entrada oculta): "
        )
        if len(password) < MIN_WEB_PASSWORD_LENGTH:
            print(f"La contraseña debe tener al menos {MIN_WEB_PASSWORD_LENGTH} caracteres.")
            continue
        confirmacion = getpass.getpass("Confirma la nueva contraseña web: ")
        if password != confirmacion:
            print("Las contraseñas no coinciden. Inténtalo de nuevo.")
            continue
        return password


def solicitar_json(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, str],
    **kwargs: Any,
) -> Any:
    try:
        response = session.request(method, url, headers=headers, timeout=(10, 90), **kwargs)
    except requests.RequestException as error:
        raise MigrationError("No se pudo contactar Supabase. Verifica la URL y la conexión.") from error
    if not response.ok:
        endpoint = url.split("/auth/v1/")[-1].split("/rest/v1/")[-1]
        raise MigrationError(
            f"Supabase rechazó una operación ({response.status_code}) en {endpoint}. "
            f"Detalle: {response.text}"
        )
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def listar_usuarios_auth(
    session: requests.Session, base_url: str, headers: dict[str, str]
) -> dict[str, dict[str, Any]]:
    existentes: dict[str, dict[str, Any]] = {}
    pagina = 1
    while True:
        payload = solicitar_json(
            session,
            "GET",
            f"{base_url}/auth/v1/admin/users",
            headers,
            params={"page": pagina, "per_page": 1000},
        )
        usuarios = payload.get("users", []) if isinstance(payload, dict) else []
        for usuario in usuarios:
            correo = usuario.get("email")
            if correo:
                existentes[correo] = usuario
        if len(usuarios) < 1000:
            return existentes
        pagina += 1


def asegurar_usuario_auth(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    existentes: dict[str, dict[str, Any]],
    fila: tuple[Any, ...],
) -> dict[str, Any]:
    source_user_id, usuario, password, rol, nombre = fila
    correo_interno = email_interno(usuario)
    metadata = {
        "source_user_id": int(source_user_id),
        "role": str(rol or "Consulta"),
        "enabled": True,
    }
    cuerpo = {
        "email": correo_interno,
        "password": password,
        "email_confirm": True,
        "app_metadata": metadata,
        "user_metadata": {"display_name": str(nombre or usuario)},
    }
    existente = existentes.get(correo_interno)
    if existente:
        auth_user = existente
    else:
        if len(str(password)) < MIN_WEB_PASSWORD_LENGTH:
            cuerpo["password"] = solicitar_password_web()
        auth_user = solicitar_json(
            session,
            "POST",
            f"{base_url}/auth/v1/admin/users",
            headers,
            json=cuerpo,
        )
    if not isinstance(auth_user, dict) or not auth_user.get("id"):
        raise MigrationError("Supabase no devolvió el identificador de una cuenta migrada.")
    existentes[correo_interno] = auth_user
    return {
        "auth_user_id": auth_user["id"],
        "source_user_id": int(source_user_id),
        "username": str(usuario),
        "display_name": str(nombre or usuario),
        "role": str(rol or "Consulta"),
        "enabled": True,
    }


def upsert_lotes(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    tabla: str,
    registros: list[dict[str, Any]],
    clave: str,
) -> None:
    headers_upsert = {**headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
    for inicio in range(0, len(registros), BATCH_SIZE):
        solicitar_json(
            session,
            "POST",
            f"{base_url}/rest/v1/{tabla}",
            headers_upsert,
            params={"on_conflict": clave},
            json=registros[inicio : inicio + BATCH_SIZE],
        )


def obtener_soportes_existentes_supabase(
    session: requests.Session, base_url: str, headers: dict[str, str]
) -> dict[int, dict[str, str]]:
    """Consulta las evidencias actuales en Supabase para no sobreescribir las rutas r2://."""
    soportes: dict[int, dict[str, str]] = {}
    offset = 0
    limite = 1000
    while True:
        resp = solicitar_json(
            session,
            "GET",
            f"{base_url}/rest/v1/requisitos",
            headers,
            params={
                "select": "id,evidencia_ruta,evidencia_respuesta",
                "limit": str(limite),
                "offset": str(offset),
            },
        )
        if not resp:
            break
        for item in resp:
            soportes[int(item["id"])] = {
                "evidencia_ruta": item.get("evidencia_ruta") or "",
                "evidencia_respuesta": item.get("evidencia_respuesta") or "",
            }
        if len(resp) < limite:
            break
        offset += limite
    return soportes


def resolver_soportes_para_nube(
    fila_req: dict[str, Any],
    existente_supabase: dict[str, str],
    r2_cfg: dict[str, str] | None,
    carpeta_base: str,
) -> tuple[str, str]:
    """Preserva rutas r2:// existentes y sube archivos nuevos locales a Cloudflare R2."""
    proy_id = fila_req["proyecto_id"]
    req_id = fila_req["id"]
    resultados = {}

    for columna, subcarpeta in (
        ("evidencia_ruta", "radicado"),
        ("evidencia_respuesta", "cierre"),
    ):
        valor_local = (fila_req.get(columna) or "").strip()
        valor_nube_previo = (existente_supabase.get(columna) or "").strip()

        if not valor_local:
            resultados[columna] = valor_nube_previo
            continue

        rutas_locales = [r.strip() for r in valor_local.split("|") if r.strip()]
        rutas_nube_previas = [r.strip() for r in valor_nube_previo.split("|") if r.strip()]
        rutas_finales = []

        for ruta_loc in rutas_locales:
            if ruta_loc.startswith((R2_PREFIX, "sb://")):
                rutas_finales.append(ruta_loc)
                continue

            nombre_archivo_local = os.path.basename(resolver_ruta_local(ruta_loc, carpeta_base))
            nombre_limpio = limpiar_nombre_archivo(nombre_archivo_local)

            # 1. Comprobar si ya estaba registrada en la nube
            coincidencia = next(
                (r for r in rutas_nube_previas if r.endswith(f"/{nombre_limpio}")),
                None,
            )
            if coincidencia:
                rutas_finales.append(coincidencia)
                continue

            # 2. Si es un archivo nuevo y tenemos R2 disponible, subirlo
            ruta_fisica = resolver_ruta_local(ruta_loc, carpeta_base)
            if r2_cfg and os.path.isfile(ruta_fisica):
                ruta_objeto = f"proyecto_{proy_id}/req_{req_id}/{subcarpeta}/{nombre_limpio}"
                try:
                    subir_archivo_r2(r2_cfg, ruta_fisica, ruta_objeto)
                    rutas_finales.append(f"{R2_PREFIX}{ruta_objeto}")
                    print(f"  [R2 NUEVO] Proy {proy_id} / Req {req_id}: {nombre_limpio}")
                except Exception as error:
                    print(f"  [AVISO] No se pudo subir {nombre_limpio} a R2: {error}")
                    rutas_finales.append(ruta_loc)
            else:
                rutas_finales.append(ruta_loc)

        resultados[columna] = "|".join(rutas_finales)

    return resultados["evidencia_ruta"], resultados["evidencia_respuesta"]


def migrar(
    database: Path,
    base_url: str,
    service_role_key: str,
    r2_cfg: dict[str, str] | None = None,
) -> None:
    if not database.is_file():
        raise MigrationError(f"No se encontró la base SQLite: {database}")
    if not base_url.startswith("https://"):
        raise MigrationError("La URL de Supabase debe usar HTTPS.")

    base_url = base_url.rstrip("/")
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }

    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        columnas_proy_disp = {
            f["name"] for f in connection.execute("PRAGMA table_info(proyectos)")
        }
        columnas_req_disp = {
            f["name"] for f in connection.execute("PRAGMA table_info(requisitos)")
        }

        columnas_proyecto = [c for c in PROJECT_COLUMNS if c in columnas_proy_disp]
        columnas_req = [c for c in REQUIREMENT_COLUMNS if c in columnas_req_disp]

        usuarios = connection.execute(
            "SELECT id, usuario, password, rol, nombre FROM usuarios ORDER BY id"
        ).fetchall()
        clusters = connection.execute(
            "SELECT id, nombre_cluster FROM clusteres ORDER BY id"
        ).fetchall()
        proyectos = connection.execute(
            f"SELECT {', '.join(columnas_proyecto)} FROM proyectos ORDER BY id"
        ).fetchall()
        requisitos = connection.execute(
            f"SELECT {', '.join(columnas_req)} FROM requisitos ORDER BY id"
        ).fetchall()

    alias = [email_interno(str(usuario["usuario"])) for usuario in usuarios]
    if len(alias) != len(set(alias)):
        raise MigrationError("Hay nombres de usuario duplicados después de normalizar la cuenta web.")

    with requests.Session() as session:
        print("Sincronizando perfiles de acceso...")
        auth_users = listar_usuarios_auth(session, base_url, headers)
        perfiles = [
            asegurar_usuario_auth(session, base_url, headers, auth_users, tuple(usuario))
            for usuario in usuarios
        ]
        upsert_lotes(session, base_url, headers, "web_profiles", perfiles, "source_user_id")

        print("Sincronizando clústeres y proyectos...")
        cluster_rows = [dict(fila) for fila in clusters]
        project_rows = [dict(fila) for fila in proyectos]
        upsert_lotes(session, base_url, headers, "clusteres", cluster_rows, "id")
        upsert_lotes(session, base_url, headers, "proyectos", project_rows, "id")

        print("Comprobando soportes documentales en la nube...")
        soportes_nube = obtener_soportes_existentes_supabase(session, base_url, headers)

        requirement_rows = []
        for fila in requisitos:
            d_fila = dict(fila)
            req_id = int(d_fila["id"])
            existente = soportes_nube.get(req_id, {})
            ev_ruta, ev_resp = resolver_soportes_para_nube(
                d_fila, existente, r2_cfg, CARPETA_BASE_ONEDRIVE
            )
            d_fila["evidencia_ruta"] = ev_ruta
            d_fila["evidencia_respuesta"] = ev_resp
            requirement_rows.append(d_fila)

        print("Sincronizando requisitos a Supabase...")
        upsert_lotes(session, base_url, headers, "requisitos", requirement_rows, "id")

    print("\n✓ Sincronización completada con éxito.")
    print(f"Cuentas: {len(perfiles)} | Clústeres: {len(cluster_rows)} | Proyectos: {len(project_rows)} | Requisitos: {len(requirement_rows)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza SQLite a Supabase y Cloudflare R2.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--url", default=os.environ.get("SUPABASE_URL"))
    args = parser.parse_args()

    ruta_secretos = ROOT / ".streamlit" / "secrets.toml"
    secretos: dict[str, Any] = {}
    if ruta_secretos.is_file():
        try:
            secretos = tomllib.loads(ruta_secretos.read_text(encoding="utf-8"))
        except Exception:
            pass

    base_url = args.url or secretos.get("supabase", {}).get("url")
    if not base_url:
        parser.error("Configura supabase.url en .streamlit/secrets.toml o pásala con --url.")

    service_role_key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or secretos.get("supabase", {}).get("service_role_key")
        or secretos.get("supabase", {}).get("anon_key", "")
    ).strip()
    if not service_role_key:
        service_role_key = getpass.getpass("Clave service_role de Supabase (entrada oculta): ").strip()
    if not service_role_key:
        parser.error("La clave service_role no puede estar vacía.")

    r2_cfg = None
    r2_sec = secretos.get("r2_storage", {})
    if r2_sec.get("account_id") and r2_sec.get("access_key_id") and r2_sec.get("secret_access_key"):
        r2_cfg = {
            "account_id": str(r2_sec["account_id"]).strip(),
            "access_key_id": str(r2_sec["access_key_id"]).strip(),
            "secret_access_key": str(r2_sec["secret_access_key"]).strip(),
            "bucket": str(r2_sec.get("bucket", "soportes-gd")).strip(),
        }

    try:
        migrar(args.database, base_url, service_role_key, r2_cfg)
    except MigrationError as error:
        parser.exit(1, f"Error de sincronización: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
