# -*- coding: utf-8 -*-
"""
QAttributePropertyDialog: edit the main attribute properties (ATK ``SimplePropertyFrame``).

Label, minimum and maximum value, alarm and warning limits, RDS delta t and
delta value, format and unit. "Apply change" writes them with
``set_attribute_config`` in a worker thread; the shared model then gets the new
configuration through ATTR_CONF_EVENT (and is refreshed explicitly as well).
A read-only dialog shows the values without the Apply button, as ATK does when
``modifProp`` is false.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import tango

from ..qt import QtWidgets, Signal
from ..core.proxies import proxy_cache
from ..models.worker import run_async
from ..models.registry import attribute_model
from .errors import show_error

__all__ = ["QAttributePropertyDialog", "FIELDS", "apply_fields", "read_fields"]

NOT_SPECIFIED = "Not specified"

#: (key, ATK label, getter path) of the editable fields, in ATK order
FIELDS = (("label", "Label"), ("min_value", "Minimum value"), ("max_value", "Maximum value"),
          ("min_alarm", "Minimum alarm"), ("max_alarm", "Maximum alarm"),
          ("min_warning", "Min. warning"), ("max_warning", "Max. warning"),
          ("delta_t", "Delta t(ms)"), ("delta_val", "Delta Val"),
          ("format", "Format"), ("unit", "Unit"))

_ALARM_KEYS = ("min_alarm", "max_alarm", "min_warning", "max_warning", "delta_t", "delta_val")


def read_fields(cfg):
    """ {key: text} from a tango.AttributeInfoEx """
    out = {}
    for key, _ in FIELDS:
        if key in _ALARM_KEYS:
            out[key] = getattr(cfg.alarms, key)
        else:
            out[key] = getattr(cfg, key)
    return out


def apply_fields(cfg, values):
    """ Copy ``{key: text}`` into ``cfg`` (empty text = "Not specified"); returns the changed keys """
    changed = []
    for key, text in values.items():
        text = (text or "").strip()
        if key not in ("label", "format", "unit") and text == "":
            text = NOT_SPECIFIED
        target = cfg.alarms if key in _ALARM_KEYS else cfg
        if getattr(target, key) != text:
            setattr(target, key, text)
            changed.append(key)
    return changed


class QAttributePropertyDialog(QtWidgets.QDialog):
    """ Attribute property editor for one attribute (name or TangoAttributeModel).

    Signals:
        loaded(object): configuration read (tango.AttributeInfoEx)
        applied(object): None on success, else the ErrorRecord
    """

    loaded = Signal(object)
    applied = Signal(object)

    def __init__(self, attribute, parent=None, read_only=False):
        QtWidgets.QDialog.__init__(self, parent)
        self.model = attribute_model(attribute) if isinstance(attribute, str) else attribute
        self.read_only = bool(read_only)
        self._cfg = None
        self.setWindowTitle("Attribute property editor")
        layout = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QFormLayout()
        self.device_label = QtWidgets.QLabel(self.model.device_name, self)
        self.attribute_label = QtWidgets.QLabel(self.model.attr_name, self)
        head.addRow("Device", self.device_label)
        head.addRow("Attribute", self.attribute_label)
        layout.addLayout(head)
        box = QtWidgets.QGroupBox(self)
        form = QtWidgets.QFormLayout(box)
        self.fields = {}
        for key, label in FIELDS:
            w = QtWidgets.QLineEdit(box)
            w.setReadOnly(self.read_only)
            w.textEdited.connect(self._edited)
            self.fields[key] = w
            form.addRow(label, w)
        layout.addWidget(box)
        self.message = QtWidgets.QLabel(self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        row = QtWidgets.QHBoxLayout()
        self.dismiss_button = QtWidgets.QPushButton("Dismiss", self)
        self.info_button = QtWidgets.QPushButton("Information", self)
        self.apply_button = QtWidgets.QPushButton("Apply change", self)
        self.apply_button.setVisible(not self.read_only)
        self.apply_button.setEnabled(False)
        row.addWidget(self.dismiss_button)
        row.addWidget(self.info_button)
        row.addStretch(1)
        row.addWidget(self.apply_button)
        layout.addLayout(row)
        self.dismiss_button.clicked.connect(self.close)
        self.info_button.clicked.connect(self.show_information)
        self.apply_button.clicked.connect(self.apply)
        self.model.configChanged.connect(self._on_config)
        self.reload()

    def reload(self):
        """ Read the configuration from the device (asynchronous) """
        device, attr = self.model.device_name, self.model.attr_name
        self.message.setText("Reading configuration...")
        return run_async(lambda: proxy_cache.get(device).get_attribute_config_ex([attr])[0],
                         on_done=self._loaded, on_error=self._failed, source=self.model.name, owner=self)

    def _loaded(self, cfg):
        self._show(cfg)
        self.message.setText("")
        self.loaded.emit(cfg)

    def _on_config(self, cfg):
        if not self.apply_button.isEnabled():
            self._show(cfg)

    def _show(self, cfg):
        self._cfg = cfg
        for key, text in read_fields(cfg).items():
            self.fields[key].setText(text)
        self.apply_button.setEnabled(False)

    def _failed(self, err):
        self.message.setText("<font color='red'>{0}</font>".format(err.message))

    def _edited(self, *_):
        self.apply_button.setEnabled(not self.read_only and self._cfg is not None)

    def values(self):
        return {key: w.text() for key, w in self.fields.items()}

    def apply(self):
        """ Write the edited fields (asynchronous); None in read-only mode """
        if self.read_only or self._cfg is None:
            return None
        device, attr = self.model.device_name, self.model.attr_name
        values = self.values()

        def write():
            proxy = proxy_cache.get(device)
            cfg = proxy.get_attribute_config_ex([attr])[0]
            if apply_fields(cfg, values):
                proxy.set_attribute_config([cfg])
            return proxy.get_attribute_config_ex([attr])[0]

        def done(cfg):
            self._show(cfg)
            self.message.setText("")
            self.model.refresh()
            self.applied.emit(None)

        def failed(err):
            self._failed(err)
            self.applied.emit(err)
            self.show_failure(err)

        self.apply_button.setEnabled(False)
        return run_async(write, on_done=done, on_error=failed, source=self.model.name, owner=self)

    def information_text(self):
        cfg = self._cfg
        if cfg is None:
            return self.model.name
        return "\n".join(["Name: " + self.model.name, "Description: " + cfg.description,
                          "Type: {0} {1}".format(cfg.data_format, cfg.data_type),
                          "Writable: {0}".format(cfg.writable),
                          "Display level: {0}".format(cfg.disp_level),
                          "Standard unit: " + cfg.standard_unit, "Display unit: " + cfg.display_unit])

    def show_information(self):
        QtWidgets.QMessageBox.information(self, "Information", self.information_text())

    def show_failure(self, err):
        show_error(self, err, "Apply change")
