# Portal web de consulta

## Componentes

- Streamlit Community Cloud sirve `app_web.py`.
- Supabase Auth valida el nombre de usuario y la contraseña.
- PostgreSQL de Supabase guarda los datos importados.
- `supabase/schema.sql` crea tablas y políticas RLS de solo lectura.
- `scripts/migrate_sqlite_to_supabase.py` importa la copia seleccionada de SQLite.

La web no recibe la clave `service_role`. Solo utiliza la clave pública `anon` y el token de la sesión, con RLS habilitado.

## Configuración

1. En Supabase, abre el SQL Editor y ejecuta el contenido de `supabase/schema.sql`.
2. Sube al repositorio de GitHub `app_web.py`, `requirements.txt`, `supabase/schema.sql`, `scripts/migrate_sqlite_to_supabase.py` y `.gitignore`. No subas `.db`, `dist`, `build`, `mi_entorno`, `.env` ni `secrets.toml`.
3. En Streamlit Community Cloud, crea una aplicación desde el repositorio, con `app_web.py` como archivo principal.
4. En la sección **Secrets** de la aplicación, agrega:

```toml
[supabase]
url = "https://TU-PROYECTO.supabase.co"
anon_key = "TU_CLAVE_PUBLICA_ANON"
```

La clave `anon` es pública; las políticas RLS son las que limitan el acceso. Nunca pongas la clave `service_role` en Streamlit, en el código o en GitHub.

## Importación inicial

En PowerShell, desde la carpeta del proyecto, ejecuta:

```powershell
.\mi_entorno\Scripts\python.exe scripts\migrate_sqlite_to_supabase.py --database "dist\sistema_gd_v4.db" --url "https://TU-PROYECTO.supabase.co"
```

El script pedirá la clave `service_role` con entrada oculta. Escríbela directamente en PowerShell; no la pegues en el chat. Supabase Auth almacena las contraseñas con hash. Para no exigir correo, cada nombre de usuario se transforma en un alias técnico interno; la recuperación de contraseña deberá hacerla un administrador.

La importación conserva los IDs y puede repetirse para actualizar el contenido de las tablas. La base seleccionada inicialmente es `dist\sistema_gd_v4.db`.

## Límite actual

Este portal es de solo lectura y la importación no crea sincronización continua. Las aplicaciones de escritorio y móvil todavía escriben en SQLite local: los cambios posteriores no aparecerán automáticamente en la web. Para cumplir sincronización inmediata, hay que modificar ambos clientes para usar una API central autenticada y definir qué aplicación puede crear, editar o borrar datos. No se debe solucionar poniendo `service_role` dentro del `.exe` o de la app móvil.