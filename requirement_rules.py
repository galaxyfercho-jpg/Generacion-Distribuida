RADICACION_NO_APLICA_CATEGORIAS = frozenset(
    {
        "Ingeniería Básica",
        "Análisis Técnico",
        "Antecedentes",
    }
)


def radicacion_aplica(categoria: str | None) -> bool:
    return categoria not in RADICACION_NO_APLICA_CATEGORIAS
