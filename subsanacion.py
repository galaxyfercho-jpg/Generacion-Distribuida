import datetime

DIAS_SUBSANACION = 10
ESTADO_SUBSANACION = "EN SUBSANACIONES"
REQUISITO_SUBSANACION = "2.1"
FORMATO_FECHA = "%d/%m/%Y"


def _domingo_pascua(anio: int) -> datetime.date:
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (a + 11 * h) // 319
    r = (2 * e + 2 * i - k - h + m + 32) % 7
    mes = (h - m + r + 90) // 25
    dia = (h - m + r + mes + 19) % 32
    return datetime.date(anio, mes, dia)


def _lunes_siguiente(fecha: datetime.date) -> datetime.date:
    return fecha + datetime.timedelta(days=(7 - fecha.weekday()) % 7)


def festivos_colombia(anio: int) -> frozenset:
    pascua = _domingo_pascua(anio)
    dia = datetime.timedelta
    fijos = [
        datetime.date(anio, 1, 1),
        datetime.date(anio, 5, 1),
        datetime.date(anio, 7, 20),
        datetime.date(anio, 8, 7),
        datetime.date(anio, 12, 8),
        datetime.date(anio, 12, 25),
        pascua - dia(days=3),
        pascua - dia(days=2),
    ]
    trasladables = [
        datetime.date(anio, 1, 6),
        datetime.date(anio, 3, 19),
        datetime.date(anio, 6, 29),
        datetime.date(anio, 8, 15),
        datetime.date(anio, 10, 12),
        datetime.date(anio, 11, 1),
        datetime.date(anio, 11, 11),
        pascua + dia(days=39),
        pascua + dia(days=60),
        pascua + dia(days=68),
    ]
    return frozenset(fijos + [_lunes_siguiente(f) for f in trasladables])


def es_dia_habil(fecha: datetime.date) -> bool:
    return fecha.weekday() < 5 and fecha not in festivos_colombia(fecha.year)


def sumar_dias_habiles_colombia(
    fecha_inicio: datetime.date, dias: int
) -> datetime.date:
    actual, agregados = fecha_inicio, 0
    while agregados < dias:
        actual += datetime.timedelta(days=1)
        if es_dia_habil(actual):
            agregados += 1
    return actual


def parsear_fecha(texto) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(str(texto).strip(), FORMATO_FECHA).date()
    except (TypeError, ValueError):
        return None


def vencimiento_subsanacion(fecha_observaciones) -> datetime.date | None:
    recibida = parsear_fecha(fecha_observaciones)
    if recibida is None:
        return None
    return sumar_dias_habiles_colombia(recibida, DIAS_SUBSANACION)


def dias_habiles_restantes(
    vencimiento: datetime.date, hoy: datetime.date | None = None
) -> int:
    """Positivo: días hábiles que faltan. Negativo: días hábiles de retraso."""
    hoy = hoy or datetime.date.today()
    if vencimiento >= hoy:
        desde, hasta, signo = hoy, vencimiento, 1
    else:
        desde, hasta, signo = vencimiento, hoy, -1
    total, actual = 0, desde
    while actual < hasta:
        actual += datetime.timedelta(days=1)
        if es_dia_habil(actual):
            total += 1
    return signo * total


def es_requisito_subsanacion(descripcion) -> bool:
    return str(descripcion or "").strip().startswith(REQUISITO_SUBSANACION + " ")


def estado_subsanacion(fecha_observaciones, hoy: datetime.date | None = None):
    """Devuelve (vencimiento, dias_restantes, vencida) o None sin fecha."""
    vence = vencimiento_subsanacion(fecha_observaciones)
    if vence is None:
        return None
    restantes = dias_habiles_restantes(vence, hoy)
    return vence, restantes, restantes < 0


def texto_alerta(fecha_observaciones, hoy: datetime.date | None = None) -> str:
    info = estado_subsanacion(fecha_observaciones, hoy)
    if info is None:
        return "Sin fecha de recepción de observaciones"
    vence, restantes, vencida = info
    fecha = vence.strftime(FORMATO_FECHA)
    if vencida:
        return f"VENCIDA hace {abs(restantes)} día(s) hábil(es) (venció {fecha})"
    if restantes == 0:
        return f"VENCE HOY ({fecha})"
    return f"Vence {fecha}: {restantes} día(s) hábil(es)"
