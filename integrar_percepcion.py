import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).parent

RUTA_FORMS = BASE_DIR / "forms_limpios.csv"
RUTA_SALIDA = BASE_DIR / "percepcion_resumen.csv"

def main():
    df = pd.read_csv(RUTA_FORMS)

    resumen = (
        df.groupby("avenida")
        .agg(
            n_total=("respuesta_id", "count"),
            n_calidad=("calidad_percibida", "count"),
            calidad_media=("calidad_percibida", "mean"),
            n_saturacion=("saturacion_percibida", "count"),
            saturacion_media=("saturacion_percibida", "mean"),
        )
        .reset_index()
    )

    resumen["conocimiento_pct"] = (
        resumen["n_calidad"] / resumen["n_total"] * 100
    )

    resumen["score_humano"] = (
        resumen["calidad_media"] * 2
        - resumen["saturacion_media"]
        + resumen["conocimiento_pct"] * 0.03
    )

    resumen.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")
    print("✅ percepcion_resumen.csv generado")

if __name__ == "__main__":
    main()