from collections.abc import Sequence

from esphome.core import CORE
from esphome.framework_helpers import (
    cmake_escape,
    get_cmake_compile_flags,
    get_cmake_link_flags,
    lex_cmake_build_flags,
    quote_cmake_args,
)
from esphome.helpers import write_file_if_changed


def write_cmake_project(
    build_name: str, extra_compile_lines: Sequence[str] = ()
) -> bool:
    """Write the project CMakeLists.txt, returning True if it changed."""
    entries = lex_cmake_build_flags(build_name)
    compile_flags = get_cmake_compile_flags(entries)
    link_flags = get_cmake_link_flags(entries)

    # Convert any PlatformIO libraries added via cg.add_library() into Zephyr
    # modules and discover them through EXTRA_ZEPHYR_MODULES (a CMake list, set
    # before find_package(Zephyr) so the modules are picked up). Only
    # framework-agnostic libraries actually compile under Zephyr.
    from esphome.components.zephyr.library import DEFINES_VAR, generate_zephyr_modules

    module_dirs = generate_zephyr_modules(list(CORE.platformio_libraries.values()))
    defines = [flag for flag in compile_flags if flag.startswith("-D")]
    options = [flag for flag in compile_flags if not flag.startswith("-D")]

    lines = [
        "cmake_minimum_required(VERSION 3.20.0)",
        "",
        'set(Zephyr_DIR "$ENV{ZEPHYR_BASE}/share/zephyr-package/cmake/")',
        "",
    ]

    if module_dirs:
        modules = ";".join(str(d).replace("\\", "/") for d in module_dirs)
        lines += [f'set(EXTRA_ZEPHYR_MODULES "{modules}")', ""]
        if defines:
            escaped = ";".join(cmake_escape(flag) for flag in defines)
            lines += [f'set({DEFINES_VAR} "{escaped}")', ""]

    lines += [
        "find_package(Zephyr REQUIRED)",
        "",
        f"project({CORE.name})",
        "",
        'file(GLOB_RECURSE APP_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/../src/*.cpp" "${CMAKE_CURRENT_LIST_DIR}/../src/*.c")',
        "",
        "target_sources(app PRIVATE ${APP_SOURCES})",
        'target_include_directories(app PRIVATE "${CMAKE_CURRENT_LIST_DIR}/../src")',
    ]

    if defines:
        lines += [
            "",
            "target_compile_options(app PRIVATE",
            *[f"  {arg}" for arg in quote_cmake_args(defines)],
            ")",
        ]
    if options:
        # A target's own options come before the ones it inherits from zephyr_interface, and the
        # compiler keeps the last of two opposing warning flags. Source options come after both.
        lines += [
            "",
            "set_source_files_properties(${APP_SOURCES} PROPERTIES",
            f'  COMPILE_OPTIONS "{";".join(cmake_escape(flag) for flag in options)}"',
            ")",
        ]

    lines.extend(extra_compile_lines)

    if link_flags:
        lines += [
            "",
            "zephyr_ld_options(",
            *[f"  {arg}" for arg in quote_cmake_args(link_flags)],
            ")",
        ]

    return write_file_if_changed(
        CORE.relative_build_path("zephyr", "CMakeLists.txt"),
        "\n".join(lines) + "\n",
    )
