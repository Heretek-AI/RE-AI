# IDAPython analysis scripts.
#
# Each script is a standalone executable that can be launched by
# IDA's ``idat64.exe`` / ``idal64`` in batch/headless mode:
#
#   idat64 -A -S<script.py> <binary>
#
# Parameters are passed via environment variables:
#   IDA_ANALYSIS_BIN_PATH  — path to the binary to analyse
#   IDA_OUTPUT_PATH        — path for the JSON result file
#   IDA_MIN_LENGTH         — minimum string length (extract_strings)
#   IDA_SECTION_NAME       — section name (disassemble_function)
#   IDA_OFFSET             — byte offset within section (disassemble_function)
#   IDA_SIZE               — byte count / max instructions
#
# Each script writes its result as a single JSON object to
# IDA_OUTPUT_PATH.
"""
IDAPython analysis scripts for the IDA Pro backend.

Each script reads a binary, performs one analysis method, and writes
a JSON result file.  They are designed to be run by ``idat64`` /
``idal64`` in headless / batch mode.
"""
