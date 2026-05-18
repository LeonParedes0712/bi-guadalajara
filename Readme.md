# BI Guadalajara — Engine de Rentabilidad

Proyecto en Python para analizar avenidas y corredores comerciales en Guadalajara utilizando datos del INEGI (DENUE, CPV y CE), combinados con percepción urbana obtenida mediante encuestas.

El objetivo es identificar zonas con alto potencial para distintos tipos de negocios mediante un modelo híbrido de análisis comercial.

---

## Descripción

El sistema evalúa avenidas de Guadalajara utilizando:

* Densidad comercial
* Validación de mercado
* Nivel socioeconómico estimado
* Saturación comercial
* Flujo económico
* Competencia por giro
* Percepción humana y heurísticas urbanas

El modelo combina:
* **80%** datos cuantitativos (INEGI / DENUE)
* **20%** percepción urbana por encuestas

El resultado es un ranking de avenidas con mayor potencial comercial para diferentes escenarios de negocio.

---

## Pipeline del Proyecto

```text
carga_datos
    ↓
construccion_dataset
    ↓
scoring
    ↓
visualizacion
    ↓
mapa interactivo
Componentes
carga_datos.py

Carga archivos CPV, CE y DENUE.

Procesa DENUE en chunks.

Extrae indicadores estratégicos.

construccion_dataset.py

Agrupa negocios por avenida.

Integra variables socioeconómicas.

Construye el dataset maestro.

scoring.py

Calcula:

Demanda comercial

Validación de mercado

Compatibilidad con presupuesto

Saturación

Score híbrido final

Integra además la capa de percepción humana.

limpieza_forms.py

Procesa encuestas urbanas:

Limpieza de respuestas

Extracción de avenidas

Detección de insights

Generación de datasets de percepción

mapa.py

Genera mapas interactivos usando:

Folium

Geocoding

Marker clustering

Popups dinámicos

Ranking híbrido

visualizacion.py

Imprime rankings.

Genera gráficas.

Estructura del Proyecto
Plaintext
proyecto_estudio_mercado/
│
├── main.py
├── carga_datos.py
├── construccion_dataset.py
├── scoring.py
├── visualizacion.py
├── mapa.py
├── limpieza_forms.py
├── integrar_percepcion.py
├── dataset_gdl_final.csv
├── percepcion_resumen.csv
├── data/
│   ├── denue_inegi_14_.csv
│   ├── cpv_valor_14.csv
│   ├── ce_valor_14.csv
│   └── forms...
│
└── mapas_generados/
Instalación
Instalar dependencias:

Bash
pip install pandas numpy matplotlib folium geopy
Datos requeridos
Colocar dentro de data/:

denue_inegi_14_.csv

cpv_valor_14.csv

ce_valor_14.csv

Opcionalmente:

Formularios de percepción urbana

Datasets auxiliares

Cómo Ejecutar
Generar ranking:

Bash
python main.py

* **Generar mapa interactivo:**
    ```bash
    python mapa.py
    
Procesar encuestas:

Bash
python limpieza_forms.py

* **Integrar percepción humana:**
    ```bash
    python integrar_percepcion.py
    
Configuración
En main.py y mapa.py:

Python
GIRO = "cafeteria"
PRESUPUESTO = "alto"
TOP_N = 50
Opciones de giro
cafeteria

gym

restaurante

bar_antro

lavanderia

Opciones de presupuesto
bajo

medio

alto

Modelo Híbrido
El score final combina:

1. Modelo Cuantitativo
Basado en:

DENUE

CPV

CE

Densidad comercial

Saturación

NSE (Nivel Socioeconómico)

Validación de mercado

2. Modelo Cualitativo
Basado en:

Percepción urbana

Conocimiento local

Heurísticas humanas

Saturación percibida

Zonas emergentes

Encuestas Urbanas
El sistema puede integrar respuestas humanas sobre:

Percepción premium

Flujo peatonal

Seguridad

Saturación

Vida nocturna

Walkability (Caminabilidad)

Potencial de crecimiento

Las respuestas se transforman en:

Scores normalizados

Insights urbanos

Capas de percepción colectiva

Output
El proyecto genera:

Rankings
Av. Vallarta | Score Final: 82.4

CSVs
dataset_gdl_final.csv

percepcion_resumen.csv

forms_limpios.csv

insights_urbanos.csv

Mapas interactivos
mapa_cafeteria_alto.html

mapa_gym_medio.html

mapa_bar_antro_medio.html

Limitaciones
El geocoding depende de OpenStreetMap/Nominatim.

Algunas avenidas pueden agruparse visualmente.

El modelo aún no considera:

Renta comercial

Tráfico en tiempo real

Movilidad urbana

Ingresos reales por zona

Posibles Mejoras Futuras
Heatmaps dinámicos

Dashboard web

Machine Learning

Datos inmobiliarios

Integración con APIs urbanas

Sistema multi-ciudad

Predicción temporal de crecimiento

Autor
Leonardo Paredes Tecnológico de Monterrey Urban Business Intelligence Project