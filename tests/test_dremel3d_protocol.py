"""Self-check for Dremel3DProtocol.

Run it directly: python3 tests/test_dremel3d_protocol.py
"""

import json
import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Dremel3D-CuraPrintr"),
)

from Dremel3DProtocol import cancel_command, parse_status, print_command, safe_file_name

# Captured from a 3D40 over the network while it was printing.
PRINTING = {
    "buildPlate_target_temperature": 0,
    "chamber_temperature": 0,
    "door_open": 0,
    "elaspedtime": 0,
    "error_code": 200,
    "extruder_target_temperature": 220,
    "fanSpeed": 0,
    "filament_type ": "PLA",
    "firmware_version": "v1.0_R03.06.06",
    "jobname": "D_obj_1_Kopf.gcode",
    "jobstatus": "building",
    "layer": 7,
    "message": "success",
    "networkBuild": 1,
    "platform_temperature": 60,
    "progress": 14,
    "remaining": 1501,
    "status": "busy",
    "temperature": 219,
    "totalTime": 1750,
}


def test_parses_a_printing_printer():
    status = parse_status(json.dumps(PRINTING))
    assert status.is_printing
    assert status.job_name == "D_obj_1_Kopf.gcode"
    assert status.progress == 14
    assert status.remaining_s == 1501
    assert status.layer == 7
    assert status.nozzle_temp == 219
    assert status.platform_temp == 60
    assert not status.door_open
    text = status.format_text()
    assert "D_obj_1_Kopf.gcode" in text
    assert "14%" in text
    assert "25 min left" in text  # 1501 s rounded to minutes


def test_handles_the_printers_own_key_spellings():
    status = parse_status(
        json.dumps({"jobstatus": "building", "elaspedtime": 7, "filament_type ": "PLA"})
    )
    assert status.elapsed_s == 7
    assert status.filament_type == "PLA"


def test_idle_printer_is_not_printing():
    status = parse_status(json.dumps({"jobstatus": "ready", "jobname": "D3_3DBenchy.gcode"}))
    assert not status.is_printing
    assert status.format_text() == "Idle (ready)"


def test_missing_and_odd_values_do_not_crash():
    status = parse_status("{}")
    assert not status.is_printing
    assert status.progress == 0
    assert status.format_text() == "Idle (unknown)"

    status = parse_status(
        json.dumps(
            {"jobstatus": "BUILDING", "progress": "14", "remaining": None, "door_open": True}
        )
    )
    assert status.is_printing  # the status is case-insensitive
    assert status.progress == 14
    assert status.remaining_s == 0
    assert status.door_open
    assert "DOOR OPEN" in status.format_text()


def test_garbage_body_raises_value_error():
    try:
        parse_status("<html>printer login page</html>")
    except ValueError:
        return
    raise AssertionError("a garbage body must raise ValueError")


def test_safe_file_name():
    assert safe_file_name("D_obj_1_Kopf", "gcode") == "D_obj_1_Kopf.gcode"
    assert safe_file_name("D_obj_1_Kopf.gcode", "gcode") == "D_obj_1_Kopf.gcode"
    assert safe_file_name("Kopfübersicht", "gcode") == "Kopf_bersicht.gcode"
    assert safe_file_name('bad"name\r\n', "gcode") == "bad_name.gcode"
    assert safe_file_name("  ", "gcode") == "print.gcode"
    assert safe_file_name("..", "gcode") == "print.gcode"


def test_commands():
    assert print_command("a.gcode") == "PRINT=a.gcode"
    assert cancel_command("a.gcode") == "CANCEL=a.gcode"


if __name__ == "__main__":
    failures = 0
    for name in sorted(globals()):
        if name.startswith("test_"):
            try:
                globals()[name]()
            except AssertionError as exception:
                failures += 1
                print("FAIL", name, exception)
            else:
                print("ok  ", name)
    sys.exit(1 if failures else 0)
