# Portal web de consulta

## Componentes

- Streamlit Community Cloud sirve `app_web.py`.
- Supabase Auth valida el nombre de usuario y la contraseña.
- PostgreSQL de Supabase guarda los datos importados.
- `supabase/schema.sql` crea tablas y políticas RLS de solo lectura.
- `scripts/migrate_sqlite_to_supabase.py` importa la copia seleccionada de SQLite.

El portal usa la clave pública `anon` y el token de la sesión para consultar datos con RLS. La sección de administración de usuarios también necesita la clave `service_role`, exclusivamente en el servidor Streamlit: nunca se envía al navegador, al móvil, al ejecutable ni a GitHub.

## Configuración

1. En Supabase, abre el SQL Editor y ejecuta el contenido de `supabase/schema.sql`.
2. Sube al repositorio de GitHub `app_web.py` y todos sus módulos locales importados: `web_dashboard.py`, `requirement_rules.py` y `web_user_admin.py`, además de `logo_INGEV.png`, `requirements.txt`, `.streamlit/config.toml`, `supabase/schema.sql`, `scripts/migrate_sqlite_to_supabase.py` y `.gitignore`. No subas `.db`, `dist`, `build`, `mi_entorno`, `.env` ni `secrets.toml`.
3. En Streamlit Community Cloud, crea una aplicación desde el repositorio, con `app_web.py` como archivo principal.
4. En la sección **Secrets** de la aplicación, agrega:

```toml
[supabase]
url = "https://TU-PROYECTO.supabase.co"
anon_key = "TU_CLAVE_PUBLICA_ANON"
service_role_key = "TU_CLAVE_PRIVADA_DE_SERVIDOR"
```

En Streamlit Community Cloud, configura estos valores en **App settings > Secrets**. La clave privada se usa solo desde el proceso servidor para gestionar cuentas; no la pongas en el código, GitHub, variables enviadas al navegador, aplicación móvil ni ejecutable. Para desarrollo local, el archivo `.streamlit/secrets.toml` está excluido de Git. No copies esa clave a `.streamlit/desktop_sync.toml`.

Si `service_role_key` no está configurada, el portal seguirá permitiendo la consulta normal, pero mostrará que la administración de usuarios requiere configuración.

Si Streamlit muestra `ModuleNotFoundError` al importar `requirement_rules` o `web_user_admin`, confirma que esos archivos `.py` estén en la raíz del mismo repositorio y rama que `app_web.py`, y que los últimos cambios estén enviados a GitHub. Después, reinicia la aplicación desde Streamlit Community Cloud. Son módulos locales del proyecto; no se instalan con `requirements.txt`.

## Administración de usuarios web

Las cuentas se administran desde la sección **Administración de usuarios**, visible para las cuentas habilitadas con el rol exacto `Administrador`.

- **Crear usuario:** registra la cuenta de Supabase Auth y su perfil web en una sola operación lógica. El portal genera una contraseña temporal de alta entropía y la muestra en la sesión del administrador para compartirla con la persona por un canal privado. Los nombres de usuario nuevos aceptan de 2 a 64 caracteres: letras (incluidas las acentuadas), números, espacios, punto, guion, guion bajo, `@` y `+`. Se guardan en minúsculas.
- **Rol Consulta:** solo permite leer información.
- **Rol Administrador:** además puede publicar cambios desde el escritorio.
- **Restablecer contraseña:** genera una contraseña temporal nueva; la contraseña previa deja de funcionar. La clave temporal se muestra en la sesión para entregarla de manera privada.
- Por seguridad, un administrador no puede restablecer su propia contraseña desde la sesión web activa: Supabase puede cerrar esa sesión antes de que el portal alcance a mostrar la contraseña nueva. Para recuperar una cuenta Administrador cuando no se puede iniciar sesión, usa la utilidad local descrita abajo.
- **Deshabilitar/habilitar:** deshabilita o habilita el perfil y bloquea o desbloquea el acceso de Supabase Auth. No se permite deshabilitar la propia cuenta ni dejar el sistema sin un administrador habilitado.

El portal no envía correos de invitación o recuperación: las cuentas utilizan alias internos y no requieren una dirección de correo real. El administrador debe entregar las contraseñas temporales fuera del portal y ocultarlas después de compartirlas. La habilitación del panel no cambia las contraseñas de las cuentas existentes.

### Recuperar la contraseña de un administrador bloqueado

Si un restablecimiento cerró la sesión y la contraseña nueva no alcanzó a mostrarse, ejecuta en una copia local autorizada del proyecto:

```powershell
.\mi_entorno\Scripts\python.exe scripts\reset_web_admin_password.py
```

La utilidad solicita el nombre de usuario existente y la contraseña nueva dos veces mediante entradas ocultas, además de pedir la clave `service_role` también de forma oculta. Acepta nombres antiguos aunque tengan mayúsculas o menos de tres caracteres; escribe el usuario tal como aparece en el inicio de sesión. La clave y la contraseña se usan únicamente en memoria; no se escriben en archivos ni en el historial del comando. El script valida que el usuario sea un Administrador habilitado y establece la contraseña que ingresaste (mínimo 12 caracteres). Después podrás iniciar sesión con ella. No pegues la clave `service_role` ni la contraseña en chats ni repositorios.

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

La importación conserva los IDs y puede repetirse para actualizar el contenido de las tablas. Los perfiles se actualizan por el ID local de usuario (`source_user_id`); si cambia el nombre de usuario local, el migrador crea o reutiliza su cuenta de Supabase Auth y vincula el perfil a ella. La base seleccionada inicialmente es `dist\sistema_gd_v4.db`. La migración importa los datos de las tablas, pero no copia los archivos señalados por `evidencia_ruta` y `evidencia_respuesta`.

## Estado actual y pendientes

La interfaz web presenta el resumen, el consolidado agrupado por clúster y el detalle del proyecto con un estilo inspirado en la aplicación de escritorio. La sección **Gestor de soportes** informa que la conexión documental aún está pendiente; todavía no permite abrir archivos.

Los adjuntos del escritorio son rutas a archivos del equipo, no archivos alojados en Supabase. Se eligió OneDrive/SharePoint de Microsoft 365 para el repositorio privado, pero su integración requiere que el administrador de Microsoft 365 apruebe una aplicación y su acceso a la biblioteca. No se deben crear enlaces públicos para evitar esa autorización. Hasta completar esa configuración, los documentos no estarán disponibles desde la web.

En la aplicación de escritorio, **Exportación > Descargar proyecto completo** genera un ZIP compatible con WinRAR, con el nombre del proyecto y la fecha de exportación. Conserva las carpetas de categorías del aplicativo (`Trámites de Terreno`, `Trámites OR`, `Servidumbre`, `Modelo de Contrato`, `Análisis Técnico`, `Ingeniería Básica` y `Antecedentes`), y crea dentro de cada requisito las subcarpetas `Radicado` y `Respuesta`. Incluye también carpetas vacías; `Servidumbre` y `Modelo de Contrato` aparecen solo cuando están habilitados para el proyecto. Si una ruta guardada ya no existe, la aplicación permite localizar el archivo sustituto antes de exportar. Al confirmar, un administrador también corrige la ruta guardada; las cuentas de consulta pueden usar la sustitución solo para ese ZIP. Si se cancela la búsqueda de un archivo, no se genera una exportación incompleta.

La aplicación de escritorio todavía escribe en SQLite local, por lo que sus cambios posteriores a la importación no aparecen automáticamente en la web. Para la sincronización continua, el cliente de escritorio deberá conectarse a una API central autenticada y Supabase tendrá que autorizar las operaciones de escritura por rol. No se debe incluir la clave `service_role` en un ejecutable ni en el repositorio.

### Sincronización del escritorio entre varios equipos

El objetivo acordado es que el computador principal sea el único que modifica la información y que otras instalaciones del escritorio sean de consulta. La base SQLite no debe compartirse por OneDrive.

El archivo `supabase/desktop_sync_policies.sql` prepara permisos de escritura en `clusteres`, `proyectos` y `requisitos` únicamente para usuarios autenticados cuyo perfil esté habilitado y tenga el rol exacto `Administrador`. Las cuentas de consulta de web y móvil conservan sus permisos de lectura. El script no modifica datos ni concede escritura en `web_profiles`. Ya ejecutaste este script y Supabase respondió “Success. No rows returned”; no es necesario ejecutarlo otra vez.

El cliente de escritorio usa Supabase Auth y la clave pública `anon`; nunca utiliza la clave `service_role`. Al iniciar sesión sincronizada:

1. Una cuenta `Administrador` publica a Supabase la base local de esa computadora. Antes de publicar, la aplicación pide confirmación y guarda un respaldo local. Los guardados posteriores se envían automáticamente.
2. Cualquier otro rol descarga los datos y abre el escritorio en modo de consulta. La descarga inicial reemplaza la copia SQLite local y crea un respaldo previo; con la sesión abierta, el escritorio vuelve a descargar y refrescar la vista cada 30 segundos, sin crear respaldos repetidos.
3. La opción **Ingresar solo en esta computadora** conserva el uso local, pero no sincroniza.

La publicación y la descarga de inicio de sesión se ejecutan en segundo plano para que la ventana no quede congelada. El escritorio muestra un aviso mientras espera a Supabase y solo abre el portafolio cuando la operación termina; si falla, deja la sesión en la pantalla de acceso y muestra el error. Si una publicación falla, verifica primero el estado de los datos en Supabase antes de volver a intentarla, porque algunas operaciones pueden haberse aplicado antes del error.

Para conectar el ejecutable, crea `.streamlit/desktop_sync.toml` junto al proyecto o junto al `.exe`, usando `supabase/desktop_sync_config.example.toml` como plantilla y colocando únicamente la URL del proyecto y la clave pública `anon`. Ambos valores deben pertenecer al mismo proyecto de Supabase usado por web y móvil; no uses la dirección de Streamlit Community Cloud como URL. No pongas la clave `service_role` allí. Este archivo local está excluido de Git. La contraseña y la sesión de Supabase no se guardan en el equipo; se inicia sesión al abrir el programa.

La aplicación web y móvil consultan la información guardada en Supabase automáticamente cada 30 segundos mientras la sesión está abierta. El escritorio en modo de consulta también descarga los cambios con esa frecuencia. El móvil conserva su botón de actualización manual. Esta sincronización es periódica, no instantánea, y usa las consultas autenticadas existentes: no requiere habilitar Supabase Realtime ni volver a ejecutar las políticas SQL. Si no hay conexión, cada cliente conserva la última vista disponible e informa del error.

La sincronización de registros no carga los documentos adjuntos: `evidencia_ruta` y `evidencia_respuesta` aún son rutas locales y la integración con OneDrive/SharePoint sigue pendiente. Los respaldos y la copia SQLite de cada computador tampoco se comparten.

La aplicación de escritorio alerta y bloquea la creación o el renombrado de proyectos con nombres repetidos, y el guardado de radicados OR ya asignados a otro proyecto. La comparación ignora mayúsculas/minúsculas y espacios repetidos. Esto previene nuevos duplicados desde el escritorio, pero no elimina ni corrige duplicados históricos; esos registros deben identificarse y depurarse por separado antes de considerarlos confiables.

El modo oscuro se reaplica al abrir módulos, controles dinámicos y ventanas emergentes; el selector de exportación PDF y el formulario de datos OR conservan fondos, campos y textos legibles en ambos temas. El dashboard muestra un velocímetro de generación acumulada EN OPERACIÓN en kW, inicia en el clúster con más proyectos en operación y agrupa los proyectos individuales en una sola categoría de avance. Los informes Excel ejecutivo y Gantt incluyen el logo de INGEV en el encabezado; por ahora no llevan código SIG.

La versión vigente del escritorio se distribuye como `dist/app_escritorio.exe`. Antes de retirar versiones anteriores, cierra las ventanas de escritorio que sigan abiertas para no interrumpir una sesión que esté usando la base local.

El estado **EN OPERACIÓN** se marca manualmente por un administrador después de confirmar que el proyecto ya inyecta energía y de que los requisitos OR 2.1–2.4 estén completados. Ese estado se sincroniza como `proyectos.en_operacion`; al actualizar un proyecto existente de Supabase, vuelve a ejecutar `supabase/schema.sql` para añadir la columna. Los proyectos pausados o descartados no aportan requisitos a los cálculos de avance/exportación: en Excel, PDF y Gantt se conservan como resumen de nombre, estado y observación del requisito 2.2. El Gantt permite exportar todos los clústeres y proyectos individuales en un único libro de Excel.

## Aplicación Android de consulta

`app_movil.py` es el cliente Flet para Android y tablets. Se conecta directamente a Supabase por HTTPS, usa Supabase Auth y solo consulta datos. No funciona fuera de línea ni escribe en la base. La clave `anon` se incorpora al paquete mediante `scripts/build_mobile_apk.py`; es una clave pública y el acceso depende de las políticas RLS. La clave `service_role` nunca debe incorporarse a la APK.

En Windows, con Python y el entorno virtual del proyecto activos:

1. Instala las dependencias móviles y Flet CLI: `.\mi_entorno\Scripts\python.exe -m pip install -r requirements-mobile.txt "flet[cli]>=1.0.4,<2"`.
2. Ejecuta `.\mi_entorno\Scripts\python.exe scripts\build_mobile_apk.py`. El script prepara el código en `%TEMP%\gestor_gd_mobile_apk_source` —fuera de OneDrive para evitar errores de Dart en rutas sincronizadas o con acentos— y ejecuta `flet build apk`.
3. En el primer build, Flet puede instalar Flutter, JDK 17 y Android SDK si aún no están disponibles. Se necesita internet y varios GB libres.
4. Busca el APK resultante en `build\mobile_apk` y transfiérelo al dispositivo Android para instalarlo.

La aplicación requiere internet y utiliza la contraseña web de Supabase Auth, que puede ser distinta de la contraseña local de escritorio. Los cambios de escritorio solo aparecerán en la app después de sincronizarlos con Supabase. Los documentos todavía no están disponibles en el móvil. El dashboard separa capacidad ejecutada y proyectada con el mismo criterio del escritorio: un proyecto se clasifica como ejecutado cuando todos sus requisitos aplicables están completados. Esa capacidad no representa una medición de energía producida.