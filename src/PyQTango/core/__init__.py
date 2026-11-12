# -*- coding: utf-8 -*-
"""
PyQTango.core: Tango helpers with no Qt dependency.

These modules can be used and unit-tested without a display:

* :mod:`names`      - Tango name parsing, wildcard filters
* :mod:`errors`     - DevFailed to readable error records
* :mod:`proxies`    - thread-safe DeviceProxy cache
* :mod:`formatting` - Tango format strings, state and quality colours
* :mod:`argparser`  - text to typed Tango values (port of Jive's ArgParser)
* :mod:`db`         - DatabaseService: typed database access with SQL fallbacks
* :mod:`tangoutil`  - legacy database helpers (getAllRegisteredDevices, getAllLiveAttributes, ...)
"""

from .names import (split_attribute_name, normalize_name, device_of, is_device_name,
                    is_full_server_name, wildcard_to_regex, wildcard_to_sql_like)
from .errors import ErrorItem, ErrorRecord, error_from_exception
from .proxies import ProxyCache, proxy_cache
from .formatting import (format_value, format_scalar, format_digits, state_name, quality_name,
                         is_int_type, is_float_type, is_numeric_type,
                         STATE_COLORS, QUALITY_COLORS, state_colors, quality_color)
from .db import (DatabaseService, ServerInfo, DeviceInfo, ReadOnlyError, parse_tango_host,
                 split_tango_hosts)
from .argparser import (ArgParser, ArgParserError, parse_command_argin, parse_attribute_value,
                        argin_example)

__all__ = [
    "DatabaseService", "ServerInfo", "DeviceInfo", "ReadOnlyError", "parse_tango_host",
    "split_tango_hosts",
    "split_attribute_name", "normalize_name", "device_of", "is_device_name",
    "is_full_server_name", "wildcard_to_regex", "wildcard_to_sql_like",
    "ErrorItem", "ErrorRecord", "error_from_exception",
    "ProxyCache", "proxy_cache",
    "format_value", "format_scalar", "format_digits", "is_int_type", "is_float_type",
    "is_numeric_type", "state_name", "quality_name",
    "STATE_COLORS", "QUALITY_COLORS", "state_colors", "quality_color",
    "ArgParser", "ArgParserError", "parse_command_argin", "parse_attribute_value", "argin_example",
]
