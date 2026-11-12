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

Two switches stop a widget from following its model without unbinding it:

* :meth:`TangoAttributeWidget.setFrozen` (window "Stop refreshing"): values are
  kept but not shown until the widget is unfrozen; :meth:`refreshOnce` lets the
  next value through. A frozen widget suspends its model, so a model whose users
  are all frozen is no longer polled.
* ``pauseWhenHidden`` (hidden tabs): the widget releases its model while hidden
  (unsubscribing after the grace period) and attaches again when shown.
  A widget created hidden does not attach until it is first shown.

:func:`freeze_widgets` applies the first switch to every Tango widget under a
window.
"""

import logging

from ..qt import Property, is_deleted
from ..models.registry import attribute_model, device_model, registry
from ..models.attribute import TangoAttributeModel
from ..models.device import TangoDeviceModel

log = logging.getLogger(__name__)


def _release_on_destroy(model, frozen):
    # Must not capture the widget (it is being destroyed); ``frozen`` is its [bool] freeze flag
    def release(*_):
        try:
            if frozen[0]:
                model.resume()
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
        self._tfrozen = False
        self._tfrozen_flag = [False]    # shared with the destroy handler
        self._tonce = False
        self._tpending = None
        self._tpause_hidden = False
        self._tattached = False
        self._twrites = 0               # writes started by this widget, not finished yet
        self._tnext = None              # (value,) to write once the write in flight is over

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
            if self._tattached:
                if self._tfrozen:
                    old.resume()
                old.release()
        self._tattached = False
        self._tmodel = model
        self._tconfig = None
        self._tvalue = None
        self._terror = None
        self._tpending = None
        if model is None:
            self.on_model_cleared()
            return
        for sig, slot in self._tango_connections(model):
            sig.connect(slot)
        if self._tpause_hidden and not self._tango_visible():
            return          # attached on the first show
        self._tango_attach()

    def _tango_visible(self):
        try:
            return self.isVisible()
        except RuntimeError:
            return False

    def _tango_attach(self):
        model = self._tmodel
        if model is None or self._tattached:
            return
        current = registry().lookup(model.name)
        if current is not None and current is not model and model.on_released is not None:
            # The registry forgot this model while the widget was detached and a new
            # one now serves the attribute: follow it instead of reviving a duplicate
            for sig, slot in self._tango_connections(model):
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            model = self._tmodel = current
            for sig, slot in self._tango_connections(model):
                sig.connect(slot)
        self._tattached = True
        self._tdestroy = _release_on_destroy(model, self._tfrozen_flag)
        self.destroyed.connect(self._tdestroy)
        model.attach()
        if self._tfrozen:
            model.suspend()
        self._tango_replay()

    def _tango_detach(self):
        model = self._tmodel
        if model is None or not self._tattached:
            return
        self._tattached = False
        if self._tdestroy is not None:
            try:
                self.destroyed.disconnect(self._tdestroy)
            except (TypeError, RuntimeError):
                pass
            self._tdestroy = None
        try:
            if self._tfrozen:
                model.resume()
            model.release()
        except RuntimeError:
            pass        # the model went away first (application shutdown)

    def _tango_replay(self):
        model = self._tmodel
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

    def isAttached(self):
        """ True while the widget holds a reference on its model """
        return self._tattached

    # -- Freeze (Stop refreshing) ----------------------------------------------
    def setFrozen(self, on):
        """ Stop (True) or restart (False) showing new values """
        on = bool(on)
        if on == self._tfrozen:
            return
        self._tfrozen = on
        self._tfrozen_flag[0] = on
        m = self._tmodel
        if m is not None and self._tattached:
            if on:
                m.suspend()
            else:
                m.resume()
        if not on and self._tpending is not None:
            pending, self._tpending = self._tpending, None
            self._on_tango_value(pending)

    def isFrozen(self):
        return self._tfrozen

    def refreshOnce(self):
        """ Read the attribute now and show the result, even when frozen """
        if self._tmodel is None:
            return None
        self._tonce = True
        return self._tmodel.refresh()

    # -- Pause while hidden ----------------------------------------------------
    def getPauseWhenHidden(self):
        return self._tpause_hidden

    def setPauseWhenHidden(self, on):
        self._tpause_hidden = bool(on)
        if self._tmodel is None:
            return
        if on and not self._tango_visible():
            self._tango_detach()
        elif not on:
            self._tango_attach()

    pauseWhenHidden = Property(bool, getPauseWhenHidden, setPauseWhenHidden)

    def showEvent(self, event):
        super(TangoAttributeWidget, self).showEvent(event)
        if self._tpause_hidden:
            self._tango_attach()

    def hideEvent(self, event):
        super(TangoAttributeWidget, self).hideEvent(event)
        if self._tpause_hidden:
            self._tango_detach()

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
        if self._tfrozen and not self._tonce:
            self._tpending = value
            return
        self._tonce = False
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
        """ Write through the model. The result reaches :meth:`on_write_done` (as for
        every write on the model) while :meth:`writing` is True, then
        :meth:`on_own_write_done`. """
        if self._tmodel is None:
            return None
        task = self._tmodel.write(value)
        self._twrites += 1
        # Connected after the model's own callbacks: writeDone is emitted first
        task.done.connect(lambda _: self._tango_own_write(None))
        task.failed.connect(lambda err: self._tango_own_write(err))
        return task

    def write_latest(self, value):
        """ Write ``value`` now, or once the write in flight is over: with fast
        clicks or keystrokes only the latest value is kept, so writes never run in
        parallel and reach the device in order. Dropped if the previous write fails. """
        if self.writing():
            self._tnext = (value,)
            return None
        return self.write(value)

    def writing(self):
        """ True while a write started by this widget has not finished """
        return self._twrites > 0

    def write_pending(self):
        """ True while a write is in flight or queued by :meth:`write_latest` """
        return self._twrites > 0 or self._tnext is not None

    def _tango_own_write(self, err):
        if is_deleted(self):
            return
        self._twrites = max(0, self._twrites - 1)
        if self._twrites == 0 and self._tnext is not None:
            (value,), self._tnext = self._tnext, None
            if err is None and self._tmodel is not None:
                self.write(value)
        self.on_own_write_done(err)

    def on_own_write_done(self, err):
        """ Result of a write started by this widget (None = success) """

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


def tango_widgets(root):
    """ Every TangoAttributeWidget under ``root`` (included) """
    from ..qt import QtWidgets
    out = [root] if isinstance(root, TangoAttributeWidget) else []
    out += [w for w in root.findChildren(QtWidgets.QWidget) if isinstance(w, TangoAttributeWidget)]
    return out


def freeze_widgets(root, on):
    """ Freeze or unfreeze every Tango widget under ``root``; returns the widgets """
    widgets = tango_widgets(root)
    for w in widgets:
        w.setFrozen(on)
    return widgets


def model_name_property():
    """ ``modelName`` Qt property (settable from Qt Designer) for attribute widgets """
    return Property(str, TangoAttributeWidget.getModelName, TangoAttributeWidget.setModelName,
                    TangoAttributeWidget.resetModel)


def device_name_property():
    """ ``deviceName`` Qt property for device widgets """
    return Property(str, TangoDeviceWidget.getDeviceName, TangoDeviceWidget.setDeviceName)


__all__ = ["TangoAttributeWidget", "TangoDeviceWidget", "model_name_property", "device_name_property",
           "tango_widgets", "freeze_widgets",
           "TangoAttributeModel", "TangoDeviceModel"]
