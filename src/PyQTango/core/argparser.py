# -*- coding: utf-8 -*-
"""
Text to typed Tango values. Python port of Jive's ``jive.ArgParser`` (Jive 8.2),
extended to every Tango type.

Syntax (same as Jive's Test Device panel):

* integers: ``10`` or ``0xa``; chars also ``'A'``
* booleans: ``true``, ``false``, ``1``, ``0``
* states: ``ON``, ``FAULT``, ... or their integer code
* enums: a label or an index
* strings: ``"quoted text"`` (``\\"`` escapes a quote); an unquoted word also works
* arrays: ``1,2,3`` or ``[1,2,3]``; ``zeros(n)`` gives n zeros
* images: ``[1,2,3][4,5,6]`` (rows of equal length)
* DevVarLongStringArray / DevVarDoubleStringArray: ``[1,2][a,"b c"]``
* DevEncoded: ``"format",[1,2,3]`` or ``"format","text"``
* ``file:/path`` reads the text from a file
"""

import numpy as np
import tango

T = tango.CmdArgType


class ArgParserError(ValueError):
    """ Raised on any syntax or range error """


_SPECIAL = ",[]()"

_INT_RANGES = {
    "char": (np.int8, -128, 127),
    "uchar": (np.uint8, 0, 255),
    "short": (np.int16, -2 ** 15, 2 ** 15 - 1),
    "ushort": (np.uint16, 0, 2 ** 16 - 1),
    "long": (np.int32, -2 ** 31, 2 ** 31 - 1),
    "ulong": (np.uint32, 0, 2 ** 32 - 1),
    "long64": (np.int64, -2 ** 63, 2 ** 63 - 1),
    "ulong64": (np.uint64, 0, 2 ** 64 - 1),
}

_SCALAR_KIND = {
    T.DevBoolean: "bool", T.DevUChar: "uchar", T.DevShort: "short", T.DevUShort: "ushort",
    T.DevLong: "long", T.DevULong: "ulong", T.DevLong64: "long64", T.DevULong64: "ulong64",
    T.DevFloat: "float", T.DevDouble: "double", T.DevString: "string", T.DevState: "state",
    T.DevEnum: "enum",
}

_ARRAY_KIND = {
    T.DevVarBooleanArray: "bool", T.DevVarCharArray: "uchar", T.DevVarShortArray: "short",
    T.DevVarUShortArray: "ushort", T.DevVarLongArray: "long", T.DevVarULongArray: "ulong",
    T.DevVarLong64Array: "long64", T.DevVarULong64Array: "ulong64", T.DevVarFloatArray: "float",
    T.DevVarDoubleArray: "double", T.DevVarStringArray: "string", T.DevVarStateArray: "state",
}

_EXAMPLES = {
    "bool": "true,false or 0,1", "char": "2,0xa,'A' (signed 8bits)", "uchar": "10 or 0xa (unsigned 8bits)",
    "short": "10 or 0xa (signed 16bits)", "ushort": "10 or 0xa (unsigned 16bits)",
    "long": "10 or 0xa (signed 32bits)", "ulong": "10 or 0xa (unsigned 32bits)",
    "long64": "10 or 0xa (signed 64bits)", "ulong64": "10 or 0xa (unsigned 64bits)",
    "float": "2.3 (32bits float)", "double": "2.3 (64bits float)", "state": "ON,OFF,...",
    "string": "quotes needed for string with space or special char",
}


class _Token(object):
    __slots__ = ("text", "quoted")

    def __init__(self, text, quoted=False):
        self.text = text
        self.quoted = quoted

    def __repr__(self):
        return "Token({0!r}{1})".format(self.text, ", quoted" if self.quoted else "")


def _unescape(s):
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


class ArgParser(object):
    """ Recursive-descent parser over Jive's argument syntax """

    def __init__(self, text):
        if text is None or text == "":
            raise ArgParserError("Empty argument, you must specify a value")
        if text.startswith("file:/"):
            try:
                # "file:/home/op/x.txt" reads /home/op/x.txt
                with open(text[len("file:"):], "r") as f:
                    text = f.read()
            except OSError as e:
                raise ArgParserError(str(e))
        self.text = text
        self.pos = 0

    # -- Lexer ---------------------------------------------------------------
    def _skip_space(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _peek(self):
        self._skip_space()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _at_end(self):
        return self._peek() == ""

    def _read_word(self):
        self._skip_space()
        t = self.text
        if self.pos >= len(t):
            return None
        c = t[self.pos]
        if c in _SPECIAL:
            self.pos += 1
            return _Token(c)
        if c == "'" and self.pos + 2 < len(t) and t[self.pos + 2] == "'":
            tok = _Token(t[self.pos:self.pos + 3])
            self.pos += 3
            return tok
        if c == '"':
            self.pos += 1
            start = self.pos
            while self.pos < len(t):
                if t[self.pos] == "\\" and self.pos + 1 < len(t):
                    self.pos += 2
                    continue
                if t[self.pos] == '"':
                    break
                if t[self.pos] == "\n":
                    raise ArgParserError("Unterminated string.")
                self.pos += 1
            if self.pos >= len(t):
                raise ArgParserError("Unterminated string.")
            raw = t[start:self.pos]
            self.pos += 1
            return _Token(_unescape(raw), quoted=True)
        start = self.pos
        while self.pos < len(t) and t[self.pos] > " " and t[self.pos] not in _SPECIAL:
            self.pos += 1
        return _Token(t[start:self.pos])

    def _expect(self, sep):
        self._skip_space()
        if self.pos < len(self.text) and self.text[self.pos] == sep:
            self.pos += 1
            return
        got = self.text[self.pos] if self.pos < len(self.text) else "end of input"
        raise ArgParserError("'{0}' expected, got '{1}' at position {2}".format(sep, got, self.pos))

    def _ensure_end(self):
        if not self._at_end():
            raise ArgParserError("Unexpected text '{0}'".format(self.text[self.pos:].strip()))

    # -- Grammar -------------------------------------------------------------
    def _parse_array_words(self):
        items = []
        if self.text[self.pos:].lstrip()[:6].lower() == "zeros(":
            self._read_word()
            self._expect("(")
            n = self._int(self._read_word(), "ushort")
            self._expect(")")
            return [_Token("0")] * int(n)
        closed = False
        if self._peek() == "[":
            closed = True
            self._expect("[")
        while not (self._at_end() or self._peek() == "]"):
            tok = self._read_word()
            if tok is None or (not tok.quoted and tok.text in _SPECIAL):
                raise ArgParserError("Value expected at position {0}".format(self.pos))
            items.append(tok)
            if not (self._at_end() or self._peek() == "]"):
                self._expect(",")
        if closed:
            self._expect("]")
        return items

    def _parse_image_words(self):
        rows = [self._parse_array_words()]
        width = len(rows[0])
        while self._peek() == "[":
            row = self._parse_array_words()
            if len(row) != width:
                raise ArgParserError("All lines in an image must have the same size.")
            rows.append(row)
        return rows

    # -- Conversions ---------------------------------------------------------
    @staticmethod
    def _int(tok, kind):
        if tok is None:
            raise ArgParserError("{0} value expected".format(kind))
        w = tok.text.strip()
        if kind in ("char", "uchar") and len(w) == 3 and w[0] == "'" and w[2] == "'":
            return _INT_RANGES[kind][0](ord(w[1]))
        try:
            if w.lower().startswith(("0x", "-0x", "+0x")):
                v = int(w, 16)
            else:
                v = int(w, 10)
        except ValueError:
            raise ArgParserError("Invalid {0} value '{1}'".format(kind, w))
        dtype, lo, hi = _INT_RANGES[kind]
        if v < lo or v > hi:
            raise ArgParserError("{0} value {1} out of range [{2},{3}].".format(kind, v, lo, hi))
        return dtype(v)

    @staticmethod
    def _float(tok, kind):
        if tok is None:
            raise ArgParserError("{0} value expected".format(kind))
        try:
            v = float(tok.text)
        except ValueError:
            raise ArgParserError("Invalid {0} value '{1}'".format(kind, tok.text))
        if kind == "float":
            if np.isfinite(v) and abs(v) > np.finfo(np.float32).max:
                raise ArgParserError("float value {0} out of range".format(v))
            return np.float32(v)
        return np.float64(v)

    @staticmethod
    def _bool(tok):
        w = tok.text.strip().lower() if tok is not None else ""
        if w in ("true", "1"):
            return True
        if w in ("false", "0"):
            return False
        raise ArgParserError("invalid boolean value {0} [true,false or 0,1].".format(w))

    @staticmethod
    def _state(tok):
        w = tok.text.strip() if tok is not None else ""
        try:
            return tango.DevState.names[w.upper()]
        except KeyError:
            pass
        try:
            return tango.DevState(int(w))
        except (ValueError, TypeError):
            raise ArgParserError("Invalid state value '{0}'".format(w))

    @staticmethod
    def _enum(tok, labels):
        w = tok.text.strip() if tok is not None else ""
        if labels:
            for i, label in enumerate(labels):
                if label == w:
                    return np.int16(i)
            for i, label in enumerate(labels):
                if label.lower() == w.lower():
                    return np.int16(i)
        try:
            v = int(w)
        except ValueError:
            raise ArgParserError("Invalid enum value '{0}' (labels: {1})".format(w, ", ".join(labels or [])))
        if labels and not 0 <= v < len(labels):
            raise ArgParserError("Enum index {0} out of range [0,{1}]".format(v, len(labels) - 1))
        return np.int16(v)

    def _convert(self, tok, kind, labels=None):
        if kind in _INT_RANGES:
            return self._int(tok, kind)
        if kind in ("float", "double"):
            return self._float(tok, kind)
        if kind == "bool":
            return self._bool(tok)
        if kind == "state":
            return self._state(tok)
        if kind == "enum":
            return self._enum(tok, labels)
        if kind == "string":
            return tok.text if tok is not None else ""
        raise ArgParserError("Unsupported type " + kind)

    def _convert_list(self, toks, kind, labels=None):
        values = [self._convert(t, kind, labels) for t in toks]
        if kind in _INT_RANGES:
            return np.array(values, dtype=_INT_RANGES[kind][0])
        if kind == "float":
            return np.array(values, dtype=np.float32)
        if kind == "double":
            return np.array(values, dtype=np.float64)
        if kind == "bool":
            return np.array(values, dtype=bool)
        if kind == "enum":
            return np.array(values, dtype=np.int16)
        return values

    # -- Public parsing ------------------------------------------------------
    def scalar(self, kind, labels=None):
        if kind == "string":
            stripped = self.text.strip()
            if stripped.startswith('"'):
                tok = self._read_word()
                self._ensure_end()
                return tok.text
            return stripped
        tok = self._read_word()
        self._ensure_end()
        return self._convert(tok, kind, labels)

    def array(self, kind, labels=None):
        toks = self._parse_array_words()
        self._ensure_end()
        return self._convert_list(toks, kind, labels)

    def image(self, kind, labels=None):
        rows = self._parse_image_words()
        self._ensure_end()
        conv = [self._convert_list(r, kind, labels) for r in rows]
        if kind == "string" or kind == "state":
            return [list(r) for r in conv]
        return np.array(conv)

    def number_string_array(self, kind):
        """ ``[1,2][a,b]`` -> ([numbers], [strings]) """
        nums = self._parse_array_words()
        strs = self._parse_array_words()
        self._ensure_end()
        return [list(self._convert_list(nums, kind)), [t.text for t in strs]]

    def encoded(self):
        """ ``"format",[1,2,3]`` or ``"format","text"`` -> (format, bytes) """
        fmt = self._read_word()
        if fmt is None:
            raise ArgParserError("DevEncoded format expected")
        self._expect(",")
        if self._peek() == "[" or self.text[self.pos:].lstrip()[:6].lower() == "zeros(":
            data = bytes(bytearray(int(v) for v in self._convert_list(self._parse_array_words(), "uchar")))
        else:
            tok = self._read_word()
            data = (tok.text if tok else "").encode()
        self._ensure_end()
        return (fmt.text, data)

    # -- Hex / decimal conversion (property panel) --------------------------
    def convert_to_hex(self):
        toks = self._parse_array_words()
        return ",".join(hex(int(self._int(t, "long64"))) for t in toks)

    def convert_to_dec(self):
        toks = self._parse_array_words()
        return ",".join(str(int(self._int(t, "long64"))) for t in toks)


def parse_command_argin(text, in_type):
    """ Parse a command argument for ``DeviceProxy.command_inout`` """
    if in_type == T.DevVoid:
        return None
    p = ArgParser(text)
    if in_type in _SCALAR_KIND:
        return p.scalar(_SCALAR_KIND[in_type])
    if in_type in _ARRAY_KIND:
        return p.array(_ARRAY_KIND[in_type])
    if in_type == T.DevVarLongStringArray:
        return p.number_string_array("long")
    if in_type == T.DevVarDoubleStringArray:
        return p.number_string_array("double")
    if in_type == T.DevEncoded:
        return p.encoded()
    raise ArgParserError("Unsupported argument type {0}".format(in_type))


def parse_attribute_value(text, data_type, data_format=tango.AttrDataFormat.SCALAR, enum_labels=None):
    """ Parse a value for ``DeviceProxy.write_attribute`` """
    p = ArgParser(text)
    if data_type == T.DevEncoded:
        return p.encoded()
    kind = _SCALAR_KIND.get(data_type)
    if kind is None:
        raise ArgParserError("Unsupported attribute type {0}".format(data_type))
    if data_format == tango.AttrDataFormat.SPECTRUM:
        return p.array(kind, enum_labels)
    if data_format == tango.AttrDataFormat.IMAGE:
        return p.image(kind, enum_labels)
    return p.scalar(kind, enum_labels)


def argin_example(data_type, data_format=None, enum_labels=None):
    """ Example text shown next to the argument field, as in Jive """
    if data_type == T.DevVoid:
        return ""
    if data_type == T.DevEnum:
        return "Enum: " + ",".join(enum_labels or [])
    if data_type == T.DevVarLongStringArray:
        return 'Ex: [1,2][A,"B C",D] (quotes needed for string with space or special char)'
    if data_type == T.DevVarDoubleStringArray:
        return 'Ex: [1.0,2.0][A,"B C",D] (quotes needed for string with space or special char)'
    if data_type == T.DevEncoded:
        return 'Ex: "format",[1,2,3] or "format","text"'
    if data_type in _ARRAY_KIND:
        return "Ex: " + _EXAMPLES.get(_ARRAY_KIND[data_type], "")
    kind = _SCALAR_KIND.get(data_type)
    base = _EXAMPLES.get(kind, "")
    if data_format == tango.AttrDataFormat.SPECTRUM:
        return "Array of " + base + " Ex: a,b,c"
    if data_format == tango.AttrDataFormat.IMAGE:
        return "Image of " + base + " Ex: [a,b,c][d,e,f][g,h,i]"
    if kind == "string":
        return base
    return "Ex: " + base
