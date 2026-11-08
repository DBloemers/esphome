"""ESPHome platform for Silicon Labs EFR32 devices using upstream Zephyr."""

import os
from pathlib import Path
import shutil

import esphome.codegen as cg
from esphome.components.zephyr import (
    copy_files as copy_files,
    zephyr_add_prj_conf,
    zephyr_data,
    zephyr_set_core_data,
    zephyr_setup_preferences,
    zephyr_to_code,
)
from esphome.components.zephyr.build import write_cmake_project
from esphome.components.zephyr.const import KEY_BOARD, KEY_BOOTLOADER
import esphome.config_validation as cv
from esphome.const import (
    CONF_BOARD,
    KEY_CORE,
    KEY_FRAMEWORK_VERSION,
    KEY_TARGET_FRAMEWORK,
    KEY_TARGET_PLATFORM,
    Framework,
    Platform,
    ThreadModel,
    Toolchain,
)
from esphome.core import CORE, CoroPriority, EsphomeError, coroutine_with_priority
from esphome.framework_helpers import run_command_ok
from esphome.helpers import copy_file_if_changed
from esphome.storage_json import StorageJSON
from esphome.types import ConfigType

# Import the GPIO module to register the EFR32 pin schema.
from . import gpio as gpio

AUTO_LOAD = ["zephyr"]
DOMAIN = "efr32"
IS_TARGET_PLATFORM = True


def set_core_data(config: ConfigType) -> ConfigType:
    zephyr_set_core_data({CONF_BOARD: config[CONF_BOARD], KEY_BOOTLOADER: ""})
    CORE.data[KEY_CORE][KEY_TARGET_PLATFORM] = Platform.EFR32
    CORE.data[KEY_CORE][KEY_TARGET_FRAMEWORK] = Framework.ZEPHYR
    CORE.data[KEY_CORE][KEY_FRAMEWORK_VERSION] = cv.Version(4, 5, 99)
    return config


CONFIG_SCHEMA = cv.All(
    cv.Schema({cv.Required(CONF_BOARD): cv.one_of("arduino_nano_matter", lower=True)}),
    cv.resolve_toolchain("EFR32", (Toolchain.ZEPHYR,), Toolchain.ZEPHYR),
    set_core_data,
)


@coroutine_with_priority(CoroPriority.PLATFORM)
async def to_code(config: ConfigType) -> None:
    cg.add_build_flag("-DUSE_EFR32")
    cg.add_define("ESPHOME_BOARD", config[CONF_BOARD])
    cg.add_define("ESPHOME_VARIANT", "EFR32MG24")
    cg.add_define(ThreadModel.MULTI_ATOMICS)

    zephyr_add_prj_conf("CPP", True)
    zephyr_add_prj_conf("REQUIRES_FULL_LIBCPP", True)
    zephyr_add_prj_conf("GPIO", True)
    zephyr_add_prj_conf("HWINFO", True)
    zephyr_add_prj_conf("REBOOT", True)
    # The ESPHome logger writes directly to the UART chosen in the board DTS.
    zephyr_add_prj_conf("CONSOLE", False, required=False)
    zephyr_add_prj_conf("UART_CONSOLE", False)
    zephyr_add_prj_conf("THREAD_LOCAL_STORAGE", True)
    zephyr_setup_preferences()
    zephyr_to_code(config)


def run_compile(args: object, config: ConfigType) -> bool:
    """Build with the user-provided upstream Zephyr west workspace."""
    zephyr_base = os.environ.get("ZEPHYR_BASE")
    if not zephyr_base or not (Path(zephyr_base) / "west.yml").is_file():
        raise EsphomeError(
            "Set ZEPHYR_BASE to the Zephyr checkout in a west workspace."
        )
    if (west := shutil.which("west")) is None:
        raise EsphomeError("Put the Zephyr workspace's west executable on PATH.")

    build_dir = CORE.relative_pioenvs_path(CORE.name)
    project_changed = write_cmake_project("EFR32")
    pristine = (
        "always"
        if project_changed or not (build_dir / "CMakeCache.txt").is_file()
        else "auto"
    )
    if not run_command_ok(
        [
            west,
            "build",
            f"--pristine={pristine}",
            "-b",
            zephyr_data()[KEY_BOARD],
            "-d",
            str(build_dir),
            str(CORE.relative_build_path("zephyr")),
        ],
        cwd=zephyr_base,
        stream_output=True,
    ):
        raise EsphomeError("EFR32 Zephyr build failed")

    copy_file_if_changed(build_dir / "zephyr" / "zephyr.bin", CORE.firmware_bin)
    return True



def get_download_types(storage_json: StorageJSON) -> list[dict[str, str]]:
    """Offer the Intel HEX image emitted by the Zephyr build."""
    if storage_json.firmware_bin_path is None:
        return []
    return [
        {
            "title": "Intel HEX (USB debugger)",
            "description": "For flashing the Arduino Nano Matter over USB with OpenOCD.",
            "file": "zephyr/zephyr.hex",
            "download": f"{storage_json.name}.hex",
        }
    ]
