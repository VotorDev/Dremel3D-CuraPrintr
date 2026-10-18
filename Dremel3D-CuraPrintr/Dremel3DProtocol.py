"""The Dremel3D printer's HTTP API and the data the printer sends back.

Pure Python on purpose (no Cura, no Qt) so it can be tested without Cura:
see tests/test_dremel3d_protocol.py.
"""

import json
import re

# POSTed as the request body to <printer url>command.
STATUS_COMMAND = "GETPRINTERSTATUS"

# Statuses the printer reports while a job is running. Anything else counts as
# idle, so an unknown status never claims a print is running.
PRINTING_STATUSES = ("building", "preparing", "paused")


def print_command(file_name: str) -> str:
    return "PRINT={}".format(file_name)


def cancel_command(file_name: str) -> str:
    return "CANCEL={}".format(file_name)


def safe_file_name(name: str, extension: str) -> str:
    """Normalise a suggested file name into <name>.<extension>.

    The name comes from Cura's job name, which is free text: a quote or a
    newline would corrupt the multipart header the file is uploaded in, and
    non-ASCII names are not portable across the printer's HTTP parsing.
    """
    suffix = "." + extension
    name = name.strip()
    if name.lower().endswith(suffix):
        name = name[: -len(suffix)]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip(".")
    return (name or "print") + suffix


def _text(value) -> str:
    return "" if value is None else str(value)


def _int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


class PrinterStatus:
    """One GETPRINTERSTATUS response.

    Key names are the printer's own, including its typos: ``elaspedtime`` is
    misspelled and ``filament_type `` has a trailing space.
    """

    def __init__(self, data: dict) -> None:
        self.job_name = _text(data.get("jobname"))
        self.job_status = _text(data.get("jobstatus")).lower()
        self.message = _text(data.get("message"))
        self.filament_type = _text(data.get("filament_type ", data.get("filament_type"))).strip()
        self.firmware_version = _text(data.get("firmware_version"))
        self.progress = _int(data.get("progress"))
        self.remaining_s = _int(data.get("remaining"))
        self.total_s = _int(data.get("totalTime"))
        self.elapsed_s = _int(data.get("elaspedtime"))
        self.layer = _int(data.get("layer"))
        self.nozzle_temp = _int(data.get("temperature"))
        self.nozzle_target = _int(data.get("extruder_target_temperature"))
        self.platform_temp = _int(data.get("platform_temperature"))
        self.platform_target = _int(data.get("buildPlate_target_temperature"))
        self.chamber_temp = _int(data.get("chamber_temperature"))
        self.fan_speed = _int(data.get("fanSpeed"))
        self.door_open = bool(_int(data.get("door_open")))
        self.error_code = _int(data.get("error_code"))

    @property
    def is_printing(self) -> bool:
        return self.job_status in PRINTING_STATUSES

    def format_text(self) -> str:
        """One line for Cura's message bar."""
        if not self.is_printing:
            return "Idle ({})".format(self.job_status or "unknown")
        parts = ["{} \u00b7 {}%".format(self.job_name or "unknown job", self.progress)]
        if self.remaining_s > 0:
            parts.append("{} min left".format(round(self.remaining_s / 60)))
        if self.layer:
            parts.append("layer {}".format(self.layer))
        parts.append("{} \u00b0C".format(self.nozzle_temp))
        if self.chamber_temp:
            parts.append("chamber {} \u00b0C".format(self.chamber_temp))
        if self.door_open:
            parts.append("DOOR OPEN")
        if self.message and self.message.lower() != "success":
            parts.append(self.message)
        return " \u00b7 ".join(parts)


def parse_status(body: str) -> PrinterStatus:
    """Parse a GETPRINTERSTATUS response body. Raises ValueError for garbage."""
    return PrinterStatus(json.loads(body))
