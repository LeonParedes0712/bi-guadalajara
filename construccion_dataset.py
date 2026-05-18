"""
construccion_dataset.py
-----------------------
Agrupa DENUE por avenida, añade conteos por giro y calcula
variables socioeconómicas (incluyendo nse_score).

FIX: Garantiza que todas las columnas de giro existan (fill_value=0).
FIX: nse_score se calcula AQUÍ → siempre disponible antes del scoring.
FIX: flujo_comercial también se calcula aquí para consistencia.
"""

from pathlib import Path

import pandas as pd

# Giros canónicos que siempre deben existir como columnas
GIROS_CANONICOS = ["cafeteria", "gym", "restaurante", "bar_antro", "lavanderia", "otro"]


def _calcular_nse_score(dataset: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula nse_score y flujo_comercial a partir de los indicadores socioeconómicos.

    Fórmula NSE: (escolaridad × 2) + (internet × 0.5) + (prod_bruta / 1_000_000)
    Fórmula flujo: (total_negocios / max) × 100

    Requiere columnas: escolaridad, internet, prod_bruta, total_negocios.
    """
    dataset["nse_score"] = (
        dataset["escolaridad"] * 2
        + dataset["internet"] * 0.5
        + dataset["prod_bruta"] / 1_000_000
    )
    max_negocios = dataset["total_negocios"].max()
    dataset["flujo_comercial"] = (
        dataset["total_negocios"] / max_negocios * 100
        if max_negocios > 0 else 0.0
    )
    return dataset


def construir_dataset(df_denue: pd.DataFrame, indicadores: dict) -> pd.DataFrame:
    """
    Construye el dataset analítico agrupado por avenida.

    Pasos:
      1. Cuenta total de negocios por avenida.
      2. Pivota conteos por giro (columna por cada tipo).
      3. Garantiza que todos los giros canónicos existan (fill 0).
      4. Adjunta indicadores socioeconómicos como columnas escalares.
      5. Calcula nse_score y flujo_comercial.

    Args:
        df_denue:    DataFrame del DENUE con columnas 'avenida' y 'tipo'.
        indicadores: Dict con escolaridad, internet, p_joven, prod_bruta.

    Returns:
        DataFrame listo para scoring con todas las columnas garantizadas.
    """
    # --- 1. Total de negocios por avenida ---
    total = (
        df_denue
        .groupby("avenida", sort=False)
        .size()
        .reset_index(name="total_negocios")
    )

    # --- 2. Conteo por giro ---
    giros = (
        df_denue
        .groupby(["avenida", "tipo"], sort=False)
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )

    # --- 3. Merge y garantía de columnas canónicas ---
    dataset = total.merge(giros, on="avenida", how="left")

    for giro in GIROS_CANONICOS:
        if giro not in dataset.columns:
            dataset[giro] = 0  # Columna ausente → relleno con ceros

    # --- 4. Indicadores socioeconómicos (valores escalares municipales) ---
    dataset["escolaridad"]     = indicadores.get("escolaridad", 0.0)
    dataset["internet"]        = indicadores.get("internet",    0.0)
    dataset["poblacion_joven"] = indicadores.get("p_joven",     0.0)
    dataset["prod_bruta"]      = indicadores.get("prod_bruta",  0.0)

    # --- 5. NSE score y flujo comercial --- SIEMPRE calculado aquí ---
    dataset = _calcular_nse_score(dataset)

    return dataset


def guardar_dataset(dataset: pd.DataFrame, ruta_salida: Path) -> None:
    """
    Exporta el dataset a CSV.

    Args:
        dataset:     DataFrame a guardar.
        ruta_salida: Path de destino.
    """
    dataset.to_csv(ruta_salida, index=False)
    print(f"✅ Dataset guardado en: {ruta_salida}  ({len(dataset):,} avenidas)")
