"""Polls the printer's status and tells the user what the job is doing.

Runs on the main thread: one request at a time with a short timeout, so the UI
never blocks and nothing is shown when there is nothing to say.
"""

import time

from PyQt6.QtCore import QByteArray, QObject, QTimer

from cura.CuraApplication import CuraApplication

from UM.Logger import Logger
from UM.Message import Message

from .Dremel3DProtocol import STATUS_COMMAND, cancel_command, parse_status

POLL_INTERVAL_MS = 3000
OFFLINE_INTERVAL_MS = 15000
STATUS_TIMEOUT_S = 3
COMMAND_TIMEOUT_S = 5
PRINT_START_TIMEOUT_S = 30


class Dremel3DMonitor(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._application = CuraApplication.getInstance()
        self._url = ""
        self._timer = QTimer()
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._request_pending = False
        self._status = None
        self._status_time = 0.0
        self._offline = False
        self._expected_job = None
        self._expect_since = 0.0
        self._expected_deadline = 0.0
        self._message = Message("", lifetime=0, dismissable=True, title="Dremel3D")
        self._message_shown = False

    # -- URL lifecycle ------------------------------------------------
    def setUrl(self, url: str) -> None:
        url = url or ""
        if url == self._url:
            return
        self._url = url
        self._status = None
        self._offline = False
        self._expected_job = None
        if url:
            Logger.log("d", "Dremel3D: monitoring {}".format(url))
            self._timer.start()
            self._poll()
        else:
            self._timer.stop()
            self._hide_message()

    # -- actions ------------------------------------------------------
    def expect_print(self, file_name: str) -> None:
        """Called right after PRINT=<file> was sent to the printer."""
        self._expected_job = file_name
        self._expect_since = time.time()
        self._expected_deadline = self._expect_since + PRINT_START_TIMEOUT_S
        if self._url and not self._timer.isActive():
            self._timer.start()

    def requestCancel(self) -> None:
        if not self._url:
            self._show("No Dremel3D printer is configured for this printer.", error=True)
            return
        if not (self._status and self._status.is_printing):
            self._show("Nothing is printing on this Dremel3D printer.")
            return
        job_name = self._status.job_name
        Logger.log("d", "Dremel3D: cancelling '{}'".format(job_name))
        self._show("Cancelling '{}'...".format(job_name))
        self._post(cancel_command(job_name), timeout=COMMAND_TIMEOUT_S, error_callback=self._on_command_error)

    def show_snapshot(self) -> None:
        """Menu action: one message with the last polled status."""
        if not self._url:
            self._show("No Dremel3D printer is configured for this printer.", error=True)
        elif self._offline:
            self._show("Dremel3D printer not reachable.", error=True)
        elif self._status is None:
            self._show("No status received from the Dremel3D printer yet.")
        else:
            self._show(self._status.format_text())

    # -- polling ------------------------------------------------------
    def _poll(self) -> None:
        if not self._url or self._request_pending:
            return
        self._check_expected_job()
        self._request_pending = True
        self._post(STATUS_COMMAND, timeout=STATUS_TIMEOUT_S, callback=self._on_status, error_callback=self._on_poll_error)

    def _post(self, command: str, timeout: float, callback=None, error_callback=None) -> None:
        headers = {"User-Agent": "Mozilla/5.0", "Connection": "Keep-Alive"}
        data = QByteArray()
        data.append(command.encode("utf-8"))
        self._application.getHttpRequestManager().post(
            self._url + "command",
            headers,
            data,
            callback=callback,
            error_callback=error_callback,
            timeout=timeout,
        )

    def _on_status(self, reply) -> None:
        self._request_pending = False
        body = bytes(reply.readAll()).decode("utf-8", "replace")
        try:
            status = parse_status(body)
        except ValueError:
            Logger.log("w", "Dremel3D: could not parse printer status: {}".format(body[:200]))
            return
        self._offline = False
        self._status = status
        self._status_time = time.time()
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._check_expected_job()
        self._update_message()

    def _on_poll_error(self, reply=None, error=None) -> None:
        self._request_pending = False
        if not self._offline:
            Logger.log("w", "Dremel3D: printer not reachable ({})".format(error))
        self._offline = True
        self._timer.setInterval(OFFLINE_INTERVAL_MS)
        self._update_message()

    def _on_command_error(self, reply=None, error=None) -> None:
        Logger.log("w", "Dremel3D: command failed ({})".format(error))
        self._show("Dremel3D command failed: {}".format(error), error=True)

    # -- what the user sees -------------------------------------------
    def _check_expected_job(self) -> None:
        """Did the job we asked for actually start? Fail loudly if not."""
        if not self._expected_job:
            return
        # Only a status that arrived after the PRINT= command says anything
        # about this job; the previous one may still describe someone else's.
        if (
            self._status
            and self._status.is_printing
            and self._status_time >= self._expect_since
        ):
            expected = self._expected_job
            self._expected_job = None
            if self._status.job_name in ("", expected):
                Logger.log("d", "Dremel3D: printer started '{}'".format(expected))
            else:
                self._show("The printer is printing '{}' instead of '{}'.".format(self._status.job_name, expected), error=True)
            return
        if time.time() > self._expected_deadline:
            expected = self._expected_job
            self._expected_job = None
            # Offline already tells the user why nothing started.
            if not self._offline:
                Logger.log("w", "Dremel3D: printer did not start '{}'".format(expected))
                self._show("The printer did not start '{}'. Check the printer's screen.".format(expected), error=True)

    def _update_message(self) -> None:
        progress = None
        if self._offline:
            # Only speak up if the user was already watching a job.
            show = self._message_shown and bool(self._status and self._status.is_printing)
            text = "Dremel3D printer not reachable."
        elif self._expected_job:
            show = True
            text = "Starting '{}' on the printer...".format(self._expected_job)
        elif self._status and self._status.is_printing:
            show = True
            text = self._status.format_text()
            progress = self._status.progress
        else:
            show = False
            text = None
        if not show:
            self._hide_message()
            return
        self._message.setText(text)
        self._message.setProgress(progress)
        if not self._message_shown:
            self._message.show()
            self._message_shown = True

    def _hide_message(self) -> None:
        if self._message_shown:
            self._message.hide()
            self._message_shown = False

    def _show(self, text: str, error: bool = False) -> None:
        Message(
            text,
            lifetime=10,
            dismissable=True,
            message_type=Message.MessageType.ERROR if error else Message.MessageType.NEUTRAL,
        ).show()
