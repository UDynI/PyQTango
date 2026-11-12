# -*- coding: utf-8 -*-
"""
ModelRegistry: hands out one shared model per attribute or device name.
"""

from ..qt import QtCore
from ..core.names import normalize_name
from .attribute import TangoAttributeModel
from .device import TangoDeviceModel


class ModelRegistry(object):
    """ Registry of shared models (one per normalised name) """

    def __init__(self):
        self._attributes = {}
        self._devices = {}

    def attribute(self, name):
        key = normalize_name(name)
        model = self._attributes.get(key)
        if model is None:
            model = TangoAttributeModel(name)
            model.on_released = self._forget_attribute
            model.on_revive = self._revive_attribute
            self._attributes[key] = model
        return model

    def lookup(self, name):
        """ The shared model of ``name`` if there is one (never creates it) """
        return self._attributes.get(normalize_name(name))

    def device(self, name):
        key = normalize_name(name)
        model = self._devices.get(key)
        if model is None:
            model = TangoDeviceModel(name, self)
            self._devices[key] = model
        return model

    def attributes(self):
        return list(self._attributes.values())

    def _forget_attribute(self, model):
        key = normalize_name(model.name)
        if self._attributes.get(key) is model and model.ref_count() == 0:
            del self._attributes[key]
            # Called from the model's own release timer: keep it alive until the next event-loop turn
            QtCore.QTimer.singleShot(0, lambda m=model: None)

    def _revive_attribute(self, model):
        # A user attached a model the registry had forgotten (e.g. a widget paused while
        # hidden): share it again, unless another model took the name meanwhile
        key = normalize_name(model.name)
        if key not in self._attributes:
            self._attributes[key] = model

    def shutdown(self):
        """ Unsubscribe everything (call before the application exits) """
        for m in list(self._attributes.values()):
            m.shutdown()
        self._attributes.clear()
        self._devices.clear()


_registry = None


def registry():
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


def attribute_model(name):
    """ Shared :class:`TangoAttributeModel` for a full attribute name """
    return registry().attribute(name)


def device_model(name):
    """ Shared :class:`TangoDeviceModel` for a device name """
    return registry().device(name)
