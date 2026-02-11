"""Shared fixtures for Deye Dashboard tests."""
import pytest
from unittest.mock import patch, MagicMock
from inverter import DeyeInverter


@pytest.fixture
def mock_inverter():
    """Create a DeyeInverter with a mocked PySolarmanV5 connection."""
    with patch("inverter.PySolarmanV5"):
        inv = DeyeInverter(ip="192.168.1.1", serial=123456)
        inv.inverter = MagicMock()
        return inv


def mock_read_register(register_values):
    """Return a side_effect function that maps register addresses to values.

    Usage:
        inverter.read_register = mock_read_register({587: 5200, 588: 75})
    """
    def read_register(addr):
        return register_values.get(addr, 0)
    return read_register
