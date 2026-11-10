from __future__ import annotations

import re
import secrets
import unicodedata
from typing import Any, Callable
from urllib.parse import quote

import requests


ADMIN_ROLES = frozenset({"Administrador", "Consulta"})
DISABLE_BAN_DURATION = "876000h"
USERNAME_PATTERN = re.compile(r"^(?=.*\w)[\w .@+-]{2,64}$", re.UNICODE)


class WebUserAdminError(RuntimeError):
    pass


class WebUserAdmin:
    def __init__(
        self,
        base_url: str,
        anon_key: str,
        service_role_key: str,
        requester: Callable[..., Any] = requests.request,
    ):
        self.base_url = base_url.rstrip("/")
        self.anon_key = anon_key
        self.service_role_key = service_role_key.strip()
        self.requester = requester
        if not self.service_role_key:
            raise WebUserAdminError(
                "La administración está pendiente de configuración. "
                "Agrega supabase.service_role_key en los secretos del servidor web."
            )

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        privileged: bool = True,
        user_token: str | None = None,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        prefer: str | None = None,
    ) -> Any:
        api_key = self.service_role_key if privileged else self.anon_key
        headers = {"apikey": api_key}
        bearer = self.service_role_key if privileged else user_token
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        if prefer:
            headers["Prefer"] = prefer

        try:
            response = self.requester(
                method,
                f"{self.base_url}{endpoint}",
                headers=headers,
                params=params,
                json=payload,
                timeout=(8, 25),
            )
        except requests.RequestException as error:
            raise WebUserAdminError(
                "No se pudo conectar con Supabase para administrar usuarios."
            ) from error

        if not response.ok:
            if response.status_code == 409:
                raise WebUserAdminError(
                    "El usuario ya existe en Supabase Auth o en el portal."
                )
            if response.status_code in (401, 403):
                raise WebUserAdminError(
                    "Supabase rechazó la operación. Verifica los permisos "
                    "del administrador y la clave privada configurada en el servidor."
                )
            if response.status_code == 404:
                raise WebUserAdminError(
                    "No se encontró la cuenta solicitada o falta la tabla "
                    "web_profiles. Revisa la configuración del proyecto."
                )
            if response.status_code >= 500:
                raise WebUserAdminError(
                    f"Supabase no pudo completar la operación (HTTP {response.status_code})."
                )
            raise WebUserAdminError(
                f"Supabase rechazó los datos de la operación (HTTP {response.status_code})."
            )

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise WebUserAdminError(
                "Supabase devolvió una respuesta no válida al administrar usuarios."
            ) from error

    def _require_administrator(self, access_token: str) -> str:
        if not access_token:
            raise WebUserAdminError("La sesión expiró. Inicia sesión de nuevo.")
        auth_user = self._request(
            "GET",
            "/auth/v1/user",
            privileged=False,
            user_token=access_token,
        )
        auth_user_id = auth_user.get("id") if isinstance(auth_user, dict) else None
        if not auth_user_id:
            raise WebUserAdminError("Supabase no confirmó la identidad de la sesión.")

        profiles = self._request(
            "GET",
            "/rest/v1/web_profiles",
            params={
                "select": "auth_user_id,username,role,enabled",
                "auth_user_id": f"eq.{auth_user_id}",
                "limit": "1",
            },
        )
        if not profiles:
            raise WebUserAdminError("La cuenta no tiene un perfil web habilitado.")
        profile = profiles[0]
        if not profile.get("enabled") or profile.get("role") != "Administrador":
            raise WebUserAdminError(
                "Solo un administrador habilitado puede gestionar usuarios web."
            )
        return str(auth_user_id)

    def listar_usuarios(self, access_token: str) -> list[dict[str, Any]]:
        self._require_administrator(access_token)
        usuarios = self._request(
            "GET",
            "/rest/v1/web_profiles",
            params={
                "select": "auth_user_id,username,display_name,role,enabled",
                "order": "username.asc",
                "limit": "1000",
            },
        )
        if not isinstance(usuarios, list):
            raise WebUserAdminError("Supabase devolvió una lista de usuarios no válida.")
        return usuarios

    def crear_usuario(
        self,
        access_token: str,
        username: str,
        display_name: str,
        role: str,
    ) -> tuple[dict[str, Any], str]:
        self._require_administrator(access_token)
        username = unicodedata.normalize("NFKC", username.strip()).lower()
        display_name = display_name.strip()
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValueError(
                "El usuario debe tener entre 2 y 64 caracteres. Se permiten letras "
                "(también con tilde), números, espacios, punto, guion, guion bajo, "
                "@ y +."
            )
        if not display_name:
            raise ValueError("Escribe el nombre de la persona.")
        if role not in ADMIN_ROLES:
            raise ValueError("Selecciona un rol válido.")

        existentes = self._request(
            "GET",
            "/rest/v1/web_profiles",
            params={
                "select": "auth_user_id",
                "username": f"eq.{username}",
                "limit": "1",
            },
        )
        if existentes:
            raise WebUserAdminError("Ya existe una cuenta con ese nombre de usuario.")

        perfiles = self._request(
            "GET",
            "/rest/v1/web_profiles",
            params={"select": "source_user_id", "limit": "1000"},
        )
        ids_origen = [
            int(perfil["source_user_id"])
            for perfil in perfiles
            if perfil.get("source_user_id") is not None
            and int(perfil["source_user_id"]) < 0
        ]
        source_user_id = min(ids_origen, default=0) - 1
        password = secrets.token_urlsafe(24)
        correo = self._correo_interno(username)
        auth_user = self._request(
            "POST",
            "/auth/v1/admin/users",
            payload={
                "email": correo,
                "password": password,
                "email_confirm": True,
                "app_metadata": {"role": role, "enabled": True},
                "user_metadata": {"display_name": display_name},
            },
        )
        auth_user_id = (
            auth_user.get("id") if isinstance(auth_user, dict) else None
        )
        if not auth_user_id:
            raise WebUserAdminError(
                "Supabase no devolvió el identificador de la cuenta creada."
            )

        perfil = {
            "auth_user_id": auth_user_id,
            "source_user_id": source_user_id,
            "username": username,
            "display_name": display_name,
            "role": role,
            "enabled": True,
        }
        try:
            self._request(
                "POST",
                "/rest/v1/web_profiles",
                payload=perfil,
                prefer="return=minimal",
            )
        except WebUserAdminError as error:
            try:
                self._request(
                    "DELETE",
                    f"/auth/v1/admin/users/{quote(str(auth_user_id), safe='')}",
                )
            except WebUserAdminError as cleanup_error:
                raise WebUserAdminError(
                    "Se creó la cuenta de autenticación, pero no se pudo guardar "
                    "su perfil ni limpiar la cuenta incompleta. Contacta al "
                    "administrador de Supabase."
                ) from cleanup_error
            raise WebUserAdminError(
                "No se pudo crear el perfil web; se canceló la cuenta incompleta. "
                f"{error}"
            ) from error
        return perfil, password

    def restablecer_password(
        self,
        access_token: str,
        auth_user_id: str,
    ) -> str:
        actor_id = self._require_administrator(access_token)
        if auth_user_id == actor_id:
            raise WebUserAdminError(
                "No puedes restablecer tu propia contraseña desde esta sesión. "
                "Usa la utilidad local de recuperación o pide ayuda a otro administrador."
            )
        self._obtener_usuario(auth_user_id)
        password = secrets.token_urlsafe(24)
        self._request(
            "PUT",
            f"/auth/v1/admin/users/{quote(auth_user_id, safe='')}",
            payload={"password": password},
        )
        return password

    def restablecer_password_administrador_por_usuario(
        self,
        username: str,
        new_password: str,
    ) -> tuple[str, str]:
        username = username.strip()
        if not username or len(username) > 64:
            raise ValueError("Escribe el nombre de usuario existente (máximo 64 caracteres).")
        if len(new_password) < 12:
            raise ValueError("La contraseña nueva debe tener al menos 12 caracteres.")

        perfiles = self._request(
            "GET",
            "/rest/v1/web_profiles",
            params={
                "select": "auth_user_id,username,role,enabled",
                "username": f"eq.{username}",
                "limit": "1",
            },
        )
        if not perfiles:
            raise WebUserAdminError("No se encontró el perfil de ese usuario.")
        perfil = perfiles[0]
        if perfil.get("role") != "Administrador" or not perfil.get("enabled"):
            raise WebUserAdminError(
                "La cuenta no es un Administrador habilitado; no se restableció."
            )

        email = self._correo_interno(str(perfil["username"]))
        page = 1
        auth_user_id = None
        while True:
            resultado = self._request(
                "GET",
                "/auth/v1/admin/users",
                params={"page": str(page), "per_page": "1000"},
            )
            usuarios = resultado.get("users", []) if isinstance(resultado, dict) else []
            auth_user_id = next(
                (
                    usuario.get("id")
                    for usuario in usuarios
                    if isinstance(usuario.get("email"), str)
                    and usuario["email"].casefold() == email.casefold()
                ),
                None,
            )
            if auth_user_id:
                break
            if len(usuarios) < 1000:
                break
            page += 1

        if not auth_user_id or auth_user_id != perfil.get("auth_user_id"):
            raise WebUserAdminError(
                "No se pudo asociar de forma segura el perfil con su cuenta de Auth."
            )

        self._request(
            "PUT",
            f"/auth/v1/admin/users/{quote(str(auth_user_id), safe='')}",
            payload={"password": new_password},
        )
        return username, new_password

    def cambiar_habilitacion(
        self,
        access_token: str,
        auth_user_id: str,
        enabled: bool,
    ) -> None:
        actor_id = self._require_administrator(access_token)
        if auth_user_id == actor_id and not enabled:
            raise WebUserAdminError("No puedes deshabilitar tu propia cuenta.")
        perfil = self._obtener_usuario(auth_user_id)
        if bool(perfil.get("enabled")) == enabled:
            raise WebUserAdminError("La cuenta ya tiene ese estado.")
        if not enabled and perfil.get("role") == "Administrador":
            administradores = self._request(
                "GET",
                "/rest/v1/web_profiles",
                params={
                    "select": "auth_user_id",
                    "role": "eq.Administrador",
                    "enabled": "eq.true",
                    "limit": "1000",
                },
            )
            if len(administradores) <= 1:
                raise WebUserAdminError(
                    "No se puede deshabilitar el último administrador habilitado."
                )

        auth_action = (
            {"ban_duration": "none"}
            if enabled
            else {"ban_duration": DISABLE_BAN_DURATION}
        )
        self._request(
            "PUT",
            f"/auth/v1/admin/users/{quote(auth_user_id, safe='')}",
            payload=auth_action,
        )
        self._request(
            "PATCH",
            "/rest/v1/web_profiles",
            params={"auth_user_id": f"eq.{auth_user_id}"},
            payload={"enabled": enabled},
            prefer="return=minimal",
        )

    def _obtener_usuario(self, auth_user_id: str) -> dict[str, Any]:
        perfiles = self._request(
            "GET",
            "/rest/v1/web_profiles",
            params={
                "select": "auth_user_id,username,display_name,role,enabled",
                "auth_user_id": f"eq.{auth_user_id}",
                "limit": "1",
            },
        )
        if not perfiles:
            raise WebUserAdminError("No se encontró el perfil del usuario.")
        return perfiles[0]

    @staticmethod
    def _correo_interno(username: str) -> str:
        import hashlib

        digest = hashlib.sha256(username.strip().encode("utf-8")).hexdigest()
        return f"u{digest}@login.gestor-gd.invalid"
