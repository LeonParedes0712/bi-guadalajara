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
# Cuántas avenidas incluir en el ranking que se muestra en el mapa.
# None = todas las que pasen los filtros de scoring.
HTML_SALIDA = Path(f"mapa_{GIRO}_{PRESUPUESTO}.html")
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

def main() -> None:
    print("\n🗺  Generador de Mapa — Guadalajara Business Intelligence")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Cargar dataset y obtener ranking con score híbrido real
    # ------------------------------------------------------------------
    print(f"\n📂 Cargando {CSV_ENTRADA}...")
    df_raw = pd.read_csv(CSV_ENTRADA)
    print(f"   → {len(df_raw):,} avenidas en total.")

    # simulador_pro_v2 espera el dataset completo y aplica sus propios filtros
    # (lista negra, total_negocios > 15) + merge con percepcion_resumen.csv.
    # top_n=None devuelve todas las avenidas que superen los filtros.
    top_n_real = TOP_N if TOP_N is not None else len(df_raw)

    print(f"\n⚙️  Calculando scores híbridos (giro={GIRO}, presupuesto={PRESUPUESTO})...")
    df = simulador_pro_v2(
        data        = df_raw,
        giro        = GIRO,
        presupuesto = PRESUPUESTO,
        top_n       = top_n_real,
    )
    print(f"   → {len(df):,} avenidas con score calculado.")

    # Filtro adicional de actividad mínima (por encima del umbral del scoring)
    df = df[df["total_negocios"] >= MIN_NEGOCIOS].copy()
    print(f"   → {len(df):,} avenidas con ≥{MIN_NEGOCIOS} negocios.")

    # Filtro de score mínimo
    df = df[df["score_final"] >= MIN_SCORE].copy()
    print(f"   → {len(df):,} avenidas con score_final ≥ {MIN_SCORE}.")

    # Percentiles para colores de marcadores (sobre el dataset filtrado)
    p33 = df["score_final"].quantile(0.33)
    p66 = df["score_final"].quantile(0.66)
    print(f"   → Percentiles de score_final: p33={p33:.2f}, p66={p66:.2f}")

    # Resumen del score híbrido en consola
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
        print(f"   ... y {len(df) - 10} avenidas más.")

    # ------------------------------------------------------------------
    # 2. Normalizar nombres para geocodificación
    # ------------------------------------------------------------------
    df["avenida_display"] = df["avenida"].apply(normalizar)  # legible en popups
    df["avenida_query"]   = df["avenida_display"]            # para búsqueda geo

    validos = df[df["avenida_display"].apply(es_nombre_valido)].copy()
    print(f"\n   → {len(validos):,} avenidas con nombres válidos para geocodificar.")

    # Límite opcional para pruebas rápidas
    if LIMITE_GEOCODIFICACION:
        validos = validos.head(LIMITE_GEOCODIFICACION)
        print(f"   → Limitando a las top {LIMITE_GEOCODIFICACION} avenidas.")

    # ------------------------------------------------------------------
    # 3. Geocodificación con caché
    # ------------------------------------------------------------------
    cache = cargar_cache(CACHE_FILE)
    print(f"\n🌐 Geocodificando avenidas (caché: {len(cache)} entradas)...")

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
            print(f"   ✗ No encontrado: {nombre_q}")

        # Guardar caché cada 50 peticiones (tolerancia a interrupciones)
        nuevas_en_cache += 1
        if nuevas_en_cache % 50 == 0:
            guardar_cache(cache, CACHE_FILE)
            print(f"   💾 Caché guardado ({len(cache)} entradas).")

    guardar_cache(cache, CACHE_FILE)
    print(f"\n   ✅ {len(indices_ok)} avenidas geocodificadas exitosamente.")
    print(f"   💾 Caché final: {len(cache)} entradas → {CACHE_FILE}")

    if not indices_ok:
        print("⛔ Ninguna avenida pudo geocodificarse. Verifica la conexión o el dataset.")
        return

    # Sub-dataset solo con avenidas geocodificadas
    df_geo = validos.loc[indices_ok].copy()
    df_geo["lat"] = lats
    df_geo["lon"] = lons

    # ------------------------------------------------------------------
    # 4. Construir mapa Folium
    # ------------------------------------------------------------------
    print(f"\n🗺  Construyendo mapa interactivo...")

    mapa = folium.Map(
        location=[GDL_LAT, GDL_LON],
        zoom_start=12,
        tiles="CartoDB positron",
    )

    heat_data = [
        [float(row["lat"]), float(row["lon"]), float(row["score_final"])]
        for _, row in df_geo.dropna(subset=["lat", "lon", "score_final"]).iterrows()
    ]

    HeatMap(
        heat_data,
        name="Heatmap híbrido",
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

    marker_cluster_layer = MarkerCluster(name="Avenidas")

    for _, row in df_geo.iterrows():
        score  = round(float(row["score_final"]), 2)
        color  = color_por_score(score, p33, p66)
        popup  = folium.Popup(
                     popup_html(row.to_dict(), score, p66=p66, giro=GIRO),
                     max_width=320,
                 )
        tooltip = (
            f"{row['avenida_display']} — "
            f"Final: {score} | "
            f"Modelo: {round(float(row['score_modelo']), 2)} | "
            f"Humano: {round(float(row['score_humano']), 2)}"
        )

        folium.Marker(
            location=[row["lat"], row["lon"]],
            popup=popup,
            tooltip=tooltip,
            icon=icono_marcador(color),
        ).add_to(marker_cluster_layer)

    marker_cluster_layer.add_to(mapa)

    # Leyenda personalizada en HTML — actualizada para mencionar score híbrido
    leyenda_html = """
    <div style="
        position: fixed;
        bottom: 40px; left: 40px;
        z-index: 1000;
        background: white;
        padding: 14px 18px;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.25);
        font-family: sans-serif;
        font-size: 13px;
        line-height: 1.7;
    ">
        <b style="font-size:14px;">📊 Score Híbrido</b><br>
        <span style="font-size:11px; color:#555;">
          80% modelo DENUE + 20% percepción
        </span><br><br>
        <span style="color:green;">●</span> Alto (p66+)<br>
        <span style="color:orange;">●</span> Medio (p33–p66)<br>
        <span style="color:red;">●</span> Bajo (&lt;p33)
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(leyenda_html))

    # Título del mapa
    titulo_html = """
    <div style="
        position: fixed;
        top: 14px; left: 50%;
        transform: translateX(-50%);
        z-index: 1000;
        background: rgba(255,255,255,0.92);
        padding: 8px 20px;
        border-radius: 8px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        font-family: sans-serif;
        font-size: 15px;
        font-weight: bold;
        color: #1a1a2e;
    ">
        🏙 BI Guadalajara — Potencial Comercial por Avenida
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(titulo_html))

    folium.LayerControl().add_to(mapa)

    # ------------------------------------------------------------------
    # 5. Guardar
    # ------------------------------------------------------------------
    mapa.save(str(HTML_SALIDA))
    print(f"\n✅ Mapa guardado: {HTML_SALIDA}")
    print(f"   Abre el archivo en tu navegador para explorar el mapa.\n")


if __name__ == "__main__":
    main()
