# -*- coding: utf-8 -*-
"""
PyQTango.models: event-aware, shared Tango models for Qt widgets.

Typical use::

    from PyQTango.models import attribute_model
    m = attribute_model("sys/tg_test/1/double_scalar")
    m.valueChanged.connect(lambda v: print(v.value))
    m.attach()          # subscribe (events first, polling fallback)
    ...
    m.release()         # unsubscribe after a grace period when unused
"""

from .worker import run_async, Job, Task, thread_pool
from .history import ErrorHistoryModel, error_history
from .refresher import AttributeRefresher, refresher, DEFAULT_PERIOD_MS
from .attribute import TangoAttributeModel, AttrValue, MODE_IDLE, MODE_EVENTS, MODE_POLLING
from .device import TangoDeviceModel
from .registry import ModelRegistry, registry, attribute_model, device_model

__all__ = [
    "run_async", "Job", "Task", "thread_pool",
    "ErrorHistoryModel", "error_history",
    "AttributeRefresher", "refresher", "DEFAULT_PERIOD_MS",
    "TangoAttributeModel", "AttrValue", "MODE_IDLE", "MODE_EVENTS", "MODE_POLLING",
    "TangoDeviceModel",
    "ModelRegistry", "registry", "attribute_model", "device_model",
]
