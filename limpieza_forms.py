"""
limpieza_forms.py
-----------------
Pipeline de limpieza e integración de encuestas de percepción comercial
para el proyecto BI Guadalajara.

Outputs:
  - forms_limpios.csv        → respuestas numéricas limpias por avenida y dimensión
  - avenidas_mencionadas.csv → avenidas/zonas extraídas de respuestas abiertas
  - insights_urbanos.csv     → insights cualitativos detectados por avenida

Uso:
  python limpieza_forms.py

Requisitos:
  pip install pandas
"""

import re
import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------------
# RUTAS
# ---------------------------------------------------------------------------
BASE = Path(__file__).parent
RUTA_FORM1 = r"C:\Users\leopa\Desktop\proyecto_estudio_mercado\data\Percepción comercial de avenidas en GDL  1 (Respuestas) - Respuestas de formulario 1.csv"

RUTA_FORM2 = r"C:\Users\leopa\Desktop\proyecto_estudio_mercado\data\Percepción comercial de avenidas en GDL 2 (Respuestas) - Respuestas de formulario 1.csv"
RUTA_FORMS_LIMPIOS      = BASE / "forms_limpios.csv"
RUTA_AVENIDAS           = BASE / "avenidas_mencionadas.csv"
RUTA_INSIGHTS           = BASE / "insights_urbanos.csv"

# ---------------------------------------------------------------------------
# PARTE 1 — MAPEOS DE ESCALA NUMÉRICA
# ---------------------------------------------------------------------------

# Escala de "qué tan buena" (dimensión: calidad_percibida)
MAPA_CALIDAD = {
    "5 — excelente opción":       5,
    "4 — buena opción":           4,
    "3 — depende del negocio":    3,   # Form 1 usa esta etiqueta
    "3 — opción normal":          3,
    "2 — mala opción":            2,
    "1 — muy mala opción":        1,
    "no la conozco":              None,
}

# Escala de saturación (dimensión: saturacion_percibida)
# Nota: la escala de saturación va de 1 (poca) a 5 (muy saturada).
# Se mantiene esa lógica directamente para transparencia.
MAPA_SATURACION = {
    "5 — muy saturada / difícil competir": 5,
    "4 — mucha competencia":               4,
    "3 — competencia normal":              3,
    "2 — poca competencia":                2,
    "1 — casi sin competencia":            1,
    "no la conozco":                       None,
}

# ---------------------------------------------------------------------------
# PARTE 2 — LISTA DE INSIGHTS A DETECTAR
# ---------------------------------------------------------------------------
# Cada entrada: (etiqueta_insight, [patrones_regex])
# El orden importa: se toma el primer match.

INSIGHTS = [
    ("sobrevalorada",     [r"sobreval"]),
    ("mucho potencial",   [r"mucho potencial", r"gran potencial"]),
    ("poca competencia",  [r"poca competencia", r"muy poca competencia", r"casi sin competencia"]),
    ("saturada",          [r"saturad", r"mucha competencia", r"difícil competir"]),
    ("crecimiento",       [r"crecimient", r"está creciendo", r"en desarrollo"]),
    ("premium",           [r"premium", r"exclusiv", r"lujosa", r"nivel alto"]),
    ("insegura",          [r"insegur", r"peligros", r"mala zona"]),
    ("tráfico",           [r"tráfico", r"trafico", r"congestion", r"congestión"]),
    ("buena zona",        [r"buena zona", r"muy buena zona", r"muy buena"]),
    ("buena opción",      [r"es buena", r"muy buena$", r"buena$"]),
    ("poca actividad",    [r"poca actividad", r"pocos negocios", r"poco movimiento"]),
]

# ---------------------------------------------------------------------------
# PARTE 3 — DICCIONARIO DE NORMALIZACIÓN DE AVENIDAS
# ---------------------------------------------------------------------------
# Mapea variantes textuales al nombre canónico que usa dataset_gdl_final.csv.
# Ampliar según los nombres reales de tu DENUE.

NORMALIZACION_AVENIDAS = {
    "chapultepec":       "CHAPULTEPEC",
    "vallarta":          "VALLARTA",
    "mexico":            "MEXICO",
    "lópez mateos":      "LOPEZ MATEOS",
    "lopez mateos":      "LOPEZ MATEOS",
    "américas":          "AMERICAS",
    "americas":          "AMERICAS",
    "patria":            "PATRIA",
    "mariano otero":     "MARIANO OTERO",
    "niños héroes":      "NIÑOS HEROES",
    "niños heroes":      "NIÑOS HEROES",
    "federalismo":       "FEDERALISMO",
    "juárez":            "JUAREZ",
    "juarez":            "JUAREZ",
    "terranova":         "TERRANOVA",
    "rubén darío":       "RUBEN DARIO",
    "ruben dario":       "RUBEN DARIO",
    "pablo neruda":      "PABLO NERUDA",
    "acueducto":         "ACUEDUCTO",
    "guadalupe":         "GUADALUPE",
    "tepeyac":           "TEPEYAC",
    "rafael sanzio":     "RAFAEL SANZIO",
    "aviación":          "AVIACION",
    "aviacion":          "AVIACION",
    "santa margarita":   "SANTA MARGARITA",
    "base aérea":        "BASE AEREA",
    "base aerea":        "BASE AEREA",
    "servidor público":  "SERVIDOR PUBLICO",
    "servidor publico":  "SERVIDOR PUBLICO",
    "alcalde":           "ALCALDE",
    "independencia":     "INDEPENDENCIA",
    "revolución":        "REVOLUCION",
    "revolucion":        "REVOLUCION",
    "lázaro cárdenas":   "LAZARO CARDENAS",
    "lazaro cardenas":   "LAZARO CARDENAS",
    "cruz del sur":      "CRUZ DEL SUR",
    "colón":             "COLON",
    "colon":             "COLON",
    "8 de julio":        "8 DE JULIO",
    "río nilo":          "RIO NILO",
    "rio nilo":          "RIO NILO",
    "juan gil preciado": "JUAN GIL PRECIADO",
    "periférico sur":    "PERIFERICO SUR",
    "periferico sur":    "PERIFERICO SUR",
    "montevideo":        "MONTEVIDEO",
    "adolf horn":        "ADOLF HORN",
    "valle imperial":    "VALLE IMPERIAL",
    "clouthier":         "CLOUTHIER",
    "copérnico":         "COPERNICO",
    "copernico":         "COPERNICO",
}


# ===========================================================================
# FUNCIONES AUXILIARES
# ===========================================================================

def limpiar_texto(texto: str) -> str:
    """
    Limpieza básica de caracteres basura.
    - Elimina backticks (`) y otros caracteres raro
    - Colapsa espacios dobles
    - Strip de inicio/final
    - Preserva acentos y ñ
    """
    if not isinstance(texto, str):
        return texto
    texto = texto.replace("`", "")        # backtick frecuente en Form 2
    texto = texto.replace("\r", " ")
    texto = texto.replace("\n", " ")
    texto = re.sub(r"  +", " ", texto)    # espacios dobles → uno
    texto = texto.strip()
    return texto


def extraer_nombre_avenida(col: str) -> str:
    """
    Extrae el nombre de avenida desde el encabezado de columna.

    Ejemplos:
      '¿Qué tan buena...  [Av. Chapultepec]' → 'Chapultepec'
      ' [Av. Juan Gil Preciado]'             → 'Juan Gil Preciado'
      ' [Calz. Independencia]'               → 'Independencia'
    """
    match = re.search(r'\[(Av\.|Calz\.|Bv\.)\s*(.+?)\]', col)
    if match:
        nombre = match.group(2).strip()
        return nombre
    return col.strip()


def convertir_escala(valor: str, mapa: dict):
    """
    Convierte un valor textual de escala a número usando el mapa dado.
    Retorna NaN si no está en el mapa o si es 'No la conozco'.
    """
    if not isinstance(valor, str):
        return None
    clave = limpiar_texto(valor).lower()
    return mapa.get(clave, None)   # None → se convierte a NaN al exportar


def normalizar_avenida(nombre: str) -> str:
    """
    Normaliza un nombre de avenida al canónico usando el diccionario.
    Si no está, retorna el nombre limpio en mayúsculas.
    """
    clave = nombre.lower().strip()
    return NORMALIZACION_AVENIDAS.get(clave, nombre.upper().strip())


def detectar_insights(texto: str) -> list[tuple[str, str]]:
    """
    Dado un texto libre, detecta pares (avenida_normalizada, insight).

    Estrategia:
      1. Extrae avenidas mencionadas en el texto.
      2. Para cada avenida, busca qué insights se mencionan.
      3. Si no se detecta insight específico, etiqueta "mencionada".
    """
    if not isinstance(texto, str) or not texto.strip():
        return []

    texto_lower = texto.lower()
    resultados = []

    # Detectar avenidas presentes en el texto
    avenidas_en_texto = []
    for clave, canonico in NORMALIZACION_AVENIDAS.items():
        if clave in texto_lower:
            avenidas_en_texto.append(canonico)

    # Detectar insights presentes en el texto
    insights_en_texto = []
    for etiqueta, patrones in INSIGHTS:
        for patron in patrones:
            if re.search(patron, texto_lower):
                insights_en_texto.append(etiqueta)
                break

    if not avenidas_en_texto:
        return []

    # Asociar cada avenida a los insights detectados
    for av in set(avenidas_en_texto):   # set para deduplicar
        if insights_en_texto:
            for ins in insights_en_texto:
                resultados.append((av, ins))
        else:
            resultados.append((av, "mencionada"))

    return resultados


def extraer_avenidas_mencionadas(texto: str) -> list[str]:
    """
    Extrae y normaliza avenidas/zonas mencionadas en texto libre.
    Retorna lista de nombres canónicos (puede tener varios).
    """
    if not isinstance(texto, str) or not texto.strip():
        return []
    texto_lower = texto.lower()
    encontradas = []
    for clave, canonico in NORMALIZACION_AVENIDAS.items():
        if clave in texto_lower:
            encontradas.append(canonico)
    # Deduplicar preservando orden de aparición
    vistas = set()
    resultado = []
    for av in encontradas:
        if av not in vistas:
            vistas.add(av)
            resultado.append(av)
    return resultado


# ===========================================================================
# PIPELINE PRINCIPAL
# ===========================================================================

def cargar_y_limpiar_form(ruta: Path, forma_numero: int) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Carga un CSV de encuesta y lo prepara.

    Retorna:
      - df_raw:         DataFrame crudo con texto limpio
      - cols_calidad:   columnas de dimensión "calidad percibida"
      - cols_saturacion: columnas de dimensión "saturación percibida"
    """
    df = pd.read_csv(ruta)

    # Limpiar TODOS los valores de texto en el dataframe
    df = df.map(lambda x: limpiar_texto(x) if isinstance(x, str) else x)

    # Identificar columnas por su contenido de encabezado
    # Form 1: tiene pregunta explícita en el encabezado
    # Form 2: columnas con sufijo .1 son saturación
    cols_calidad    = []
    cols_saturacion = []

    for col in df.columns:
        col_clean = col.strip()
        if forma_numero == 1:
            if "Qué tan buena" in col:
                cols_calidad.append(col)
            elif "saturada" in col or "difícil" in col:
                cols_saturacion.append(col)
        elif forma_numero == 2:
            # Form 2: columnas sin sufijo = calidad, con .1 = saturación
            if re.search(r'\[.+\]$', col_clean) and not col_clean.endswith(".1]") and "¿" not in col:
                cols_calidad.append(col)
            elif col_clean.endswith(".1") or re.search(r'\.\d+$', col_clean):
                cols_saturacion.append(col)

    return df, cols_calidad, cols_saturacion


def construir_forms_limpios(
    df: pd.DataFrame,
    cols_calidad: list[str],
    cols_saturacion: list[str],
    forma_numero: int,
) -> pd.DataFrame:
    """
    Convierte las respuestas de escala textual a numéricas.

    Estructura del output (formato largo):
      | respuesta_id | forma | avenida | calidad_percibida | saturacion_percibida |
    """
    registros = []

    for idx, fila in df.iterrows():
        # Emparejar avenidas de calidad y saturación por nombre
        calidad_dict    = {}
        saturacion_dict = {}

        for col in cols_calidad:
            nombre = extraer_nombre_avenida(col)
            canonico = normalizar_avenida(nombre)
            valor = convertir_escala(fila[col], MAPA_CALIDAD)
            calidad_dict[canonico] = valor

        for col in cols_saturacion:
            nombre = extraer_nombre_avenida(col)
            # Para Form 2, quitar el sufijo ".1" que pandas añade a duplicados
            nombre = re.sub(r'\.1$', '', nombre).strip()
            canonico = normalizar_avenida(nombre)
            valor = convertir_escala(fila[col], MAPA_SATURACION)
            saturacion_dict[canonico] = valor

        # Una fila por avenida por respondente
        todas_avenidas = set(calidad_dict.keys()) | set(saturacion_dict.keys())
        for av in todas_avenidas:
            registros.append({
                "respuesta_id":        idx,
                "forma":               forma_numero,
                "avenida":             av,
                "calidad_percibida":   calidad_dict.get(av, None),
                "saturacion_percibida": saturacion_dict.get(av, None),
            })

    return pd.DataFrame(registros)


def construir_avenidas_mencionadas(df1: pd.DataFrame, df2: pd.DataFrame) -> pd.DataFrame:
    """
    Extrae avenidas de las respuestas abiertas de ambos forms.
    Retorna dataset con columnas: | avenida | menciones | fuente |
    """
    COL_ABIERTA = "  ¿Hay alguna avenida o zona que consideres muy buena, sobrevalorada o poco recomendable para abrir un negocio? ¿Por qué?  "

    registros = []

    for forma_num, df in [(1, df1), (2, df2)]:
        col = COL_ABIERTA
        if col not in df.columns:
            # Buscar por coincidencia parcial (por si el encabezado varía)
            match = [c for c in df.columns if "avenida o zona" in c.lower()]
            if match:
                col = match[0]
            else:
                continue

        for texto in df[col].dropna():
            avenidas = extraer_avenidas_mencionadas(texto)
            for av in avenidas:
                registros.append({
                    "avenida": av,
                    "texto_original": texto,
                    "forma": forma_num,
                })

    if not registros:
        return pd.DataFrame(columns=["avenida", "menciones", "formas"])

    df_av = pd.DataFrame(registros)

    # Agregar conteo de menciones
    resumen = (
        df_av.groupby("avenida")
        .agg(
            menciones=("avenida", "count"),
            formas=("forma", lambda x: ",".join(str(f) for f in sorted(set(x))))
        )
        .reset_index()
        .sort_values("menciones", ascending=False)
    )

    return resumen


def construir_insights_urbanos(df1: pd.DataFrame, df2: pd.DataFrame) -> pd.DataFrame:
    """
    Detecta insights cualitativos en respuestas abiertas.
    Retorna dataset: | avenida | insight_detectado | forma |
    """
    COL_ABIERTA = "  ¿Hay alguna avenida o zona que consideres muy buena, sobrevalorada o poco recomendable para abrir un negocio? ¿Por qué?  "

    registros = []

    for forma_num, df in [(1, df1), (2, df2)]:
        col = COL_ABIERTA
        if col not in df.columns:
            match = [c for c in df.columns if "avenida o zona" in c.lower()]
            if match:
                col = match[0]
            else:
                continue

        for texto in df[col].dropna():
            pares = detectar_insights(texto)
            for av, insight in pares:
                registros.append({
                    "avenida":          av,
                    "insight_detectado": insight,
                    "texto_fuente":     texto,
                    "forma":            forma_num,
                })

    if not registros:
        return pd.DataFrame(columns=["avenida", "insight_detectado", "forma"])

    df_ins = pd.DataFrame(registros)

    # Deduplicar: misma avenida + mismo insight una sola vez por forma
    df_ins = df_ins.drop_duplicates(subset=["avenida", "insight_detectado", "forma"])

    return df_ins[["avenida", "insight_detectado", "forma"]].sort_values(
        ["avenida", "insight_detectado"]
    ).reset_index(drop=True)


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    print("\n🧹  limpieza_forms.py — Pipeline de percepción urbana GDL")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Cargar y limpiar CSVs
    # ------------------------------------------------------------------
    print("\n📂 Cargando formularios...")
    df1_raw, cols_cal1, cols_sat1 = cargar_y_limpiar_form(RUTA_FORM1, forma_numero=1)
    df2_raw, cols_cal2, cols_sat2 = cargar_y_limpiar_form(RUTA_FORM2, forma_numero=2)

    print(f"   Form 1: {len(df1_raw)} respuestas  |  {len(cols_cal1)} avenidas (calidad)  |  {len(cols_sat1)} (saturación)")
    print(f"   Form 2: {len(df2_raw)} respuestas  |  {len(cols_cal2)} avenidas (calidad)  |  {len(cols_sat2)} (saturación)")

    # ------------------------------------------------------------------
    # 2. Construir tabla de scores numéricos (formato largo)
    # ------------------------------------------------------------------
    print("\n🔢 Convirtiendo escalas a valores numéricos...")
    forms1_num = construir_forms_limpios(df1_raw, cols_cal1, cols_sat1, forma_numero=1)
    forms2_num = construir_forms_limpios(df2_raw, cols_cal2, cols_sat2, forma_numero=2)
    forms_limpios = pd.concat([forms1_num, forms2_num], ignore_index=True)

    # También calcular promedios por avenida (útil para merge con dataset_gdl_final)
    promedios = (
        forms_limpios
        .groupby("avenida")
        .agg(
            n_respuestas=("respuesta_id", "count"),
            calidad_media=("calidad_percibida", "mean"),
            saturacion_media=("saturacion_percibida", "mean"),
        )
        .round(3)
        .reset_index()
    )

    forms_limpios.to_csv(RUTA_FORMS_LIMPIOS, index=False, encoding="utf-8-sig")
    print(f"   ✅ forms_limpios.csv  ({len(forms_limpios):,} filas)")

    # ------------------------------------------------------------------
    # 3. Avenidas mencionadas en respuestas abiertas
    # ------------------------------------------------------------------
    print("\n🗺️  Extrayendo avenidas de respuestas abiertas...")
    avenidas_df = construir_avenidas_mencionadas(df1_raw, df2_raw)
    avenidas_df.to_csv(RUTA_AVENIDAS, index=False, encoding="utf-8-sig")
    print(f"   ✅ avenidas_mencionadas.csv  ({len(avenidas_df)} avenidas únicas)")

    # ------------------------------------------------------------------
    # 4. Insights urbanos
    # ------------------------------------------------------------------
    print("\n💡 Detectando insights cualitativos...")
    insights_df = construir_insights_urbanos(df1_raw, df2_raw)
    insights_df.to_csv(RUTA_INSIGHTS, index=False, encoding="utf-8-sig")
    print(f"   ✅ insights_urbanos.csv  ({len(insights_df)} insights detectados)")

    # ------------------------------------------------------------------
    # 5. Resumen en consola
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("📊 PROMEDIOS DE PERCEPCIÓN POR AVENIDA")
    print("=" * 60)
    print(promedios.to_string(index=False))

    print("\n📋 INSIGHTS DETECTADOS")
    print("=" * 60)
    if not insights_df.empty:
        print(insights_df.to_string(index=False))
    else:
        print("  (ninguno detectado — ampliar diccionario NORMALIZACION_AVENIDAS si es necesario)")

    print("\n✅ Pipeline completado. Archivos generados:")
    print(f"   → {RUTA_FORMS_LIMPIOS}")
    print(f"   → {RUTA_AVENIDAS}")
    print(f"   → {RUTA_INSIGHTS}")
    print()
    print("💡 Para integrar al pipeline principal:")
    print("   df_percepcion = pd.read_csv('forms_limpios.csv')")
    print("   promedios = df_percepcion.groupby('avenida')[['calidad_percibida','saturacion_percibida']].mean()")
    print("   dataset = dataset.merge(promedios, on='avenida', how='left')")


if __name__ == "__main__":
    main()
