import os.path
from enum import Enum
from io import BytesIO, StringIO
from typing import cast

from cura.CuraApplication import CuraApplication

from PyQt6.QtCore import QByteArray, QUrl, QVariant
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QHttpMultiPart, QHttpPart, QNetworkReply, QNetworkRequest

from UM.i18n import i18nCatalog
from UM.Logger import Logger
from UM.Mesh.MeshWriter import MeshWriter
from UM.Message import Message
from UM.OutputDevice import OutputDeviceError
from UM.OutputDevice.OutputDevice import OutputDevice
from UM.PluginRegistry import PluginRegistry

from .Dremel3DProtocol import print_command, safe_file_name

catalog = i18nCatalog("cura")

# The printer is a LAN device: fail fast instead of leaving the output device
# busy forever on an unreachable printer.
REACHABILITY_TIMEOUT_S = 5
UPLOAD_TIMEOUT_S = 300
COMMAND_TIMEOUT_S = 5


class OutputStage(Enum):
    ready = 0
    writing = 1


class Dremel3DConfigureOutputDevice(OutputDevice):
    def __init__(self) -> None:
        super().__init__("dremel3d-configure")
        self.setShortDescription("Dremel3D Plugin")
        self.setDescription("Configure Dremel3D...")
        self.setPriority(0)

    def requestWrite(self, node, fileName=None, *args, **kwargs):
        message = Message(
            "To configure your Dremel3D printer go to:\n→ Settings\n  → Printer\n    → Manage Printers\n     → select your printer\n    → click on 'Connect Dremel'",
            lifetime=0,
            title="Configure Dremel3D in Preferences!",
        )
        message.show()
        self.writeSuccess.emit(self)


class Dremel3DOutputDevice(OutputDevice):
    def __init__(self, config, monitor=None):
        self._name_id = "dremel3d-upload"
        super().__init__(self._name_id)

        self._url = config.get("url", "")
        self._monitor = monitor

        self.application = CuraApplication.getInstance()
        global_container_stack = self.application.getGlobalContainerStack()
        self._name = global_container_stack.getName()

        description = catalog.i18nc("@action:button", "Start on {0}").format(
            self._name
        )
        self.setShortDescription(description)
        self.setDescription(description)

        self._stage = OutputStage.ready
        self._stream = None
        self._message = None

        Logger.log(
            "d",
            "New Dremel3DOutputDevice '{}' created | URL: {} ".format(
                self._name_id, self._url
            ),
        )
        self._resetState()

    def requestWrite(self, node, fileName=None, *args, **kwargs):
        if self._stage != OutputStage.ready:
            raise OutputDeviceError.DeviceBusyError()

        # Make sure post-processing plugin are run on the gcode
        self.writeStarted.emit(self)

        # The presliced print should always be send using `GCodeWriter`
        self._output_format = "gcode"
        code_writer = cast(
            MeshWriter, PluginRegistry.getInstance().getPluginObject("GCodeWriter")
        )
        self._stream = StringIO()

        if not code_writer.write(self._stream, None):
            Logger.log("e", "MeshWriter failed: %s" % code_writer.getInformation())
            return

        # Cura suggests the job name without an extension (see
        # OutputDevicesActionButton.qml), so normalise it into a name that is
        # safe in the upload's multipart header.
        if not fileName:
            fileName = self.application.getPrintInformation().jobName
        self._fileName = safe_file_name(
            os.path.basename(fileName), self._output_format
        )

        self._startPrint = True
        self.startUploading()

    def startUploading(self):
        self._stage = OutputStage.writing

        # show a progress message
        self._message = Message(
            catalog.i18nc("@info:progress", "Uploading to {}...").format(self._name),
            0,
            False,
            -1,
        )
        self._message.show()
        Logger.log("d", "Connecting to Dremel...")
        self._sendRequest(
            "", on_success=self.onInstanceOnline, timeout=REACHABILITY_TIMEOUT_S
        )

    def onInstanceOnline(self, reply):
        if self._stage != OutputStage.writing:
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._onNetworkError(reply, reply.error())
            return

        Logger.log("d", "Uploading " + self._output_format + "...")
        self._stream.seek(0)
        self._postData = QByteArray()
        if isinstance(self._stream, BytesIO):
            self._postData.append(self._stream.getvalue())
        else:
            self._postData.append(self._stream.getvalue().encode())
        self._sendRequest(
            "print_file_uploads",
            name=self._fileName,
            data=self._postData,
            on_success=self.onCodeUploaded,
            timeout=UPLOAD_TIMEOUT_S,
        )

    def onCodeUploaded(self, reply):
        if self._stage != OutputStage.writing:
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._onNetworkError(reply, reply.error())
            return

        Logger.log("d", "Upload completed")
        self._stream.close()
        self._stream = None

        if self._startPrint:
            self._sendCommand(print_command(self._fileName))
            if self._monitor:
                self._monitor.expect_print(self._fileName)
            self._showResult(
                catalog.i18nc(
                    "@info:status", "Uploaded '{}' - starting the print."
                ).format(self._fileName)
            )
        else:
            self._showResult(
                catalog.i18nc("@info:status", "Uploaded '{}' to {}.").format(
                    self._fileName, self._name
                )
            )

        self.writeSuccess.emit(self)
        self._resetState()

    def _sendCommand(self, command: str):
        """POST one command, e.g. PRINT=<file>."""
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Connection": "Keep-Alive",
        }
        data = QByteArray()
        data.append(command.encode("utf-8"))
        self.application.getHttpRequestManager().post(
            self._url + "command",
            headers,
            data,
            callback=None,
            error_callback=self._onNetworkError,
            timeout=COMMAND_TIMEOUT_S,
        )

    def _showResult(self, text: str):
        self._hide_message()
        Message(text, lifetime=10, dismissable=True).show()

    def _hide_message(self):
        if self._message:
            self._message.hide()
            self._message = None

    def _onProgress(self, progress):
        if self._message:
            self._message.setProgress(progress)
        self.writeProgress.emit(self, progress)

    def _resetState(self):
        Logger.log("d", "Reset state")
        if self._stream:
            self._stream.close()
        self._stream = None
        self._stage = OutputStage.ready
        self._fileName = None
        self._startPrint = None
        self._postData = None
        self._hide_message()

    def _onMessageActionTriggered(self, message, action):
        if action == "open_browser":
            QDesktopServices.openUrl(QUrl(self._url))
            self._hide_message()

    def _onUploadProgress(self, bytesSent, bytesTotal):
        if bytesTotal > 0:
            self._onProgress(int(bytesSent * 100 / bytesTotal))

    def _onNetworkError(self, reply, error):
        Logger.log("e", repr(error))
        self._hide_message()

        errorString = ""
        if reply:
            errorString = reply.errorString()

        message = Message(
            catalog.i18nc("@info:status", "There was a network error: {} {}").format(
                error, errorString
            ),
            0,
            False,
        )
        message.show()

        self.writeError.emit(self)
        self._resetState()

    def _sendRequest(self, path, name=None, data=None, on_success=None, on_error=None, timeout=None):
        url = self._url + path

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Connection": "Keep-Alive",
        }

        if data:
            # Create multi_part request
            parts = QHttpMultiPart(QHttpMultiPart.ContentType.FormDataType)

            part_file = QHttpPart()
            part_file.setHeader(
                QNetworkRequest.KnownHeaders.ContentDispositionHeader,
                QVariant('form-data; name="print_file"; filename="' + str(name) + '"'),
            )
            part_file.setBody(data)
            parts.append(part_file)

            headers["Content-Type"] = "multipart/form-data; boundary=" + str(
                parts.boundary().data(), encoding="utf-8"
            )

            self.application.getHttpRequestManager().post(
                url,
                headers,
                parts,
                callback=on_success,
                error_callback=on_error if on_error else self._onNetworkError,
                upload_progress_callback=self._onUploadProgress,
                timeout=timeout,
            )
        else:
            self.application.getHttpRequestManager().get(
                url,
                headers,
                callback=on_success,
                error_callback=on_error if on_error else self._onNetworkError,
                timeout=timeout,
            )
