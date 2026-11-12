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

    def get(self, name, timeout_ms=None, source=None):
        """ Return the cached proxy for ``name``, creating it if needed.

        ``source`` (a tango.DevSource) gives a separate proxy reading from that
        source (DEV, CACHE or CACHE_DEV), so one reader can use the polling
        cache without changing the shared proxy. Likewise a ``timeout_ms``
        other than the cache default gives a separate proxy with that timeout
        (Starters are read with 1 s so one dead host cannot hold a worker).
        """
        key = normalize_name(name)
        src = None if source is None or source == tango.DevSource.CACHE_DEV else int(source)
        tmo = None if timeout_ms is None or timeout_ms == self.timeout_ms else int(timeout_ms)
        if src is not None or tmo is not None:
            key = (key, src, tmo)
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
            return self.get(name, timeout_ms, source)
        try:
            proxy = tango.DeviceProxy(name)
            proxy.set_timeout_millis(timeout_ms or self.timeout_ms)
            if isinstance(key, tuple) and key[1] is not None:
                proxy.set_source(source)
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
        """ Forget the proxies of ``name`` (the next get() creates new ones). The old
        proxies are parked with :func:`keep_alive`, never destroyed (PyTango #302),
        and subscriptions made on them can still be unsubscribed. """
        key = normalize_name(name)
        with self._lock:
            for k in [k for k in self._proxies if k == key or (isinstance(k, tuple) and k[0] == key)]:
                keep_alive(self._proxies.pop(k))

    def proxies_of(self, name):
        """ Every cached proxy of a device (all sources), never blocks """
        key = normalize_name(name)
        with self._lock:
            return [p for k, p in self._proxies.items() if k == key or (isinstance(k, tuple) and k[0] == key)]

    def clear(self):
        """ Forget every proxy (parked with :func:`keep_alive`, see :meth:`invalidate`) """
        with self._lock:
            for p in self._proxies.values():
                keep_alive(p)
            self._proxies.clear()


#: Process-wide default cache
proxy_cache = ProxyCache()


# -- Proxies that must not be destroyed --------------------------------------------------------------
_kept = []
_kept_lock = threading.Lock()


def keep_alive(proxy):
    """ Keep ``proxy`` until the process ends, and return it.

    Destroying a DeviceProxy takes a lock of the Tango event consumer while the
    destroying thread holds the GIL; a failing stateless subscription's
    keep-alive thread holds that lock while it waits for the GIL to deliver its
    error event, so the two can deadlock (PyTango issue #302). Proxies from
    :data:`proxy_cache` are never destroyed; a window that needs a proxy of its
    own (its own timeout or source) parks it here instead of letting it go.
    """
    with _kept_lock:
        _kept.append(proxy)
    return proxy

