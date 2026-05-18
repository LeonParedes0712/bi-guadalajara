"""
visualizacion.py
----------------
Presentación de resultados: tabla de ranking, diagnóstico por zona
y gráfica de componentes apilados.

Sin dependencias internas → importable desde cualquier módulo.
"""

import matplotlib.pyplot as plt
import pandas as pd


def imprimir_ranking(top: pd.DataFrame, giro: str) -> None:
    """
    Imprime tabla de ranking y diagnóstico por avenida en consola.

    Args:
        top:  DataFrame con el top N de avenidas (salida de simulador_pro_v2).
        giro: Nombre del giro evaluado.
    """
    print(f"\n🏆 RANKING ESTRATÉGICO PARA {giro.upper()}:")
    print("=" * 90)

    # Tabla comparativa — solo columnas que existan
    tabla_cols = [
        "avenida",
        "score_final",
        "score_demanda",
        "score_validacion",
        "penalizacion_ruido",
        "penalizacion_saturacion",
    ]
    cols_presentes = [c for c in tabla_cols if c in top.columns]

    print(top[cols_presentes].to_string(
        index=False,
        formatters={
            "score_final":             "{:,.2f}".format,
            "score_demanda":           "{:,.1f}".format,
            "score_validacion":        "{:,.1f}".format,
            "penalizacion_ruido":      "{:,.1f}".format,
            "penalizacion_saturacion": "{:,.1f}".format,
        },
    ))
    print("\n" + "=" * 90)

    for _, row in top.iterrows():
        print(f"📍 {row['avenida']} | Score Final: {round(row['score_final'], 1)}")

        pros, cons = [], []

        if row.get("score_validacion", 0) > 10:
            pros.append("Mercado validado (presencia del giro)")
        if row.get("score_demanda", 0) > 70:
            pros.append("Zona de alto tráfico comercial")
        if row.get("score_compatibilidad", 0) > 15:
            pros.append("Afinidad con perfil socioeconómico")

        if row.get("penalizacion_saturacion", 0) > 0:
            cons.append(f"Saturación detectada (supera percentil 75 de {giro}s)")
        if row.get("penalizacion_ruido", 0) > 10:
            cons.append("Ambiente con alto ruido industrial/talleres")

        print(f"   ✅ PROS: {', '.join(pros) if pros else 'Estabilidad de zona'}")
        print(f"   ⚠️  CONSIDERAR: {', '.join(cons) if cons else 'Competencia equilibrada'}")
        print("-" * 90)


def graficar_ranking(top: pd.DataFrame, giro: str) -> None:
    """
    Gráfica de barras horizontales con desglose de componentes positivos por avenida.

    Args:
        top:  DataFrame con el top N de avenidas.
        giro: Nombre del giro (usado en el título).
    """
    cols_grafica   = ["score_demanda", "score_validacion", "score_compatibilidad"]
    cols_presentes = [c for c in cols_grafica if c in top.columns]

    if not cols_presentes:
        print("⚠️  Sin columnas de score para graficar.")
        return

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12, 6))

    top.plot(
        x="avenida",
        y=cols_presentes,
        kind="barh",
        stacked=True,
        ax=ax,
        colormap="winter",
    )

    ax.set_title(
        f"Desglose de Potencial Comercial por Avenida — {giro.capitalize()}",
        fontsize=15,
    )
    ax.set_xlabel("Puntos Acumulados (componentes positivos)")
    plt.tight_layout()
    plt.show()
