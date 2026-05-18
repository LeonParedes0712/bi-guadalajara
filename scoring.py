"""
scoring.py
----------
Motor de scoring de rentabilidad comercial por avenida.

FIX: Si nse_score no está en el dataset, se calcula internamente.
FIX: Si la columna del giro no existe, se rellena con 0 (no crash).
FIX: calcular_nse_score movido a construccion_dataset; aquí solo se
     usa como fallback de seguridad.

NUEVO — Capa de percepción humana:
  Si existe percepcion_resumen.csv, se hace merge con el dataset y
  el score_final se calcula como:
      score_final = score_modelo * 0.80 + score_humano_norm * 0.20
  Si una avenida no tiene datos humanos, se usa score_humano = 6.42
  (media observada del dataset de percepción), que equivale a un
  valor neutral sin sesgar el ranking.
  Si el archivo no existe, el pipeline funciona exactamente igual
  que antes (score_modelo = score_final).

Sin dependencias de otros módulos del proyecto → sin ciclos de import.
"""

from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Ruta al archivo de percepción (relativa al propio scoring.py)
# ---------------------------------------------------------------------------
RUTA_PERCEPCION = Path(__file__).parent / "percepcion_resumen.csv"

# Valor neutral de score_humano para avenidas sin datos de encuesta.
# Equivale a la media observada del dataset (≈ punto medio de la escala).
SCORE_HUMANO_NEUTRAL = 6.42

# Pesos del score final
PESO_MODELO     = 0.80
PESO_PERCEPCION = 0.20


# ---------------------------------------------------------------------------
# Pesos por giro — multiplicadores sobre cada componente del score base
# ---------------------------------------------------------------------------
PESOS_GIRO: dict = {
    "cafeteria": {
        "demanda":        1.2,  # tráfico peatonal muy relevante
        "validacion":     1.0,
        "compatibilidad": 0.8,
        "ruido":          1.0,
        "saturacion":     1.0,
    },
    "gym": {
        "demanda":        0.9,
        "validacion":     1.1,
        "compatibilidad": 1.3,  # membresías dependen del NSE
        "ruido":          0.7,
        "saturacion":     1.2,
    },
    "restaurante": {
        "demanda":        1.3,
        "validacion":     1.0,
        "compatibilidad": 0.9,
        "ruido":          1.1,
        "saturacion":     1.0,
    },
    "bar_antro": {
        "demanda":        1.4,  # volumen de tráfico crítico
        "validacion":     0.9,
        "compatibilidad": 0.7,
        "ruido":          0.5,  # bares toleran más ruido comercial
        "saturacion":     1.1,
    },
    "lavanderia": {
        "demanda":        0.8,
        "validacion":     1.2,
        "compatibilidad": 1.0,
        "ruido":          1.3,  # sensible a zonas industriales
        "saturacion":     0.9,
    },
}

# Pesos neutros para giros no especificados
PESOS_DEFAULT: dict = {
    "demanda":        1.0,
    "validacion":     1.0,
    "compatibilidad": 1.0,
    "ruido":          1.0,
    "saturacion":     1.0,
}

# Avenidas excluidas por baja representatividad estadística
LISTA_NEGRA: list = [
    "DIONISIO RODRIGUEZ",
    "ALVARO OBREGON",
    "MEDRANO",
    "OBREGON",
    "GIGANTES",
    "FEDERICO MEDRANO",
]


# ---------------------------------------------------------------------------
# CARGA DE PERCEPCIÓN HUMANA
# ---------------------------------------------------------------------------

def _cargar_percepcion(ruta: Path) -> pd.DataFrame | None:
    """
    Carga percepcion_resumen.csv si existe.

    Retorna un DataFrame con columnas ['avenida', 'score_humano'],
    o None si el archivo no existe.

    La columna 'avenida' se normaliza a mayúsculas para garantizar
    el merge con el dataset principal (que viene del DENUE en mayúsculas).
    """
    if not ruta.exists():
        print("  ⚠️  percepcion_resumen.csv no encontrado — se omite capa de percepción.")
        return None

    df = pd.read_csv(ruta, usecols=["avenida", "score_humano"])
    df["avenida"] = df["avenida"].str.upper().str.strip()
    print(f"  📊 Percepción cargada: {len(df)} avenidas desde {ruta.name}")
    return df


def _integrar_percepcion(data: pd.DataFrame, percepcion: pd.DataFrame | None) -> pd.DataFrame:
    """
    Hace merge del dataset principal con la capa de percepción.

    - Si percepcion es None: score_humano = 0.0 (no suma ni resta).
    - Si una avenida no tiene registro en percepcion: score_humano = SCORE_HUMANO_NEUTRAL.
    - La columna 'avenida' del dataset se normaliza previamente para el merge.

    No modifica el dataset original (trabaja sobre copia).
    """
    d = data.copy()

    # Normalizar avenida en el dataset principal para el merge
    d["avenida"] = d["avenida"].str.upper().str.strip()

    if percepcion is None:
        d["score_humano"] = 0.0
        return d

    d = d.merge(percepcion[["avenida", "score_humano"]], on="avenida", how="left")

    # Avenidas sin datos de encuesta reciben el valor neutral
    n_sin_datos = d["score_humano"].isna().sum()
    if n_sin_datos > 0:
        print(f"  ℹ️  {n_sin_datos} avenida(s) sin datos de percepción → score_humano = {SCORE_HUMANO_NEUTRAL}")
    d["score_humano"] = d["score_humano"].fillna(SCORE_HUMANO_NEUTRAL)

    return d


# ---------------------------------------------------------------------------
# FALLBACK NSE
# ---------------------------------------------------------------------------

def _asegurar_nse_score(data: pd.DataFrame) -> pd.DataFrame:
    """
    Garantía de seguridad: si nse_score no existe, lo calcula con defaults.
    En el pipeline normal ya viene calculado desde construccion_dataset.
    """
    if "nse_score" not in data.columns:
        escolaridad = data.get("escolaridad", 0.0)
        internet    = data.get("internet",    0.0)
        prod_bruta  = data.get("prod_bruta",  0.0)
        data = data.copy()
        data["nse_score"] = (
            escolaridad * 2
            + internet * 0.5
            + prod_bruta / 1_000_000
        )
    return data


# ---------------------------------------------------------------------------
# COMPONENTES DEL SCORE MODELO
# ---------------------------------------------------------------------------

def _calcular_componentes(
    data: pd.DataFrame,
    giro: str,
    presupuesto: str,
) -> pd.DataFrame:
    """
    Calcula los 5 componentes del score para el giro y presupuesto dados.

    Componentes positivos:
      - score_demanda:        densidad normalizada de negocios en la zona
      - score_validacion:     log del conteo del giro (mercado existe)
      - score_compatibilidad: NSE ajustado por capacidad de inversión

    Componentes negativos (penalizaciones):
      - penalizacion_saturacion: exceso sobre percentil 75 del giro
      - penalizacion_ruido:      proporción de negocios "otro" (no clasificados)
    """
    d = data.copy()

    # Columna del giro puede no existir si ningún negocio fue clasificado así
    if giro not in d.columns:
        d[giro] = 0

    # 1. Demanda
    max_negocios = d["total_negocios"].max()
    d["score_demanda"] = (
        d["total_negocios"] / max_negocios * 100 if max_negocios > 0 else 0.0
    )

    # 2. Validación de mercado (escala logarítmica)
    d["score_validacion"] = np.log1p(d[giro]) * 15

    # 3. Saturación (penalización sobre percentil 75)
    umbral = d[giro].quantile(0.75)
    d["penalizacion_saturacion"] = d[giro].apply(
        lambda x: (x - umbral) * 2 if x > umbral else 0.0
    )

    # 4. Ruido comercial (negocios sin clasificar relativo al total)
    if "otro" in d.columns:
        d["penalizacion_ruido"] = (d["otro"] / d["total_negocios"].replace(0, 1)) * 25
    else:
        d["penalizacion_ruido"] = 0.0

    # 5. Compatibilidad NSE según presupuesto del inversor
    factor = 0.5 if presupuesto == "alto" else 0.2
    d["score_compatibilidad"] = d["nse_score"] * factor

    return d


def _calcular_score_modelo(data: pd.DataFrame, giro: str) -> pd.DataFrame:
    """
    Aplica los pesos del giro sobre cada componente y calcula score_modelo.
    (Antes llamado score_final; ahora es el subtotal cuantitativo.)
    """
    d     = data.copy()
    pesos = PESOS_GIRO.get(giro, PESOS_DEFAULT)

    d["score_modelo"] = (
          d["score_demanda"]           * pesos["demanda"]
        + d["score_validacion"]        * pesos["validacion"]
        + d["score_compatibilidad"]    * pesos["compatibilidad"]
        - d["penalizacion_ruido"]      * pesos["ruido"]
        - d["penalizacion_saturacion"] * pesos["saturacion"]
    )
    return d


# ---------------------------------------------------------------------------
# SCORE FINAL CON CAPA DE PERCEPCIÓN
# ---------------------------------------------------------------------------

def _calcular_score_final(data: pd.DataFrame) -> pd.DataFrame:
    """
    Combina score_modelo y score_humano en score_final.

    Para hacer comparables las dos escalas, score_humano se normaliza
    al mismo rango que score_modelo usando min-max sobre los valores
    presentes en el dataset (no sobre constantes fijas), lo que garantiza
    que la capa humana sea proporcional y no domine artificialmente.

    Si todas las avenidas tienen score_humano = 0.0 (archivo ausente),
    score_final = score_modelo × 0.80, lo que preserva el ranking original.

    Fórmula:
        score_humano_norm = (score_humano - min) / (max - min) * rango_modelo
        score_final = score_modelo * PESO_MODELO + score_humano_norm * PESO_PERCEPCION
    """
    d = data.copy()

    sh = d["score_humano"]
    sm = d["score_modelo"]

    # Normalizar score_humano al rango de score_modelo
    sh_min, sh_max = sh.min(), sh.max()
    sm_min, sm_max = sm.min(), sm.max()

    if sh_max > sh_min and sh_max > 0:
        rango_modelo = sm_max - sm_min if sm_max > sm_min else 1.0
        sh_norm = (sh - sh_min) / (sh_max - sh_min) * rango_modelo + sm_min
    else:
        # Sin variación en percepción (archivo ausente o datos idénticos)
        sh_norm = 0.0

    d["score_humano_norm"] = sh_norm
    d["score_final"] = (
        sm * PESO_MODELO
        + d["score_humano_norm"] * PESO_PERCEPCION
    )

    return d


# ---------------------------------------------------------------------------
# PUNTO DE ENTRADA PÚBLICO
# ---------------------------------------------------------------------------

def simulador_pro_v2(
    data: pd.DataFrame,
    giro: str,
    presupuesto: str,
    top_n: int = 5,
) -> pd.DataFrame:
    """
    Análisis de rentabilidad comercial por avenida para un giro y presupuesto dados.

    Args:
        data:        Dataset construido por construccion_dataset.construir_dataset().
        giro:        Tipo de negocio: cafeteria/gym/restaurante/bar_antro/lavanderia.
        presupuesto: Nivel de inversión: bajo/medio/alto.
        top_n:       Cuántas avenidas incluir en el ranking (default 5).

    Returns:
        DataFrame con el top N de avenidas ordenadas por score_final (desc).
        Columnas de interés:
          - score_modelo:      score cuantitativo puro (DENUE + NSE)
          - score_humano:      percepción humana original (escala encuesta)
          - score_humano_norm: percepción normalizada al rango del modelo
          - score_final:       score combinado (80% modelo + 20% percepción)
    """
    giro        = giro.lower().strip()
    presupuesto = presupuesto.lower().strip()

    d = data.copy()

    # 1. Fallback NSE por si no viene del pipeline
    d = _asegurar_nse_score(d)

    # 2. Filtros base
    d = d[~d["avenida"].str.upper().isin(LISTA_NEGRA)]
    d = d[d["total_negocios"] > 15]  # zonas con actividad real

    if d.empty:
        raise ValueError("No quedan avenidas tras aplicar filtros. Revisa los datos de entrada.")

    # 3. Integrar percepción humana (merge; tolera archivo ausente)
    percepcion = _cargar_percepcion(RUTA_PERCEPCION)
    d = _integrar_percepcion(d, percepcion)

    # 4. Pipeline de scoring cuantitativo
    d = _calcular_componentes(d, giro, presupuesto)
    d = _calcular_score_modelo(d, giro)

    # 5. Score final combinado
    d = _calcular_score_final(d)

    return d.sort_values("score_final", ascending=False).head(top_n).reset_index(drop=True)