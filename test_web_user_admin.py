import unittest

from web_user_admin import WebUserAdmin, WebUserAdminError


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._data = data
        self.content = b"" if data is None else b"response"

    def json(self):
        return self._data


class WebUserAdminTests(unittest.TestCase):
    def setUp(self):
        self.actor_id = "admin-id"
        self.target_id = "user-id"
        self.profiles = [
            {
                "auth_user_id": self.actor_id,
                "source_user_id": 1,
                "username": "admin",
                "display_name": "Web Admin",
                "role": "Administrador",
                "enabled": True,
            },
            {
                "auth_user_id": self.target_id,
                "source_user_id": 2,
                "username": "consulta",
                "display_name": "Persona Consulta",
                "role": "Consulta",
                "enabled": True,
            },
        ]
        self.calls = []
        self.force_single_admin = False
        self.requester = self.respond
        self.service = WebUserAdmin(
            "https://example.supabase.co",
            "anon-key",
            "server-only-key",
            requester=self.requester,
        )

    def test_missing_service_role_key_disables_admin_api(self):
        with self.assertRaisesRegex(WebUserAdminError, "service_role_key"):
            WebUserAdmin("https://example.supabase.co", "anon-key", "")

    def respond(self, method, url, headers, params=None, json=None, **kwargs):
        self.calls.append((method, url, headers, params, json))
        if url.endswith("/auth/v1/user"):
            return FakeResponse(data={"id": self.actor_id})
        if url.endswith("/auth/v1/admin/users") and method == "GET":
            return FakeResponse(
                data={
                    "users": [
                        {
                            "id": profile["auth_user_id"],
                            "email": WebUserAdmin._correo_interno(profile["username"]),
                        }
                        for profile in self.profiles
                    ],
                }
            )
        if url.endswith("/auth/v1/admin/users"):
            return FakeResponse(data={"id": "new-user-id"})
        if url.endswith("/auth/v1/admin/users/new-user-id"):
            return FakeResponse(data={"id": "new-user-id"})
        if url.endswith("/auth/v1/admin/users/admin-id"):
            return FakeResponse(data={"id": self.actor_id})
        if url.endswith("/auth/v1/admin/users/user-id"):
            return FakeResponse(data={"id": self.target_id})
        if url.endswith("/rest/v1/web_profiles"):
            if method == "POST":
                self.profiles.append(json)
                return FakeResponse()
            if method == "PATCH":
                for profile in self.profiles:
                    if params.get("auth_user_id") == f"eq.{profile['auth_user_id']}":
                        profile.update(json)
                return FakeResponse()
            if params and params.get("username"):
                return FakeResponse(
                    data=[
                        profile
                        for profile in self.profiles
                        if profile["username"] == params["username"][3:]
                    ]
                )
            if params and params.get("auth_user_id"):
                auth_user_id = params["auth_user_id"][3:]
                return FakeResponse(
                    data=[
                        profile
                        for profile in self.profiles
                        if profile["auth_user_id"] == auth_user_id
                    ]
                )
            if params and params.get("role") == "eq.Administrador":
                admins = [
                    {"auth_user_id": profile["auth_user_id"]}
                    for profile in self.profiles
                    if profile["role"] == "Administrador" and profile["enabled"]
                ]
                if self.force_single_admin:
                    admins = admins[:1]
                return FakeResponse(data=admins)
            if params and params.get("select") == "source_user_id":
                return FakeResponse(
                    data=[
                        {"source_user_id": profile["source_user_id"]}
                        for profile in self.profiles
                    ]
                )
            return FakeResponse(data=self.profiles)
        return FakeResponse(status_code=404, data={"message": "unexpected request"})

    def test_create_user_creates_auth_account_and_profile_with_server_key(self):
        profile, temporary_password = self.service.crear_usuario(
            "valid-access-token",
            "New.User",
            "Persona Nueva",
            "Consulta",
        )

        self.assertEqual(profile["username"], "new.user")
        self.assertEqual(profile["source_user_id"], -1)
        self.assertTrue(profile["enabled"])
        self.assertGreaterEqual(len(temporary_password), 24)
        auth_create = next(
            call for call in self.calls if call[1].endswith("/auth/v1/admin/users")
        )
        self.assertEqual(auth_create[4]["password"], temporary_password)
        for method, url, headers, _, _ in self.calls:
            if "/admin/" in url or "/rest/v1/" in url:
                self.assertEqual(headers["apikey"], "server-only-key")
                self.assertEqual(
                    headers["Authorization"], "Bearer server-only-key"
                )

    def test_create_user_accepts_two_character_and_accented_usernames(self):
        profile, _ = self.service.crear_usuario(
            "valid-access-token",
            "GP",
            "Persona Nueva",
            "Consulta",
        )
        self.assertEqual(profile["username"], "gp")

        profile, _ = self.service.crear_usuario(
            "valid-access-token",
            "José García",
            "Persona Nueva",
            "Consulta",
        )
        self.assertEqual(profile["username"], "josé garcía")

    def test_create_user_rejects_short_or_control_character_usernames(self):
        for username in ("g", "ab\ncd"):
            with self.subTest(username=username):
                with self.assertRaisesRegex(ValueError, "entre 2 y 64"):
                    self.service.crear_usuario(
                        "valid-access-token",
                        username,
                        "Persona Nueva",
                        "Consulta",
                    )

    def test_non_admin_profile_cannot_use_admin_endpoints(self):
        self.profiles[0]["role"] = "Consulta"

        with self.assertRaisesRegex(WebUserAdminError, "Solo un administrador"):
            self.service.crear_usuario(
                "valid-access-token",
                "new.user",
                "Persona Nueva",
                "Consulta",
            )

        self.assertFalse(any("/auth/v1/admin/" in call[1] for call in self.calls))

    def test_cannot_disable_self_or_last_enabled_administrator(self):
        with self.assertRaisesRegex(WebUserAdminError, "tu propia cuenta"):
            self.service.cambiar_habilitacion(
                "valid-access-token",
                self.actor_id,
                False,
            )

        self.profiles[1]["role"] = "Administrador"
        self.force_single_admin = True
        with self.assertRaisesRegex(WebUserAdminError, "último administrador"):
            self.service.cambiar_habilitacion(
                "valid-access-token",
                self.target_id,
                False,
            )

        self.assertFalse(any("/auth/v1/admin/" in call[1] for call in self.calls))

    def test_disable_bans_account_and_updates_enabled_profile(self):
        self.service.cambiar_habilitacion(
            "valid-access-token",
            self.target_id,
            False,
        )

        auth_update = next(
            call for call in self.calls if call[1].endswith("/auth/v1/admin/users/user-id")
        )
        self.assertEqual(auth_update[0], "PUT")
        self.assertEqual(auth_update[4], {"ban_duration": "876000h"})
        self.assertFalse(self.profiles[1]["enabled"])

    def test_password_reset_generates_a_new_password(self):
        password = self.service.restablecer_password(
            "valid-access-token",
            self.target_id,
        )

        auth_update = next(
            call for call in self.calls if call[1].endswith("/auth/v1/admin/users/user-id")
        )
        self.assertEqual(auth_update[0], "PUT")
        self.assertEqual(auth_update[4], {"password": password})
        self.assertGreaterEqual(len(password), 24)

    def test_password_reset_rejects_the_current_administrator(self):
        with self.assertRaisesRegex(WebUserAdminError, "propia contraseña"):
            self.service.restablecer_password(
                "valid-access-token",
                self.actor_id,
            )

        self.assertFalse(any(call[0] == "PUT" for call in self.calls))

    def test_recovery_script_resets_only_enabled_admin_account(self):
        username, password = self.service.restablecer_password_administrador_por_usuario(
            "admin",
            "Mi clave nueva segura 2026",
        )

        self.assertEqual(username, "admin")
        auth_update = next(
            call
            for call in self.calls
            if call[0] == "PUT"
            and call[1].endswith("/auth/v1/admin/users/admin-id")
        )
        self.assertEqual(auth_update[4], {"password": password})
        self.assertEqual(password, "Mi clave nueva segura 2026")

    def test_recovery_accepts_existing_short_mixed_case_username(self):
        self.profiles[0]["username"] = "GP"

        username, password = self.service.restablecer_password_administrador_por_usuario(
            "GP",
            "Mi clave nueva segura 2026",
        )

        self.assertEqual(username, "GP")
        lookup = next(
            call
            for call in self.calls
            if call[1].endswith("/rest/v1/web_profiles")
            and call[3]
            and call[3].get("username")
        )
        self.assertEqual(lookup[3]["username"], "eq.GP")
        auth_update = next(
            call
            for call in self.calls
            if call[0] == "PUT"
            and call[1].endswith("/auth/v1/admin/users/admin-id")
        )
        self.assertEqual(auth_update[4]["password"], password)

    def test_recovery_script_rejects_non_admin_accounts(self):
        self.profiles[0]["role"] = "Consulta"

        with self.assertRaisesRegex(WebUserAdminError, "no es un Administrador"):
            self.service.restablecer_password_administrador_por_usuario(
                "admin",
                "Mi clave nueva segura 2026",
            )

        self.assertFalse(any(call[0] == "PUT" for call in self.calls))

    def test_recovery_rejects_short_password_before_requesting_supabase(self):
        with self.assertRaisesRegex(ValueError, "al menos 12 caracteres"):
            self.service.restablecer_password_administrador_por_usuario(
                "admin",
                "short",
            )

        self.assertFalse(self.calls)


if __name__ == "__main__":
    unittest.main()
