"""
mapa.py
-------
Geocodifica avenidas de Guadalajara desde dataset_gdl_final.csv
y genera un mapa interactivo en folium guardado como mapa_gdl.html.

Usa simulador_pro_v2() de scoring.py para obtener el score híbrido:
  - score_modelo:      score cuantitativo puro (DENUE + NSE)
  - score_humano:      percepción humana original (escala encuesta)
  - score_humano_norm: percepción normalizada al rango del modelo
  - score_final:       score combinado (80% modelo + 20% percepción)

Uso:
    python mapa.py

Dependencias:
    pip install pandas geopy folium
"""

from folium.plugins import HeatMap, MarkerCluster
from html import escape
import json
import sys
import time
import unicodedata
import re
from pathlib import Path

import folium
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

# Importar el motor de scoring — sin ciclos de import
from scoring import simulador_pro_v2

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# CONFIGURACIÓN — mismos valores que main.py
# ---------------------------------------------------------------------------

CSV_ENTRADA = Path("dataset_gdl_final.csv")
CACHE_FILE  = Path("geocode_cache.json")   # caché persistente en disco


# Centro geográfico de Guadalajara
GDL_LAT, GDL_LON = 20.6597, -103.3496

# Sufijo para las búsquedas de geocodificación
SUFIJO_GEO = ", Guadalajara, Jalisco, Mexico"

# Geocodificar solo avenidas con suficiente actividad (evita calles fantasma)
# Nota: simulador_pro_v2 ya filtra por total_negocios > 15; este umbral
# aplica sobre el dataset completo ANTES de pasar al scoring.
MIN_NEGOCIOS = 20

# Score mínimo para aparecer en el mapa (filtra ruido)
MIN_SCORE = 15           # pon un valor más alto para mapas más limpios

# ── Configuración idéntica a main.py ──────────────────────────────────────
GIRO        = "bar_antro"   # cafeteria | gym | restaurante | bar_antro | lavanderia
PRESUPUESTO = "medio"        # bajo | medio | alto
GIROS = ["cafeteria", "gym", "restaurante", "bar_antro", "lavanderia"]
PRESUPUESTOS = ["bajo", "medio", "alto"]
# Cuántas avenidas incluir en el ranking que se muestra en el mapa.
# None = todas las que pasen los filtros de scoring.
HTML_SALIDA = Path(f"mapa_{GIRO}_{PRESUPUESTO}.html")
HTML_INTERACTIVO = Path("mapa_interactivo.html")
TOP_N = 50
# ─────────────────────────────────────────────────────────────────────────

# Pausa entre llamadas a Nominatim (política: ≥ 1 segundo)
DELAY_SEG = 1.1

# Límite de avenidas a geocodificar por ejecución (None = sin límite)
LIMITE_GEOCODIFICACION = None   # e.g. 200 para pruebas rápidas


# ---------------------------------------------------------------------------
# UTILIDADES DE TEXTO
# ---------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """Quita acentos, convierte a título y limpia caracteres raros."""
    if not texto:
        return ""
    # Reparar posibles caracteres corruptos (latin-1 leído como utf-8)
    try:
        texto = texto.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8")
    texto = re.sub(r"\s+", " ", texto).strip().title()
    return texto


def es_nombre_valido(nombre: str) -> bool:
    """Descarta nombres que son solo números o muy cortos."""
    limpio = nombre.strip()
    if len(limpio) <= 1:
        return False
    if limpio.isdigit():
        return False
    return True

def clasificar_corredor(row):

    if row["score_humano"] > 7 and row["score_validacion"] > 10:
        return "Premium consolidado"

    if row["score_demanda"] > 70 and row["penalizacion_saturacion"] > 0:
        return "Corredor de alto flujo"

    if row["score_humano"] > 7 and row["score_validacion"] < 5:
        return "Zona emergente"

    if row["penalizacion_ruido"] > 10:
        return "Comercial mixto"

    return "Corredor comercial"


def badge_style_por_corredor(tipo_corredor):
    estilos = {
        "Premium consolidado": ("#d1e7dd", "#0f5132"),
        "Corredor de alto flujo": ("#fff3cd", "#664d03"),
        "Zona emergente": ("#cfe2ff", "#084298"),
        "Comercial mixto": ("#f8d7da", "#842029"),
    }
    return estilos.get(tipo_corredor, ("#eef4ff", "#1d4ed8"))


# ---------------------------------------------------------------------------
# COLOR POR SCORE
# ---------------------------------------------------------------------------

def color_por_score(score: float, p33: float, p66: float) -> str:
    """Devuelve color de marcador según percentiles del dataset."""
    if score >= p66:
        return "green"
    elif score >= p33:
        return "orange"
    else:
        return "red"


# ---------------------------------------------------------------------------
# GEOCODIFICACIÓN CON CACHÉ
# ---------------------------------------------------------------------------

def cargar_cache(ruta: Path) -> dict:
    """Carga el caché de coordenadas desde disco (JSON)."""
    if ruta.exists():
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def guardar_cache(cache: dict, ruta: Path) -> None:
    """Persiste el caché de coordenadas en disco."""
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def geocodificar(geolocator, nombre_normalizado: str, cache: dict) -> tuple | None:
    """
    Devuelve (lat, lon) para una calle, usando caché o llamada a Nominatim.
    Retorna None si no se puede geocodificar.
    """
    clave = nombre_normalizado

    if clave in cache:
        datos = cache[clave]
        if datos is None:
            return None          # ya sabemos que falla
        return (datos["lat"], datos["lon"])

    query = nombre_normalizado + SUFIJO_GEO
    try:
        time.sleep(DELAY_SEG)
        location = geolocator.geocode(query, timeout=10)
        if location:
            cache[clave] = {"lat": location.latitude, "lon": location.longitude}
            return (location.latitude, location.longitude)
        else:
            cache[clave] = None   # marca como "no encontrado"
            return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"   ⚠  Error geocodificando '{query}': {e}")
        return None


# ---------------------------------------------------------------------------
# MAPA FOLIUM — POPUPS Y RECOMENDACIONES
# ---------------------------------------------------------------------------

def icono_marcador(color: str) -> folium.Icon:
    """Crea un ícono de marcador con el color indicado."""
    return folium.Icon(color=color, icon="store", prefix="fa")


def _recomendacion(score: float, saturacion: float, ruido: float, p66: float) -> tuple[str, str]:
    """
    Devuelve (texto, color_fondo) con la recomendación automática para la zona.

    Lógica de prioridad:
      1. Ruido alto       → advertencia de entorno
      2. Score alto + saturación → oportunidad con precaución
      3. Score alto       → zona atractiva
      4. Score bajo       → zona menos prioritaria
    """
    es_alto = score >= p66

    if ruido > 10:
        return (
            "⚠️ Zona con ruido comercial elevado; revisar compatibilidad del entorno.",
            "#fff3cd",   # amarillo suave
        )
    if es_alto and saturacion > 0:
        return (
            "📊 Zona con alta demanda, pero se recomienda analizar competencia directa.",
            "#cfe2ff",   # azul suave
        )
    if es_alto:
        return (
            "✅ Zona atractiva con buen potencial comercial.",
            "#d1e7dd",   # verde suave
        )
    return (
        "🔻 Zona menos prioritaria para este giro bajo los criterios actuales.",
        "#f8d7da",   # rojo suave
    )


def popup_html(row: dict, score: float, p66: float = 0.0, giro: str = "") -> str:
    """
    Genera HTML enriquecido para el popup del marcador.

    Ahora muestra el desglose completo del score híbrido:
      - score_modelo:      score cuantitativo (DENUE + NSE)
      - score_humano:      percepción humana (escala encuesta, ~5-8)
      - score_final:       combinado 80/20

    Args:
        row:   Fila del DataFrame convertida a dict (row.to_dict()).
        score: score_final ya redondeado.
        p66:   Percentil 66 del score en el dataset (para clasificar "alto").
        giro:  Giro activo (e.g. "gym") para mostrar su conteo específico.
    """
    # ── Campos básicos ──────────────────────────────────────────────────
    nombre   = row.get("avenida_display") or row.get("avenida", "—")
    negocios = int(row.get("total_negocios", 0))
    flujo    = round(float(row.get("flujo_comercial", 0)), 1)

    # ── Scores híbridos ─────────────────────────────────────────────────
    score_modelo = round(float(row.get("score_modelo", 0)), 2)
    score_humano = round(float(row.get("score_humano", 0)), 2)

    # ── Giro seleccionado ────────────────────────────────────────────────
    giro_col   = giro.lower().strip() if giro else ""
    giro_count = int(row.get(giro_col, 0)) if giro_col else None
    giro_label = giro_col.replace("_", "/").capitalize() if giro_col else None

    # ── Explicabilidad centralizada ─────────────────────────────────────────
    pros = str(row.get("pros", "") or "").strip()
    riesgos = str(row.get("riesgos", "") or "").strip()
    explicacion_corta = str(row.get("explicacion_corta", "") or "").strip()
    tipo_corredor = clasificar_corredor(row)
    badge_bg, badge_color = badge_style_por_corredor(tipo_corredor)

    def convertir_a_bullets(texto: str, fallback: str) -> str:
        if not texto:
            return fallback
        
        items = [escape(item.strip()) for item in texto.split(" | ") if item.strip()]

        if not items:
            return fallback

        return "".join(
            f"<div style='margin-bottom:4px;'>• {item}</div>"
            for item in items
        )
    
    pros_html = convertir_a_bullets(pros, "Sin fortalezas destacadas")
    riesgos_html = convertir_a_bullets(riesgos, "Sin riesgos destacados")


    explicacion_html = (
        escape(explicacion_corta)
        if explicacion_corta
        else "Zona con indicadores comerciales moderados."
    )

    # ── Alertas ─────────────────────────────────────────────────────────
    saturacion = float(row.get("penalizacion_saturacion", 0))
    ruido      = float(row.get("penalizacion_ruido", 0))

    # ── Recomendación automática ─────────────────────────────────────────
    recomendacion_txt, recomendacion_bg = _recomendacion(score, saturacion, ruido, p66)

    # ── Fila del giro seleccionado (opcional) ────────────────────────────
    fila_giro = (
        f"""<tr>
              <td style="padding:3px 0;"><b>{giro_label} en la zona</b></td>
              <td style="padding:3px 0 3px 8px;">{giro_count}</td>
            </tr>"""
        if giro_label is not None else ""
    )

    return f"""
    <div style="font-family:sans-serif; min-width:240px; max-width:310px;">

      <!-- Encabezado -->
      <div style="
          background:#1a73e8; color:white;
          padding:8px 12px; border-radius:6px 6px 0 0;
          margin:-1px -1px 0 -1px;
      ">
        <b style="font-size:14px;">{nombre}</b>
      </div>

      <!-- Score híbrido desglosado -->
      <table style="
          border-collapse:collapse; width:100%;
          font-size:13px; padding:6px 4px;
      ">
        <tr>
          <td style="padding:4px 0;"><b>Score final</b></td>
          <td style="padding:4px 0 4px 8px; font-weight:bold; color:#1a73e8;">
            {score}
          </td>
        </tr>
        <tr>
          <td style="padding:3px 0; color:#555;">
            ↳ Score modelo (80%)
          </td>
          <td style="padding:3px 0 3px 8px; color:#555;">{score_modelo}</td>
        </tr>
        <tr>
          <td style="padding:3px 0; color:#555;">
            ↳ Percepción humana (20%)
          </td>
          <td style="padding:3px 0 3px 8px; color:#555;">{score_humano}</td>
        </tr>
        <tr><td colspan="2"><hr style="margin:4px 0; border-color:#eee;"></td></tr>
        <tr>
          <td style="padding:3px 0;"><b>Total negocios</b></td>
          <td style="padding:3px 0 3px 8px;">{negocios}</td>
        </tr>
        <tr>
          <td style="padding:3px 0;"><b>Flujo comercial</b></td>
          <td style="padding:3px 0 3px 8px;">{flujo}%</td>
        </tr>
        {fila_giro}
      </table>

      <!-- Explicabilidad -->
      <div style="
          margin-top:8px;
          padding:8px 10px;
          background:#f8f9fa;
          border:1px solid #e9ecef;
          border-radius:5px;
          font-size:12px;
          line-height:1.45;
      ">
        <div style="margin-bottom:10px;">
          <b>🏷 Tipo de corredor</b><br>

          <span style="
              background:{badge_bg};
              color:{badge_color};
              padding:4px 8px;
              border-radius:8px;
              font-size:12px;
              font-weight:600;
          ">
              {tipo_corredor}
          </span>
        </div>
        <div style="margin-bottom:6px;">
          <b>Explicación</b><br>
          <span style="color:#333;">{explicacion_html}</span>
        </div>
        <div style="margin-bottom:4px;">
          
          <b style="color:#0f5132;">Fortalezas</b><br>
          <span>{pros_html}</span>
        </div>
        <div>
          <b style="color:#842029;">Riesgos</b><br>
          <span>{riesgos_html}</span>
        </div>
      </div>

    </div>
    """


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPAL
# ---------------------------------------------------------------------------

def calcular_escenario(df_raw: pd.DataFrame, giro: str, presupuesto: str) -> tuple[pd.DataFrame, float, float]:
    """Calcula y filtra el ranking para un giro/presupuesto."""
    # simulador_pro_v2 espera el dataset completo y aplica sus propios filtros
    # (lista negra, total_negocios > 15) + merge con percepcion_resumen.csv.
    # top_n=None devuelve todas las avenidas que superen los filtros.
    top_n_real = TOP_N if TOP_N is not None else len(df_raw)

    print(f"\nCalculando scores hibridos (giro={giro}, presupuesto={presupuesto})...")
    df = simulador_pro_v2(
        data        = df_raw,
        giro        = giro,
        presupuesto = presupuesto,
        top_n       = top_n_real,
    )
    print(f"   -> {len(df):,} avenidas con score calculado.")

    # Filtro adicional de actividad minima (por encima del umbral del scoring)
    df = df[df["total_negocios"] >= MIN_NEGOCIOS].copy()
    print(f"   -> {len(df):,} avenidas con >={MIN_NEGOCIOS} negocios.")

    # Filtro de score minimo
    df = df[df["score_final"] >= MIN_SCORE].copy()
    print(f"   -> {len(df):,} avenidas con score_final >= {MIN_SCORE}.")

    # Percentiles para colores de marcadores (sobre el dataset filtrado)
    p33 = df["score_final"].quantile(0.33)
    p66 = df["score_final"].quantile(0.66)
    print(f"   -> Percentiles de score_final: p33={p33:.2f}, p66={p66:.2f}")

    # Resumen del score hibrido en consola
    print(f"\n   {'Avenida':<30} {'Modelo':>8} {'Humano':>8} {'Final':>8}")
    print(f"   {'-'*30} {'-'*8} {'-'*8} {'-'*8}")
    for _, row in df.head(10).iterrows():
        print(
            f"   {row['avenida']:<30} "
            f"{row['score_modelo']:>8.2f} "
            f"{row['score_humano']:>8.2f} "
            f"{row['score_final']:>8.2f}"
        )
    if len(df) > 10:
        print(f"   ... y {len(df) - 10} avenidas mas.")

    return df, p33, p66


def geocodificar_dataframe(df: pd.DataFrame) -> pd.DataFrame | None:
    """Normaliza nombres, geocodifica con cache y devuelve filas con lat/lon."""
    df = df.copy()
    df["avenida_display"] = df["avenida"].apply(normalizar)  # legible en popups
    df["avenida_query"]   = df["avenida_display"]            # para busqueda geo

    validos = df[df["avenida_display"].apply(es_nombre_valido)].copy()
    print(f"\n   -> {len(validos):,} avenidas con nombres validos para geocodificar.")

    # Limite opcional para pruebas rapidas
    if LIMITE_GEOCODIFICACION:
        validos = validos.head(LIMITE_GEOCODIFICACION)
        print(f"   -> Limitando a las top {LIMITE_GEOCODIFICACION} avenidas.")

    cache = cargar_cache(CACHE_FILE)
    print(f"\nGeocodificando avenidas (cache: {len(cache)} entradas)...")

    geolocator = Nominatim(user_agent="gdl_bi_map_v1")

    lats, lons, indices_ok = [], [], []
    nuevas_en_cache = 0

    for idx, row in validos.iterrows():
        nombre_q = row["avenida_query"]
        coords = geocodificar(geolocator, nombre_q, cache)

        if coords:
            lats.append(coords[0])
            lons.append(coords[1])
            indices_ok.append(idx)
        else:
            print(f"   x No encontrado: {nombre_q}")

        # Guardar cache cada 50 peticiones (tolerancia a interrupciones)
        nuevas_en_cache += 1
        if nuevas_en_cache % 50 == 0:
            guardar_cache(cache, CACHE_FILE)
            print(f"   Cache guardado ({len(cache)} entradas).")

    guardar_cache(cache, CACHE_FILE)
    print(f"\n   OK: {len(indices_ok)} avenidas geocodificadas exitosamente.")
    print(f"   Cache final: {len(cache)} entradas -> {CACHE_FILE}")

    if not indices_ok:
        print("Ninguna avenida pudo geocodificarse. Verifica la conexion o el dataset.")
        return None

    df_geo = validos.loc[indices_ok].copy()
    df_geo["lat"] = lats
    df_geo["lon"] = lons
    return df_geo


def _float_json(valor) -> float | None:
    """Convierte numeros de pandas/numpy a float JSON o None si faltan."""
    if pd.isna(valor):
        return None
    return float(valor)


def construir_payload_escenario(
    df_geo: pd.DataFrame,
    giro: str,
    presupuesto: str,
    p33: float,
    p66: float,
) -> dict:
    """Convierte un escenario geocodificado en datos serializables para JS."""
    markers = []
    heatmap = []

    for _, row in df_geo.dropna(subset=["lat", "lon", "score_final"]).iterrows():
        score = round(float(row["score_final"]), 2)
        score_modelo = round(float(row.get("score_modelo", 0)), 2)
        score_humano = round(float(row.get("score_humano", 0)), 2)
        color = color_por_score(score, p33, p66)

        tooltip = (
            f"{row['avenida_display']} - "
            f"Final: {score} | "
            f"Modelo: {score_modelo} | "
            f"Humano: {score_humano}"
        )

        markers.append({
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "color": color,
            "popup_html": popup_html(row.to_dict(), score, p66=p66, giro=giro),
            "tooltip": tooltip,
            "score_final": score,
            "avenida": str(row.get("avenida_display", row.get("avenida", ""))),
        })
        heatmap.append([float(row["lat"]), float(row["lon"]), score])

    return {
        "giro": giro,
        "presupuesto": presupuesto,
        "p33": _float_json(p33),
        "p66": _float_json(p66),
        "total_markers": len(markers),
        "markers": markers,
        "heatmap": heatmap,
    }


def construir_payload_interactivo(df_raw: pd.DataFrame) -> dict:
    """Precalcula todos los escenarios giro x presupuesto para el HTML."""
    escenarios = {}

    for giro in GIROS:
        escenarios[giro] = {}
        for presupuesto in PRESUPUESTOS:
            df, p33, p66 = calcular_escenario(df_raw, giro, presupuesto)
            df_geo = geocodificar_dataframe(df)

            if df_geo is None:
                escenarios[giro][presupuesto] = {
                    "giro": giro,
                    "presupuesto": presupuesto,
                    "p33": _float_json(p33),
                    "p66": _float_json(p66),
                    "total_markers": 0,
                    "markers": [],
                    "heatmap": [],
                }
                continue

            escenarios[giro][presupuesto] = construir_payload_escenario(
                df_geo=df_geo,
                giro=giro,
                presupuesto=presupuesto,
                p33=p33,
                p66=p66,
            )

    return {
        "default_giro": GIRO,
        "default_presupuesto": PRESUPUESTO,
        "giros": GIROS,
        "presupuestos": PRESUPUESTOS,
        "escenarios": escenarios,
    }


def crear_mapa_base() -> folium.Map:
    """Crea el mapa Folium base compartido por todos los escenarios."""
    return folium.Map(
        location=[GDL_LAT, GDL_LON],
        zoom_start=12,
        tiles="CartoDB positron",
    )


def inyectar_capas_interactivas(mapa: folium.Map, payload: dict) -> None:
    """Inyecta capas vacias y JS para renderizar escenarios desde JSON."""
    heat_layer = HeatMap(
        [],
        name="Heatmap hibrido",
        min_opacity=0.35,
        radius=24,
        blur=18,
        gradient={
            0.20: "#2c7bb6",
            0.45: "#abd9e9",
            0.65: "#ffffbf",
            0.82: "#fdae61",
            1.00: "#d7191c",
        },
        overlay=True,
        control=True,
        show=True,
    ).add_to(mapa)

    marker_cluster_layer = MarkerCluster(name="Avenidas").add_to(mapa)
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    marker_css = """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

      /* ════════════════════════════════════════════════════════════
         BOTTOM CONTROL CARD — estilo Google Maps / Waze
         ════════════════════════════════════════════════════════════ */
      .mapa-panel-control {
        position: fixed;
        bottom: 36px;
        left: 24px;
        z-index: 1001;
        width: 246px;
        display: flex;
        flex-direction: column;
        gap: 0;
        background: rgba(255, 255, 255, 0.97);
        border-radius: 20px;
        box-shadow:
          0 8px 32px rgba(0,0,0,0.14),
          0 2px 8px rgba(0,0,0,0.08);
        font-family: 'Inter', system-ui, sans-serif;
        overflow: hidden;
      }

      /* Franja superior de color — acento de marca */
      .mapa-panel-control::before {
        content: "";
        display: block;
        height: 4px;
        background: linear-gradient(90deg, #1a73e8 0%, #34a853 100%);
        flex-shrink: 0;
      }

      /* Contenido interno con padding */
      .mapa-panel-inner {
        padding: 15px 17px 13px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      /* Título de la card */
      .mapa-panel-card-title {
        font-size: 11px;
        font-weight: 700;
        color: #1a73e8;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin: 0;
      }

      /* ── Campos label + select ──────────────────────────────── */
      .mapa-panel-control label {
        display: flex;
        flex-direction: column;
        gap: 4px;
        cursor: pointer;
      }
      .mapa-panel-control label .field-label {
        color: #5f6368;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .mapa-panel-control select {
        width: 100%;
        height: 36px;
        border: 1.5px solid #e8eaed;
        border-radius: 10px;
        background: #f8f9fa;
        color: #202124;
        font-size: 13px;
        font-weight: 500;
        font-family: 'Inter', system-ui, sans-serif;
        padding: 0 10px;
        cursor: pointer;
        -webkit-appearance: none;
        appearance: none;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='7' viewBox='0 0 12 7'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%235f6368' stroke-width='1.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 10px center;
        padding-right: 28px;
        transition: border-color 0.15s ease, background 0.15s ease;
        outline: none;
      }
      .mapa-panel-control select:focus {
        border-color: #1a73e8;
        background-color: #fff;
      }

      /* ── Botón CTA principal ──────────────────────────────────── */
      .mapa-panel-control button {
        width: 100%;
        height: 40px;
        border: none;
        border-radius: 12px;
        background: #1a73e8;
        color: #fff;
        font-size: 13px;
        font-weight: 600;
        font-family: 'Inter', system-ui, sans-serif;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        transition: background 0.15s ease, box-shadow 0.15s ease, transform 0.1s ease;
        letter-spacing: 0.01em;
        margin-top: 2px;
      }
      .mapa-panel-control button::before {
        content: "✦";
        font-size: 11px;
        opacity: 0.85;
      }
      .mapa-panel-control button:hover {
        background: #1557b0;
        box-shadow: 0 4px 16px rgba(26, 115, 232, 0.4);
        transform: translateY(-1px);
      }
      .mapa-panel-control button:active {
        transform: translateY(0);
        box-shadow: none;
      }

      /* ── Status bar ───────────────────────────────────────────── */
      .mapa-panel-status {
        font-size: 11px;
        font-family: 'Inter', system-ui, sans-serif;
        padding: 7px 17px 12px;
        color: #80868b;
        text-align: center;
        border-top: 1px solid #f1f3f4;
        line-height: 1.4;
      }
      .mapa-panel-status.pending {
        color: #e37400;
        font-weight: 600;
      }
      .mapa-panel-status.ready {
        color: #1e8e3e;
        font-weight: 600;
      }

      /* ── Empty state — toast al centro inferior ───────────────── */
      .mapa-empty-state {
        position: fixed;
        bottom: 36px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 1000;
        background: rgba(32, 33, 36, 0.92);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        border-radius: 12px;
        color: #fff;
        font-family: 'Inter', system-ui, sans-serif;
        font-size: 13px;
        line-height: 1.5;
        padding: 12px 22px;
        text-align: center;
        white-space: nowrap;
        pointer-events: none;
      }
      .mapa-empty-state b {
        display: block;
        font-size: 13px;
        font-weight: 600;
        color: #fff;
        margin-bottom: 1px;
      }

      /* ── Marcadores ───────────────────────────────────────────── */
      .business-marker {
        width: 18px;
        height: 18px;
        border-radius: 50% 50% 50% 0;
        border: 2.5px solid white;
        box-shadow: 0 2px 8px rgba(0,0,0,0.32);
        transform: rotate(-45deg);
      }
      .business-marker > span {
        display: block;
        width: 6px;
        height: 6px;
        margin: 4px;
        border-radius: 50%;
        background: rgba(255,255,255,0.9);
      }
      .business-marker.green  { background: #00c853; }
      .business-marker.orange { background: #ff9100; }
      .business-marker.red    { background: #f44336; }

      /* ── Mobile ───────────────────────────────────────────────── */
      @media (max-width: 720px) {
        .mapa-panel-control {
          left: 12px;
          right: 12px;
          bottom: 16px;
          width: auto;
        }
        .mapa-empty-state {
          bottom: 16px;
          left: 12px;
          right: 12px;
          transform: none;
          white-space: normal;
        }
      }
    </style>
    """
    mapa.get_root().html.add_child(folium.Element(marker_css))

    giro_labels = {
        "cafeteria": "Cafetería",
        "gym": "Gimnasio",
        "restaurante": "Restaurante",
        "bar_antro": "Bar / Antro",
        "lavanderia": "Lavandería",
    }
    presupuesto_labels = {
        "bajo": "Bajo",
        "medio": "Medio",
        "alto": "Alto",
    }
    giro_options = "\n".join(
        f'<option value="{escape(g)}">{escape(giro_labels.get(g, g))}</option>'
        for g in payload["giros"]
    )
    presupuesto_options = "\n".join(
        f'<option value="{escape(p)}">{escape(presupuesto_labels.get(p, p))}</option>'
        for p in payload["presupuestos"]
    )

    panel_html = f"""
    <div class="mapa-panel-control">
      <div class="mapa-panel-inner">
        <div class="mapa-panel-card-title">Escenario de análisis</div>
        <label>
          <span class="field-label">Tipo de negocio</span>
          <select id="selector-giro">
            {giro_options}
          </select>
        </label>
        <label>
          <span class="field-label">Presupuesto</span>
          <select id="selector-presupuesto">
            {presupuesto_options}
          </select>
        </label>
        <button id="aplicar-escenario" type="button">Generar recomendación</button>
      </div>
      <div id="mapa-escenario-status" class="mapa-panel-status pending">Selecciona opciones y presiona el botón</div>
    </div>
    <div id="mapa-empty-state" class="mapa-empty-state">
      <b>Listo para explorar</b>
      Elige giro y presupuesto · presiona Generar recomendación
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(panel_html))

    renderer_js = f"""
    const MAPA_ESCENARIOS = {payload_json};
    const MAPA_LEAFLET_NAME = "{mapa.get_name()}";
    const MAPA_HEAT_LAYER_NAME = "{heat_layer.get_name()}";
    const MAPA_MARKER_CLUSTER_NAME = "{marker_cluster_layer.get_name()}";
    let MAPA_LEAFLET = null;
    let MAPA_HEAT_LAYER = null;
    let MAPA_MARKER_CLUSTER = null;

    function resolverCapasFolium() {{
      MAPA_LEAFLET = window[MAPA_LEAFLET_NAME];
      MAPA_HEAT_LAYER = window[MAPA_HEAT_LAYER_NAME];
      MAPA_MARKER_CLUSTER = window[MAPA_MARKER_CLUSTER_NAME];

      return Boolean(MAPA_LEAFLET && MAPA_HEAT_LAYER && MAPA_MARKER_CLUSTER);
    }}

    function crearIconoDinamico(color) {{
      const safeColor = ["green", "orange", "red"].includes(color) ? color : "red";
      return L.divIcon({{
        className: "",
        html: `<div class="business-marker ${{safeColor}}"><span></span></div>`,
        iconSize: [18, 18],
        iconAnchor: [9, 18],
        popupAnchor: [0, -18]
      }});
    }}

    function obtenerEscenario(giro, presupuesto) {{
      return (
        MAPA_ESCENARIOS.escenarios[giro] &&
        MAPA_ESCENARIOS.escenarios[giro][presupuesto]
      ) || null;
    }}

    function actualizarEscenario(giro, presupuesto) {{
      if (!resolverCapasFolium()) {{
        const status = document.getElementById("mapa-escenario-status");
        if (status) {{
          status.textContent = "Cargando mapa...";
        }}
        setTimeout(() => actualizarEscenario(giro, presupuesto), 100);
        return;
      }}

      const escenario = obtenerEscenario(giro, presupuesto);
      if (!escenario) {{
        console.warn("Escenario no encontrado", giro, presupuesto);
        return;
      }}

      MAPA_MARKER_CLUSTER.clearLayers();
      MAPA_HEAT_LAYER.setLatLngs(escenario.heatmap || []);

      (escenario.markers || []).forEach((item) => {{
        const marker = L.marker([item.lat, item.lon], {{
          icon: crearIconoDinamico(item.color)
        }});

        marker.bindPopup(item.popup_html || "", {{ maxWidth: 320 }});

        if (item.tooltip) {{
          marker.bindTooltip(item.tooltip);
        }}

        MAPA_MARKER_CLUSTER.addLayer(marker);
      }});

      MAPA_LEAFLET.fire("escenario:actualizado", {{
        giro,
        presupuesto,
        totalMarkers: escenario.total_markers || 0
      }});

      const status = document.getElementById("mapa-escenario-status");
      if (status) {{
        const total = escenario.total_markers || 0;
        status.textContent = `Top ${{total}} oportunidades detectadas`;
        status.classList.remove("pending");
        status.classList.add("ready");
      }}

      const emptyState = document.getElementById("mapa-empty-state");
      if (emptyState) {{
        emptyState.style.display = "none";
      }}
    }}

    function marcarSeleccionPendiente() {{
      const status = document.getElementById("mapa-escenario-status");
      if (status) {{
        status.textContent = "Cambios sin aplicar";
        status.classList.remove("ready");
        status.classList.add("pending");
      }}
    }}

    function inicializarPanelEscenarios() {{
      if (!resolverCapasFolium()) {{
        setTimeout(inicializarPanelEscenarios, 100);
        return;
      }}

      const giroSelect = document.getElementById("selector-giro");
      const presupuestoSelect = document.getElementById("selector-presupuesto");
      const aplicarButton = document.getElementById("aplicar-escenario");

      if (!giroSelect || !presupuestoSelect) {{
        return;
      }}

      giroSelect.value = MAPA_ESCENARIOS.default_giro;
      presupuestoSelect.value = MAPA_ESCENARIOS.default_presupuesto;

      function renderSeleccionActual() {{
        actualizarEscenario(giroSelect.value, presupuestoSelect.value);
      }}

      giroSelect.addEventListener("change", marcarSeleccionPendiente);
      presupuestoSelect.addEventListener("change", marcarSeleccionPendiente);
      if (aplicarButton) {{
        aplicarButton.addEventListener("click", renderSeleccionActual);
      }}
      marcarSeleccionPendiente();
    }}

    window.MAPA_ESCENARIOS = MAPA_ESCENARIOS;
    window.actualizarEscenario = actualizarEscenario;
    if (document.readyState === "loading") {{
      document.addEventListener("DOMContentLoaded", inicializarPanelEscenarios);
    }} else {{
      inicializarPanelEscenarios();
    }}
    """
    mapa.get_root().script.add_child(folium.Element(renderer_js))


def main() -> None:
    print("\n🗺  Generador de Mapa — Guadalajara Business Intelligence")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Cargar dataset y obtener ranking con score híbrido real
    # ------------------------------------------------------------------
    print(f"\n📂 Cargando {CSV_ENTRADA}...")
    df_raw = pd.read_csv(CSV_ENTRADA)
    print(f"   → {len(df_raw):,} avenidas en total.")

    print("\nPrecalculando escenarios para el mapa interactivo...")
    payload = construir_payload_interactivo(df_raw)

    # ------------------------------------------------------------------
    # 2. Construir mapa Folium con capas dinamicas
    # ------------------------------------------------------------------
    print(f"\nConstruyendo mapa interactivo...")

    mapa = crear_mapa_base()
    inyectar_capas_interactivas(mapa, payload)

    # Leyenda personalizada en HTML — actualizada para mencionar score híbrido
    leyenda_html = """
    <div style="
        position: fixed;
        bottom: 36px; right: 16px;
        z-index: 1000;
        background: rgba(255,255,255,0.95);
        backdrop-filter: blur(6px);
        -webkit-backdrop-filter: blur(6px);
        padding: 10px 14px;
        border-radius: 14px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.10);
        font-family: 'Inter', system-ui, sans-serif;
        font-size: 11px;
        min-width: 140px;
    ">
        <div style="font-size:10px; font-weight:700; color:#5f6368; letter-spacing:0.07em; text-transform:uppercase; margin-bottom:9px;">
          Score híbrido
        </div>
        <div style="display:flex; flex-direction:column; gap:7px;">
          <div style="display:flex; align-items:center; gap:9px;">
            <span style="width:9px;height:9px;border-radius:50%;background:#00c853;flex-shrink:0;display:inline-block;box-shadow:0 0 0 2px rgba(0,200,83,0.2);"></span>
            <span style="color:#202124; font-weight:500;">Alto</span>
            <span style="color:#9aa0a6; font-size:10px; margin-left:auto;">p66+</span>
          </div>
          <div style="display:flex; align-items:center; gap:9px;">
            <span style="width:9px;height:9px;border-radius:50%;background:#ff9100;flex-shrink:0;display:inline-block;box-shadow:0 0 0 2px rgba(255,145,0,0.2);"></span>
            <span style="color:#202124; font-weight:500;">Medio</span>
            <span style="color:#9aa0a6; font-size:10px; margin-left:auto;">p33–66</span>
          </div>
          <div style="display:flex; align-items:center; gap:9px;">
            <span style="width:9px;height:9px;border-radius:50%;background:#f44336;flex-shrink:0;display:inline-block;box-shadow:0 0 0 2px rgba(244,67,54,0.2);"></span>
            <span style="color:#202124; font-weight:500;">Bajo</span>
            <span style="color:#9aa0a6; font-size:10px; margin-left:auto;">&lt;p33</span>
          </div>
        </div>
        <div style="margin-top:9px; padding-top:8px; border-top:1px solid #f1f3f4; color:#9aa0a6; font-size:9px; text-align:center; letter-spacing:0.02em;">
          80% DENUE · 20% percepción
        </div>
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(leyenda_html))

    # Título del mapa
    titulo_html = """
    <div style="
        position: fixed;
        top: 16px; left: 50%;
        transform: translateX(-50%);
        z-index: 999;
        background: rgba(255,255,255,0.95);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        padding: 10px 22px;
        border-radius: 16px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.10), 0 1px 4px rgba(0,0,0,0.06);
        font-family: 'Inter', system-ui, sans-serif;
        text-align: center;
        pointer-events: none;
        white-space: nowrap;
    ">
        <div style="font-size:15px; font-weight:700; color:#202124; letter-spacing:-0.01em; line-height:1.2;">
          BI Guadalajara
        </div>
        <div style="font-size:11px; font-weight:400; color:#5f6368; margin-top:2px; letter-spacing:0.01em;">
          Explorador de potencial comercial urbano
        </div>
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(titulo_html))

    folium.LayerControl().add_to(mapa)

    # ------------------------------------------------------------------
    # 3. Guardar
    # ------------------------------------------------------------------
    mapa.save(str(HTML_INTERACTIVO))
    print(f"\nMapa guardado: {HTML_INTERACTIVO}")
    print(f"   Abre el archivo en tu navegador para explorar el mapa.\n")


if __name__ == "__main__":
    main()
