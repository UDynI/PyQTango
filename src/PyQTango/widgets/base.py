# -*- coding: utf-8 -*-
"""
TangoWidget: mixin that binds a QWidget to a shared Tango model.

A widget class combines the mixin with a Qt widget and implements the hooks::

    class MyLabel(TangoAttributeWidget, QtWidgets.QLabel):
        modelName = model_name_property()

        def __init__(self, parent=None):
            QtWidgets.QLabel.__init__(self, parent)
            TangoAttributeWidget.__init__(self)

        def on_value(self, value):      # AttrValue
            self.setText(str(value.value))

The mixin connects the model signals, keeps the reference count (attach on
``setModel``, release when the widget is destroyed or re-bound), and replays the
last configuration and value so a widget bound to an already running model
shows data at once.
"""

import logging

from ..qt import Property
from ..models.registry import attribute_model, device_model
from ..models.attribute import TangoAttributeModel
from ..models.device import TangoDeviceModel

log = logging.getLogger(__name__)


def _release_on_destroy(model):
    # Must not capture the widget (it is being destroyed)
    def release(*_):
        try:
            model.release()
        except RuntimeError:
            pass
    return release


class TangoAttributeWidget(object):
    """ Mixin for widgets showing or setting one attribute """

    def __init__(self):
        self._tmodel = None
        self._tdestroy = None
        self._tconfig = None
        self._tvalue = None
        self._terror = None

    # -- Binding ---------------------------------------------------------------
    def setModel(self, model):
        """ Bind to an attribute name, a TangoAttributeModel, or None/"" to unbind """
        if isinstance(model, str):
            model = attribute_model(model) if model.strip() else None
        if model is self._tmodel:
            return
        old = self._tmodel
        if old is not None:
            for sig, slot in self._tango_connections(old):
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            if self._tdestroy is not None:
                try:
                    self.destroyed.disconnect(self._tdestroy)
                except (TypeError, RuntimeError):
                    pass
                self._tdestroy = None
            old.release()
        self._tmodel = model
        self._tconfig = None
        self._tvalue = None
        self._terror = None
        if model is None:
            self.on_model_cleared()
            return
        for sig, slot in self._tango_connections(model):
            sig.connect(slot)
        self._tdestroy = _release_on_destroy(model)
        self.destroyed.connect(self._tdestroy)
        model.attach()
        # Replay what the model already knows
        if model.config() is not None:
            self._on_tango_config(model.config())
        if model.last_value() is not None:
            self._on_tango_value(model.last_value())
        if model.last_error() is not None:
            self._on_tango_error(model.last_error())

    def model(self):
        return self._tmodel

    def getModelName(self):
        return self._tmodel.name if self._tmodel is not None else ""

    def setModelName(self, name):
        self.setModel(name)

    def resetModel(self):
        self.setModel(None)

    def attributeConfig(self):
        return self._tconfig

    def attributeValue(self):
        return self._tvalue

    def attributeError(self):
        return self._terror

    def _tango_connections(self, model):
        return [(model.configChanged, self._on_tango_config),
                (model.valueChanged, self._on_tango_value),
                (model.errorChanged, self._on_tango_error),
                (model.writeDone, self._on_tango_write_done)]

    # -- Internal dispatch -------------------------------------------------------
    def _on_tango_config(self, cfg):
        self._tconfig = cfg
        self.on_config(cfg)

    def _on_tango_value(self, value):
        self._tvalue = value
        self.on_value(value)

    def _on_tango_error(self, err):
        self._terror = err
        self.on_error(err)

    def _on_tango_write_done(self, err):
        self.on_write_done(err)

    # -- Hooks for subclasses ----------------------------------------------------
    def on_config(self, cfg):
        """ tango.AttributeInfoEx received (first read or ATTR_CONF_EVENT) """

    def on_value(self, value):
        """ New :class:`PyQTango.models.AttrValue` """

    def on_error(self, err):
        """ ErrorRecord, or None when the error cleared """

    def on_write_done(self, err):
        """ Result of a write started by any widget on this model (None = success) """

    def on_model_cleared(self):
        """ The widget was unbound """

    # -- Helpers -----------------------------------------------------------------
    def set_point(self, value, mode="auto"):
        """ Value a setter should show for an AttrValue.

        ``mode``: "auto" (set point when :meth:`TangoAttributeModel.has_valid_set_point`,
        else read value), "always" (set point, ATK behaviour) or "never" (read value).
        """
        w = value.w_value
        if w is None or (isinstance(w, str) and w == "Not initialised") or mode == "never":
            return value.value
        if mode == "always" or (self._tmodel is not None and self._tmodel.has_valid_set_point()):
            return w
        return value.value

    def write(self, value):
        if self._tmodel is not None:
            return self._tmodel.write(value)
        return None

    def tooltip_text(self):
        """ Tooltip with name, label, description, unit and limits """
        m, cfg = self._tmodel, self._tconfig
        if m is None:
            return ""
        lines = ["<b>{0}</b>".format(m.name)]
        if cfg is not None:
            def ok(v):
                return v not in (None, "", "Not specified", "No description", "No unit")
            if ok(cfg.label):
                lines.append("Label: " + cfg.label)
            if ok(cfg.description):
                lines.append(cfg.description)
            if ok(cfg.unit):
                lines.append("Unit: " + cfg.unit)
            if ok(cfg.min_value) or ok(cfg.max_value):
                lines.append("Range: [{0}, {1}]".format(cfg.min_value, cfg.max_value))
            alarms = getattr(cfg, "alarms", None)
            if alarms is not None and (ok(alarms.min_alarm) or ok(alarms.max_alarm)):
                lines.append("Alarms: [{0}, {1}]".format(alarms.min_alarm, alarms.max_alarm))
        if self._tvalue is not None:
            lines.append("Quality: {0}".format(self._tvalue.quality))
        if self._terror is not None:
            lines.append("<font color='red'>{0}</font>".format(self._terror.message))
        return "<br/>".join(lines)


class TangoDeviceWidget(object):
    """ Mixin for widgets bound to a whole device """

    def __init__(self):
        self._dmodel = None

    def setDevice(self, device):
        """ Bind to a device name or TangoDeviceModel (None/"" unbinds) """
        if isinstance(device, str):
            device = device_model(device) if device.strip() else None
        if device is self._dmodel:
            return
        self._dmodel = device
        self.on_device_changed(device)

    def device(self):
        return self._dmodel

    def getDeviceName(self):
        return self._dmodel.name if self._dmodel is not None else ""

    def setDeviceName(self, name):
        self.setDevice(name)

    def on_device_changed(self, device):
        """ Override: bind child widgets to ``device`` (may be None) """


def model_name_property():
    """ ``modelName`` Qt property (settable from Qt Designer) for attribute widgets """
    return Property(str, TangoAttributeWidget.getModelName, TangoAttributeWidget.setModelName,
                    TangoAttributeWidget.resetModel)


def device_name_property():
    """ ``deviceName`` Qt property for device widgets """
    return Property(str, TangoDeviceWidget.getDeviceName, TangoDeviceWidget.setDeviceName)


__all__ = ["TangoAttributeWidget", "TangoDeviceWidget", "model_name_property", "device_name_property",
           "TangoAttributeModel", "TangoDeviceModel"]
