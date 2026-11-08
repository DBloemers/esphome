"""Digital GPIO schema for the EFR32MG24."""

import re

from esphome import pins
import esphome.codegen as cg
from esphome.components.zephyr.const import zephyr_ns
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_INVERTED, CONF_MODE, CONF_NUMBER, Platform
from esphome.types import ConfigType

ZephyrGPIOPin = zephyr_ns.class_("ZephyrGPIOPin", cg.InternalGPIOPin)

# MGM240SD22VNA module GPIO counts from the Zephyr SoC devicetree.
_PORT_PINS = {"A": 10, "B": 6, "C": 10, "D": 6}
_PORT_WIDTH = 32

# Header labels from Zephyr's arduino_nano_matter_connector.dtsi.
_NANO_MATTER_PINS = {
    "D0": "PA4",
    "D1": "PA5",
    "D2": "PA3",
    "D3": "PC6",
    "D4": "PC7",
    "D5": "PC8",
    "D6": "PC9",
    "D7": "PD2",
    "D8": "PD3",
    "D9": "PD4",
    "D10": "PD5",
    "D11": "PA9",
    "D12": "PA8",
    "D13": "PB4",
    "A0": "PB0",
    "A1": "PB2",
    "A2": "PB5",
    "A3": "PC0",
    "A4": "PA6",
    "A5": "PA7",
    "A6": "PB1",
    "A7": "PB3",
}


def validate_gpio_pin(value: object) -> int:
    if not isinstance(value, str):
        raise cv.Invalid("Use a pin label such as D13, A0, or PC1.")
    label = value.strip().upper()
    label = _NANO_MATTER_PINS.get(label, label)
    if (match := re.fullmatch(r"P([A-D])([0-9]{1,2})", label)) is None:
        raise cv.Invalid("Use a pin label such as D13, A0, or PC1.")
    port, pin_text = match.groups()
    pin = int(pin_text)
    if pin >= _PORT_PINS[port]:
        raise cv.Invalid(f"Invalid MGM240S pin P{port}{pin}.")
    return (ord(port) - ord("A")) * _PORT_WIDTH + pin


@pins.PIN_SCHEMA_REGISTRY.register(
    Platform.EFR32, pins.gpio_base_schema(ZephyrGPIOPin, validate_gpio_pin)
)
async def efr32_pin_to_code(config: ConfigType) -> cg.MockObj:
    pin = config[CONF_NUMBER]
    port = chr(ord("A") + pin // _PORT_WIDTH)
    var = cg.new_Pvariable(
        config[CONF_ID],
        cg.RawExpression(f"DEVICE_DT_GET(DT_NODELABEL(gpio{port.lower()}))"),
        _PORT_WIDTH,
        f"P{port}",
    )
    cg.add(var.set_pin(pin))
    if config[CONF_INVERTED]:
        cg.add(var.set_inverted(True))
    cg.add(var.set_flags(pins.gpio_flags_expr(config[CONF_MODE])))
    return var
