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
2. Sube al repositorio de GitHub `app_web.py`, `requirements.txt`, `.streamlit/config.toml`, `supabase/schema.sql`, `scripts/migrate_sqlite_to_supabase.py` y `.gitignore`. No subas `.db`, `dist`, `build`, `mi_entorno`, `.env` ni `secrets.toml`.
3. En Streamlit Community Cloud, crea una aplicación desde el repositorio, con `app_web.py` como archivo principal.
4. En la sección **Secrets** de la aplicación, agrega:

```toml
[supabase]
url = "https://TU-PROYECTO.supabase.co"
anon_key = "TU_CLAVE_PUBLICA_ANON"
```

La clave `anon` es pública; las políticas RLS son las que limitan el acceso. Nunca pongas la clave `service_role` en Streamlit, en el código o en GitHub.

## Importación inicial

En PowerShell, desde la carpeta del proyecto, introduce la clave con `Read-Host -AsSecureString`; no se mostrará ni quedará en el historial del comando:

```powershell
$secureKey = Read-Host "Clave service_role de Supabase" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
	$env:SUPABASE_SERVICE_ROLE_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
	.\mi_entorno\Scripts\python.exe scripts\migrate_sqlite_to_supabase.py --database "dist\sistema_gd_v4.db"
} finally {
	Remove-Item Env:\SUPABASE_SERVICE_ROLE_KEY -ErrorAction SilentlyContinue
	[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
	$secureKey.Dispose()
}
```

La URL se lee desde `.streamlit/secrets.toml`; el comando no la imprime. Supabase Auth almacena las contraseñas con hash. Para no exigir correo, cada nombre de usuario se transforma en un alias técnico interno; la recuperación de contraseña deberá hacerla un administrador.

La importación conserva los IDs y puede repetirse para actualizar el contenido de las tablas. La base seleccionada inicialmente es `dist\sistema_gd_v4.db`. La migración importa los datos de las tablas, pero no copia los archivos señalados por `evidencia_ruta` y `evidencia_respuesta`.

## Estado actual y pendientes

La interfaz web presenta el resumen, el consolidado agrupado por clúster y el detalle del proyecto con un estilo inspirado en la aplicación de escritorio. La sección **Gestor de soportes** informa que la conexión documental aún está pendiente; todavía no permite abrir archivos.

Los adjuntos del escritorio son rutas a archivos del equipo, no archivos alojados en Supabase. Se eligió OneDrive/SharePoint de Microsoft 365 para el repositorio privado, pero su integración requiere que el administrador de Microsoft 365 apruebe una aplicación y su acceso a la biblioteca. No se deben crear enlaces públicos para evitar esa autorización. Hasta completar esa configuración, los documentos no estarán disponibles desde la web.

La aplicación de escritorio todavía escribe en SQLite local, por lo que sus cambios posteriores a la importación no aparecen automáticamente en la web. Para la sincronización continua, el cliente de escritorio deberá conectarse a una API central autenticada y Supabase tendrá que autorizar las operaciones de escritura por rol. No se debe incluir la clave `service_role` en un ejecutable ni en el repositorio.

## Aplicación Android de consulta

`app_movil.py` es el cliente Flet para Android y tablets. Se conecta directamente a Supabase por HTTPS, usa Supabase Auth y solo consulta datos. No funciona fuera de línea ni escribe en la base. La clave `anon` se incorpora al paquete mediante `scripts/build_mobile_apk.py`; es una clave pública y el acceso depende de las políticas RLS. La clave `service_role` nunca debe incorporarse a la APK.

En Windows, con Python y el entorno virtual del proyecto activos:

1. Instala las dependencias móviles y Flet CLI: `.\mi_entorno\Scripts\python.exe -m pip install -r requirements-mobile.txt "flet[cli]>=1.0.4,<2"`.
2. Ejecuta `.\mi_entorno\Scripts\python.exe scripts\build_mobile_apk.py`. El script prepara el código en `%TEMP%\gestor_gd_mobile_apk_source` —fuera de OneDrive para evitar errores de Dart en rutas sincronizadas o con acentos— y ejecuta `flet build apk`.
3. En el primer build, Flet puede instalar Flutter, JDK 17 y Android SDK si aún no están disponibles. Se necesita internet y varios GB libres.
4. Busca el APK resultante en `build\mobile_apk` y transfiérelo al dispositivo Android para instalarlo.

La aplicación requiere internet y utiliza la contraseña web de Supabase Auth, que puede ser distinta de la contraseña local de escritorio. Los cambios de escritorio solo aparecerán en la app después de sincronizarlos con Supabase. Los documentos todavía no están disponibles en el móvil. El dashboard separa capacidad ejecutada y proyectada con el mismo criterio del escritorio: un proyecto se clasifica como ejecutado cuando todos sus requisitos aplicables están completados. Esa capacidad no representa una medición de energía producida.