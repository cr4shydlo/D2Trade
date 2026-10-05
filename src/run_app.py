"""Punkt wejscia dla testow NiceGUI (pytest). Normalnie uruchamiaj d2_web.py."""
import d2_web  # noqa: F401  (import tworzy strone)
from nicegui import ui

ui.run(reload=False)
