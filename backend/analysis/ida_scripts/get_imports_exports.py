#!/usr/bin/env python3
"""IDAPython script — import / export table extraction.

Reads ``IDA_ANALYSIS_BIN_PATH`` and ``IDA_OUTPUT_PATH`` from the
environment, opens the database, enumerates import and export
tables, and writes a JSON result.

Result keys match ``ImportsExportsResult`` in ``base.py``.
"""

from __future__ import annotations

import json
import os
import sys

try:
    import ida_auto
    import ida_idaapi
    import ida_nalt
except ImportError:
    sys.exit("This script must be run inside IDA Pro (idat64 / idal64).")


def _get_imports() -> list[dict]:
    """Enumerate all imported modules and their symbols."""
    imports: list[dict] = []
    mod_qty = ida_nalt.get_import_module_qty()

    for mod_idx in range(mod_qty):
        mod_name = ida_nalt.get_import_module_name(mod_idx)
        if not mod_name:
            continue

        symbols: list[dict] = []

        def _import_cb(ea: int, name: str | None, ordinal: int) -> int:
            """Callback invoked per import entry."""
            symbols.append({
                "address": ea,
                "name": name if name else f"ord_{ordinal}",
                "ordinal": ordinal,
            })
            return 1  # continue enumeration

        ida_nalt.enum_import_names(mod_name, mod_idx, _import_cb)

        imports.append({
            "module": mod_name,
            "symbols": symbols,
        })

    return imports


def _get_exports() -> list[dict]:
    """Enumerate all exported symbols."""
    exports: list[dict] = []
    exp_qty = ida_nalt.get_export_qty()

    for exp_idx in range(exp_qty):
        ordinal = ida_nalt.get_export_ordinal(exp_idx)
        name = ida_nalt.get_export_name(exp_idx)
        target = ida_nalt.get_export_ordinal_by_ordinal(ordinal)
        exports.append({
            "ordinal": ordinal,
            "name": name if name else f"ord_{ordinal}",
            "target_ea": target,
        })

    return exports


def main() -> None:
    bin_path = os.environ.get("IDA_ANALYSIS_BIN_PATH")
    output_path = os.environ.get("IDA_OUTPUT_PATH")

    if not bin_path or not output_path:
        sys.exit("ERROR: IDA_ANALYSIS_BIN_PATH and IDA_OUTPUT_PATH must be set.")

    ida_idaapi.open_database(bin_path, True)
    ida_auto.auto_wait()

    result: dict = {
        "imports": _get_imports(),
        "exports": _get_exports(),
        "has_exceptions": False,  # IDAPython does not expose SEH/exception dir directly
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    ida_idaapi.close_database(True)


if __name__ == "__main__":
    main()
