import altair as alt
import pandas as pd


def _valor_activo(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().casefold() in {"1", "true", "sí", "si", "yes"}


def calcular_avance_por_cluster(
    proyectos: pd.DataFrame,
    requisitos: pd.DataFrame,
) -> pd.DataFrame:
    columnas = ["cluster", "avance", "completados", "total", "proyectos"]
    if proyectos.empty or requisitos.empty:
        return pd.DataFrame(columns=columnas)

    activos = proyectos.copy()
    activos["estado_general"] = activos["estado_general"].fillna("").astype(str).str.strip().str.upper()
    activos = activos[~activos["estado_general"].isin({"PAUSADO", "DESCARTADO"})].copy()
    if activos.empty:
        return pd.DataFrame(columns=columnas)

    activos["cluster"] = activos["cluster"].fillna("").astype(str).str.strip()
    activos.loc[
        activos["cluster"].str.casefold().isin({"", "n/a", "individual"}),
        "cluster",
    ] = "Proyectos individuales"

    aplicables = requisitos.merge(
        activos[["id", "cluster", "req_servidumbre", "req_contrato"]],
        left_on="proyecto_id",
        right_on="id",
        how="inner",
    )
    aplicables["categoria"] = aplicables["categoria"].fillna("").astype(str).str.strip()
    aplicables = aplicables[
        ~aplicables["categoria"].isin({"Ingeniería Básica", "Análisis Técnico"})
    ]
    aplicables = aplicables[
        ~(
            (aplicables["categoria"] == "Servidumbre")
            & ~aplicables["req_servidumbre"].map(_valor_activo)
        )
    ]
    aplicables = aplicables[
        ~(
            (aplicables["categoria"] == "Modelo de Contrato")
            & ~aplicables["req_contrato"].map(_valor_activo)
        )
    ]
    if aplicables.empty:
        return pd.DataFrame(columns=columnas)

    aplicables["estado"] = aplicables["estado"].fillna("").astype(str).str.strip().str.upper()
    resultado = (
        aplicables.groupby("cluster", as_index=False)
        .agg(
            total=("estado", "size"),
            completados=("estado", lambda valores: int((valores == "COMPLETADO").sum())),
            proyectos=("proyecto_id", "nunique"),
        )
    )
    resultado["avance"] = resultado["completados"] / resultado["total"] * 100
    return resultado.sort_values(
        ["avance", "total", "cluster"],
        ascending=[False, False, True],
        ignore_index=True,
    )[columnas]


def crear_grafico_avance(avance: pd.DataFrame) -> alt.LayerChart:
    datos = avance.rename(
        columns={
            "cluster": "Clúster",
            "avance": "Avance",
            "completados": "Completados",
            "total": "Total",
            "proyectos": "Proyectos",
        }
    ).copy()
    datos["etiqueta"] = datos.apply(
        lambda fila: (
            f"{fila['Avance']:.0f}% · "
            f"{int(fila['Completados'])}/{int(fila['Total'])}"
        ),
        axis=1,
    )
    orden = alt.SortField(field="Avance", order="descending")
    barras = (
        alt.Chart(datos)
        .mark_bar(color="#3c9657", cornerRadiusEnd=6, size=22)
        .encode(
            x=alt.X(
                "Avance:Q",
                scale=alt.Scale(domain=[0, 115]),
                axis=alt.Axis(
                    title="Avance de requisitos",
                    values=[0, 25, 50, 75, 100],
                    labelExpr="datum.value + '%'",
                    grid=True,
                ),
            ),
            y=alt.Y(
                "Clúster:N",
                sort=orden,
                axis=alt.Axis(title=None, labelLimit=280, labelFontSize=12),
            ),
            tooltip=[
                alt.Tooltip("Clúster:N", title="Agrupación"),
                alt.Tooltip("Avance:Q", title="Avance (%)", format=".1f"),
                alt.Tooltip("Completados:Q", title="Requisitos completados"),
                alt.Tooltip("Total:Q", title="Requisitos aplicables"),
                alt.Tooltip("Proyectos:Q", title="Proyectos activos"),
            ],
        )
    )
    etiquetas = (
        alt.Chart(datos)
        .mark_text(
            align="left",
            baseline="middle",
            dx=7,
            fontSize=12,
            fontWeight="bold",
            color="#263746",
        )
        .encode(
            x=alt.X("Avance:Q", scale=alt.Scale(domain=[0, 115])),
            y=alt.Y("Clúster:N", sort=orden),
            text=alt.Text("etiqueta:N"),
        )
    )
    return (barras + etiquetas).properties(
        height=max(220, min(620, len(datos) * 44))
    )
