"""
limpieza.py
-----------
Utilidades de limpieza y normalización de texto para datos INEGI.
Sin dependencias internas → se puede importar desde cualquier módulo.
"""

import re
import unicodedata

import pandas as pd


def limpiar_texto(texto) -> str:
    """
    Normaliza un texto: mayúsculas, sin acentos, sin espacios extra.
    Acepta NaN de forma segura.
    """
    if pd.isna(texto):
        return ""
    texto = str(texto).upper().strip()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8")
    return re.sub(r"\s+", " ", texto)


def clasificar_giro(nombre_actividad: str) -> str:
    """
    Clasifica un nombre de actividad DENUE en un giro comercial conocido.

    Returns:
        Una de: 'cafeteria', 'gym', 'restaurante', 'bar_antro', 'lavanderia', 'otro'
    """
    act = str(nombre_actividad).upper()

    if "CAFE" in act:
        return "cafeteria"
    if "GYM" in act or "DEPORTE" in act:
        return "gym"
    if "RESTAURANTE" in act:
        return "restaurante"
    if "BAR" in act or "ANTRO" in act:
        return "bar_antro"
    if "LAVANDERIA" in act:
        return "lavanderia"

    return "otro"
