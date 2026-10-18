import os
import re
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSlot, pyqtProperty, pyqtSignal

from cura.CuraApplication import CuraApplication
from cura.MachineAction import MachineAction

from UM.Logger import Logger
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM.Settings.DefinitionContainer import DefinitionContainer
from UM.i18n import i18nCatalog

catalog = i18nCatalog("cura")

from .Dremel3DSettings import delete_config, get_config, save_config


class Dremel3DAction(MachineAction):
    def __init__(self, parent: QObject = None) -> None:
        super().__init__("Dremel3DAction", catalog.i18nc("@action", "Connect Dremel"))

        self._qml_url = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "resources",
            "qml",
            "Dremel3DConfiguration.qml",
        )

        self._application = CuraApplication.getInstance()
        self._application.globalContainerStackChanged.connect(
            self._onGlobalContainerStackChanged
        )
        ContainerRegistry.getInstance().containerAdded.connect(self._onContainerAdded)

    def _onGlobalContainerStackChanged(self) -> None:
        self.printerSettingsUrlChanged.emit()

    def _onContainerAdded(self, container: "ContainerInterface") -> None:
        # The Dremel definitions are named "Dremel3D40", "Dremel3D45", ...
        # Matching on the definition's id keeps this action off other printers.
        if (
            isinstance(container, DefinitionContainer)
            and container.getMetaDataEntry("type") == "machine"
            and container.getId().startswith("Dremel")
        ):
            self._application.getMachineActionManager().addSupportedAction(
                container.getId(), self.getKey()
            )

    def _reset(self) -> None:
        self.printerSettingsUrlChanged.emit()

    printerSettingsUrlChanged = pyqtSignal()

    @pyqtProperty(str, notify=printerSettingsUrlChanged)
    def printerSettingUrl(self) -> Optional[str]:
        s = get_config()
        if s:
            return s.get("url", "")
        return ""

    @pyqtSlot(str)
    def saveConfig(self, url):
        if not url.endswith("/"):
            url += "/"

        save_config(url)
        Logger.log("d", "config saved")

        # trigger a stack change to reload the output devices
        self._application.globalContainerStackChanged.emit()

    @pyqtSlot()
    def deleteConfig(self):
        if delete_config():
            Logger.log("d", "config deleted")

            # trigger a stack change to reload the output devices
            self._application.globalContainerStackChanged.emit()
        else:
            Logger.log("d", "no config to delete")

    @pyqtSlot(str, result=bool)
    def validUrl(self, newUrl):
        if newUrl.startswith("\\\\"):
            # no UNC paths
            return False
        if not re.match("^https?://.", newUrl):
            # missing https?://
            return False
        if "@" in newUrl:
            # @ is probably HTTP basic auth, which is a separate setting
            return False

        return True
