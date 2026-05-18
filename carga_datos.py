"""
carga_datos.py
--------------
Carga de datos INEGI: CPV, CE y DENUE.

FIX: Rutas ahora usan pathlib.Path (no /content/).
FIX: Import de limpieza al nivel de módulo (no dentro del loop).
"""

from pathlib import Path

import pandas as pd

# Importaciones internas — limpieza no importa nada de este proyecto → sin ciclos
from limpieza import clasificar_giro, limpiar_texto

# ---------------------------------------------------------------------------
# Constantes configurables (se pueden sobreescribir desde main.py)
# ---------------------------------------------------------------------------
MUNICIPIO_OBJETIVO = "GUADALAJARA"


def buscar_valor(df: pd.DataFrame, keywords: list) -> float:
    """
    Extrae el primer valor numérico cuyo campo 'indicador' contenga alguna keyword.

    Returns:
        Float con el valor encontrado, o 0.0 si no hay coincidencia.
    """
    try:
        mask = df["indicador"].str.contains("|".join(keywords), case=False, na=False)
        valor = df[mask]["valor"].iloc[0]
        return float(str(valor).replace(",", ""))
    except (IndexError, ValueError):
        return 0.0


def cargar_indicadores_cpv_ce(
    ruta_cpv: Path,
    ruta_ce: Path,
    municipio: str = MUNICIPIO_OBJETIVO,
) -> dict:
    """
    Lee CPV y CE, filtra por municipio y extrae indicadores clave.

    Args:
        ruta_cpv:  Path al CSV del Censo de Población y Vivienda.
        ruta_ce:   Path al CSV del Censo Económico.
        municipio: Nombre del municipio en mayúsculas.

    Returns:
        Dict con claves: escolaridad, internet, p_joven, prod_bruta.
    """
    print("📊 Cargando indicadores CPV y CE...")

    cpv = pd.read_csv(ruta_cpv, encoding="latin-1")
    ce  = pd.read_csv(ruta_ce,  encoding="latin-1")

    # Filtro por municipio objetivo
    gdl_cpv = cpv[cpv["desc_municipio"].str.upper() == municipio.upper()]
    gdl_ce  = ce[ce["desc_municipio"].str.upper()  == municipio.upper()]

    indicadores = {
        "escolaridad": buscar_valor(gdl_cpv, ["escolaridad", "grado promedio"]),
        "internet":    buscar_valor(gdl_cpv, ["internet", "disponen de internet"]),
        "p_joven":     buscar_valor(gdl_cpv, ["15 a 29", "poblacion joven"]),
        "prod_bruta":  buscar_valor(gdl_ce,  ["produccion bruta total", "Producción bruta"]),
    }

    print(f"   → Indicadores obtenidos: {indicadores}")
    return indicadores


def cargar_denue_por_chunks(
    ruta_denue: Path,
    municipio: str = MUNICIPIO_OBJETIVO,
    chunksize: int = 100_000,
) -> pd.DataFrame:
    """
    Lee el DENUE en chunks (manejo de memoria), filtra por municipio,
    limpia nombres de vialidades y clasifica giros.

    Args:
        ruta_denue: Path al CSV del DENUE.
        municipio:  Municipio a filtrar (case-insensitive).
        chunksize:  Filas por chunk de lectura.

    Returns:
        DataFrame con columnas: nombre_act, avenida, municipio, tipo.
    """
    print("🔄 Procesando DENUE por chunks...")

    cols = ["nombre_act", "nom_vial", "municipio"]
    chunks_procesados = []

    for chunk in pd.read_csv(
        ruta_denue,
        encoding="latin-1",
        usecols=cols,
        chunksize=chunksize,
        low_memory=False,
    ):
        # Filtrar por municipio antes de cualquier otra operación
        mask = chunk["municipio"].str.contains(municipio, case=False, na=False)
        chunk = chunk[mask].copy()

        if chunk.empty:
            continue

        chunk["avenida"] = chunk["nom_vial"].apply(limpiar_texto)
        chunk["tipo"]    = chunk["nombre_act"].apply(clasificar_giro)
        chunks_procesados.append(chunk)

    if not chunks_procesados:
        raise ValueError(f"No se encontraron registros para municipio='{municipio}' en {ruta_denue}")

    df = pd.concat(chunks_procesados, ignore_index=True)
    print(f"   → {len(df):,} registros cargados del DENUE.")
    return df
