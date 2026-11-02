# -*- coding: utf-8 -*-
"""
Thread-safe DeviceProxy cache.

DeviceProxy creation can block (DNS, database lookup). Call :meth:`ProxyCache.get`
from a worker thread, never from the GUI thread.
"""

import threading
import logging

import tango

from .names import normalize_name

log = logging.getLogger(__name__)


class ProxyCache(object):
    """ Cache of tango.DeviceProxy objects keyed by normalised device name """

    def __init__(self, timeout_ms=3000):
        self._lock = threading.RLock()
        self._creating = {}
        self._proxies = {}
        self.timeout_ms = timeout_ms

    def get(self, name, timeout_ms=None):
        """ Return the cached proxy for ``name``, creating it if needed """
        key = normalize_name(name)
        with self._lock:
            proxy = self._proxies.get(key)
            if proxy is not None:
                return proxy
            event = self._creating.get(key)
            if event is None:
                event = threading.Event()
                self._creating[key] = event
                owner = True
            else:
                owner = False
        if not owner:
            # Another thread is creating the same proxy: wait for it
            event.wait()
            with self._lock:
                proxy = self._proxies.get(key)
            if proxy is not None:
                return proxy
            return self.get(name, timeout_ms)
        try:
            proxy = tango.DeviceProxy(name)
            proxy.set_timeout_millis(timeout_ms or self.timeout_ms)
            with self._lock:
                self._proxies[key] = proxy
            return proxy
        finally:
            with self._lock:
                self._creating.pop(key, None)
            event.set()

    def peek(self, name):
        """ Cached proxy or None, never blocks """
        with self._lock:
            return self._proxies.get(normalize_name(name))

    def invalidate(self, name):
        with self._lock:
            self._proxies.pop(normalize_name(name), None)

    def clear(self):
        with self._lock:
            self._proxies.clear()


#: Process-wide default cache
proxy_cache = ProxyCache()
