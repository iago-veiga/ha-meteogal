"""Configuración común de los tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Permite cargar custom_components/meteogal en los tests de Home Assistant."""
    return
