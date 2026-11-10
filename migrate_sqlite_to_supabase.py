"""Migra la base SQLite seleccionada a Supabase sin imprimir credenciales."""

from __future__ import annotations

import argparse
from contextlib import closing
import getpass
import hashlib
import os
import sqlite3
import tomllib
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "dist" / "sistema_gd_v4.db"
BATCH_SIZE = 250
MIN_WEB_PASSWORD_LENGTH = 12

PROJECT_COLUMNS = (
    "id", "cluster", "nombre", "municipio", "departamento", "direccion", "latitud",
    "longitud", "area", "radicado", "cod_validacion", "circuito", "coord_conexion",
    "fecha_creacion", "estado_general", "capacidad_kw", "req_servidumbre", "req_contrato",
    "num_paneles", "pot_panel", "num_inversores", "modelos_inversores", "en_operacion",
)
REQUIREMENT_COLUMNS = (
    "id", "proyecto_id", "categoria", "descripcion", "entidad", "estado",
    "fecha_radicacion", "fecha_limite", "fecha_final", "observaciones",
)


class MigrationError(RuntimeError):
    pass


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
            "Revisa schema.sql y los permisos del proyecto."
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


def migrar(database: Path, base_url: str, service_role_key: str) -> None:
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
        columnas_proyecto_disponibles = {
            fila["name"] for fila in connection.execute("PRAGMA table_info(proyectos)")
        }
        columnas_proyecto = [
            columna for columna in PROJECT_COLUMNS
            if columna in columnas_proyecto_disponibles
        ]
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
            f"SELECT {', '.join(REQUIREMENT_COLUMNS)} FROM requisitos ORDER BY id"
        ).fetchall()

    alias = [email_interno(str(usuario["usuario"])) for usuario in usuarios]
    if len(alias) != len(set(alias)):
        raise MigrationError("Hay nombres de usuario duplicados después de normalizar la cuenta web.")

    with requests.Session() as session:
        auth_users = listar_usuarios_auth(session, base_url, headers)
        perfiles = [
            asegurar_usuario_auth(session, base_url, headers, auth_users, tuple(usuario))
            for usuario in usuarios
        ]
        upsert_lotes(session, base_url, headers, "web_profiles", perfiles, "source_user_id")

        cluster_rows = [dict(fila) for fila in clusters]
        project_rows = [dict(fila) for fila in proyectos]
        requirement_rows = [dict(fila) for fila in requisitos]

        upsert_lotes(session, base_url, headers, "clusteres", cluster_rows, "id")
        upsert_lotes(session, base_url, headers, "proyectos", project_rows, "id")
        upsert_lotes(session, base_url, headers, "requisitos", requirement_rows, "id")

    print("Migración completada.")
    print(f"Cuentas: {len(perfiles)}")
    print(f"Clústeres: {len(cluster_rows)}")
    print(f"Proyectos: {len(project_rows)}")
    print(f"Requisitos: {len(requirement_rows)}")
    print("Las contraseñas no se imprimieron; Supabase Auth las almacenó con hash.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migra la base local a Supabase de forma idempotente.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--url", default=os.environ.get("SUPABASE_URL"))
    args = parser.parse_args()

    base_url = args.url
    if not base_url:
        ruta_secretos = ROOT / ".streamlit" / "secrets.toml"
        try:
            secretos = tomllib.loads(ruta_secretos.read_text(encoding="utf-8"))
            base_url = secretos["supabase"]["url"].strip()
        except (OSError, KeyError, tomllib.TOMLDecodeError):
            parser.error("Configura supabase.url en .streamlit/secrets.toml o pásala con --url.")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not service_role_key:
        service_role_key = getpass.getpass("Clave service_role de Supabase (entrada oculta): ").strip()
    if not service_role_key:
        parser.error("La clave service_role no puede estar vacía.")

    try:
        migrar(args.database, base_url, service_role_key)
    except MigrationError as error:
        parser.exit(1, f"Error de migración: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())