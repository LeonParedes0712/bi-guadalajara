"""
main.py
-------
Punto de entrada del proyecto de análisis de mercado INEGI — Guadalajara.

Pipeline:
  carga_datos → construccion_dataset → scoring → visualizacion

Para cambiar el escenario a analizar, edita únicamente la sección
"CONFIGURACIÓN DE EJECUCIÓN" más abajo.
"""

from pathlib import Path

from carga_datos           import cargar_indicadores_cpv_ce, cargar_denue_por_chunks
from construccion_dataset  import construir_dataset, guardar_dataset
from scoring               import simulador_pro_v2
from visualizacion         import graficar_ranking, imprimir_ranking

# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RUTAS DE DATOS

# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent / "data" #Busca la ruta dentro de la carpeta data

RUTA_DENUE  = BASE_DIR / "denue_inegi_14_.csv" 
RUTA_CPV    = BASE_DIR / "cpv_valor_14.csv"
RUTA_CE     = BASE_DIR / "ce_valor_14.csv"


RUTA_OUTPUT = Path(__file__).parent / "dataset_gdl_final.csv" #Crea la ruta final para el dataset de INEGI

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DE EJECUCIÓN
# Modifica GIRO y PRESUPUESTO para probar distintos escenarios.
# ---------------------------------------------------------------------------
GIRO        = "bar_antro"   # cafeteria | gym | restaurante | bar_antro | lavanderia
PRESUPUESTO = "medio"       # bajo | medio | alto
TOP_N       = 5             # cuántas avenidas mostrar en el ranking


def main() -> None:
    """Orquesta el pipeline completo de análisis de mercado."""

    print("\n🧭  BI Guadalajara — Engine de Rentabilidad V2.0")
    print(f"    Giro: {GIRO}  |  Presupuesto: {PRESUPUESTO}\n")

    # ------------------------------------------------------------------
    # 1. Cargar indicadores socioeconómicos (CPV + CE)
    # ------------------------------------------------------------------
    indicadores = cargar_indicadores_cpv_ce(ruta_cpv=RUTA_CPV, ruta_ce=RUTA_CE)

    # ------------------------------------------------------------------
    # 2. Cargar y clasificar el DENUE en chunks
    # ------------------------------------------------------------------
    df_denue = cargar_denue_por_chunks(ruta_denue=RUTA_DENUE)

    # ------------------------------------------------------------------
    # 3. Construir dataset analítico (incluye nse_score)
    # ------------------------------------------------------------------
    dataset = construir_dataset(df_denue, indicadores)
    guardar_dataset(dataset, ruta_salida=RUTA_OUTPUT)

    # ------------------------------------------------------------------
    # 4. Scoring y ranking
    #    nse_score ya viene calculado desde construccion_dataset;
    #    scoring.py lo recomputa como fallback si faltara.
    # ------------------------------------------------------------------
    ranking = simulador_pro_v2(dataset, giro=GIRO, presupuesto=PRESUPUESTO, top_n=TOP_N)

    print(ranking[["avenida", "score_modelo", "score_humano", "score_humano_norm", "score_final"]])

    # ------------------------------------------------------------------
    # 5. Presentación de resultados
    # ------------------------------------------------------------------
    imprimir_ranking(ranking, giro=GIRO)
    graficar_ranking(ranking, giro=GIRO)


if __name__ == "__main__":
    main()
