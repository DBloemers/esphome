"""GPIO configuration for the Silicon Labs MGM240S."""

from pathlib import Path

import pytest

from esphome.components.efr32.gpio import validate_gpio_pin
from esphome.config import read_config
import esphome.config_validation as cv
from esphome.const import Platform, Toolchain
from esphome.core import CORE


@pytest.mark.parametrize(
    ("pin", "number"),
    [("PA0", 0), ("pb05", 37), ("PC9", 73), ("PD5", 101), ("d13", 36), ("A7", 35)],
)
def test_valid_pins(pin: str, number: int) -> None:
    assert validate_gpio_pin(pin) == number


@pytest.mark.parametrize("pin", ["PA10", "PB6", "PC10", "PD6", "PE0", "P0.01", 0])
def test_invalid_pins(pin: object) -> None:
    with pytest.raises(cv.Invalid):
        validate_gpio_pin(pin)


def test_nano_matter_gpio_config(tmp_path: Path) -> None:
    path = tmp_path / "nano-matter.yaml"
    path.write_text(
        """
esphome:
  name: nano-matter
efr32:
  board: arduino_nano_matter
logger:
binary_sensor:
  - platform: gpio
    name: User button
    pin:
      number: PA0
      mode: INPUT_PULLUP
      inverted: true
output:
  - platform: gpio
    id: user_led
    pin: PC1
"""
    )
    CORE.config_path = path
    config = read_config({})
    assert config is not None
    assert CORE.target_platform == Platform.EFR32
    assert CORE.toolchain == Toolchain.ZEPHYR
    assert config["logger"]["hardware_uart"] == "UART0"
    assert config["binary_sensor"][0]["use_interrupt"] is True
    assert config["output"][0]["pin"]["number"] == 65
