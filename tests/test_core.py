# -*- coding: utf-8 -*-
""" Qt-free helpers """

import numpy as np
import pytest
import tango

from PyQTango.core import (ArgParser, ArgParserError, parse_command_argin, parse_attribute_value, argin_example,
                           split_attribute_name, wildcard_to_sql_like, wildcard_to_regex, is_device_name,
                           is_full_server_name, format_scalar, format_value, format_digits, error_from_exception)

T = tango.CmdArgType
F = tango.AttrDataFormat


@pytest.mark.parametrize("text, dtype, expected", [
    ("10", T.DevLong, 10), ("0xa", T.DevUShort, 10), ("true", T.DevBoolean, True), ("0", T.DevBoolean, False),
    ('"a b"', T.DevString, "a b"), ("a b", T.DevString, "a b"), ("2.5", T.DevDouble, 2.5),
    ("ON", T.DevState, tango.DevState.ON), ("18446744073709551615", T.DevULong64, 2 ** 64 - 1),
])
def test_scalars(text, dtype, expected):
    assert parse_command_argin(text, dtype) == expected


def test_arrays_and_keywords():
    assert list(parse_command_argin("1,2,3", T.DevVarLongArray)) == [1, 2, 3]
    assert parse_command_argin("[1,2,3]", T.DevVarLongArray).dtype == np.int32
    assert list(parse_command_argin("zeros(3)", T.DevVarShortArray)) == [0, 0, 0]
    assert list(parse_command_argin("'A',2", T.DevVarCharArray)) == [65, 2]
    assert parse_command_argin('Dance,"the TANGO"', T.DevVarStringArray) == ["Dance", "the TANGO"]
    nums, strs = parse_command_argin('[1,2][A,"B C"]', T.DevVarLongStringArray)
    assert list(nums) == [1, 2] and strs == ["A", "B C"]
    assert parse_command_argin('"gray8",[1,2]', T.DevEncoded) == ("gray8", b"\x01\x02")
    assert parse_command_argin('"json","{}"', T.DevEncoded) == ("json", b"{}")


def test_images_and_enums():
    img = parse_attribute_value("[1,2,3][4,5,6]", T.DevDouble, F.IMAGE)
    assert img.shape == (2, 3)
    assert parse_attribute_value("Blue", T.DevEnum, F.SCALAR, ["Red", "Blue"]) == 1
    assert parse_attribute_value("blue", T.DevEnum, F.SCALAR, ["Red", "Blue"]) == 1
    assert parse_attribute_value("0", T.DevEnum, F.SCALAR, ["Red", "Blue"]) == 0


@pytest.mark.parametrize("text, dtype", [
    ("300", T.DevUChar), ("[1,2][3]", T.DevVarLongArray), ("maybe", T.DevBoolean), ('"open', T.DevString),
    ("1.5", T.DevLong), ("", T.DevLong),
])
def test_errors(text, dtype):
    with pytest.raises(ArgParserError):
        parse_command_argin(text, dtype)


def test_image_rows_must_match():
    with pytest.raises(ArgParserError):
        parse_attribute_value("[1,2][3]", T.DevLong, F.IMAGE)


def test_pipe_and_conversions():
    name, items = ArgParser('Blob,[a,D,1.5,2],[in,[Inner,[s,STR,"x y"]]]').pipe()
    assert name == "Blob" and items[0]["name"] == "a" and list(items[0]["value"]) == [1.5, 2.0]
    assert items[1]["value"][1][0]["value"] == ["x y"]
    assert ArgParser("255,16").convert_to_hex() == "0xff,0x10"
    assert ArgParser("0xff").convert_to_dec() == "255"


def test_examples():
    assert argin_example(T.DevDouble, F.SPECTRUM) == "Array of 2.3 (64bits float) Ex: a,b,c"
    assert argin_example(T.DevVoid) == ""
    assert "Enum" in argin_example(T.DevEnum, enum_labels=["a"])


def test_names():
    assert split_attribute_name("a/b/c/d") == ("a/b/c", "d")
    assert split_attribute_name("tango://h:1/a/b/c/X#dbase=no") == ("tango://h:1/a/b/c#dbase=no", "X")
    with pytest.raises(ValueError):
        split_attribute_name("a/b/c")
    assert is_device_name("sys/tg_test/1") and not is_device_name("sys/tg_test")
    assert is_full_server_name("TangoTest/test") and not is_full_server_name("a/b/c")
    assert wildcard_to_sql_like("sr/d_*/o'k%") == "sr/d\\_%/o''k\\%"
    assert wildcard_to_regex("sr/*/m1").match("SR/abc/M1")
    assert not wildcard_to_regex("sr/*/m1").match("sr/abc/m12")


def test_formatting():
    assert format_scalar(3.14159, "%6.2f", T.DevDouble, unit="mm") == "  3.14 mm"
    assert format_scalar(5, "%x") == "5"
    assert format_scalar(2.5, "%d") == "2"
    assert format_scalar(1, "", T.DevEnum, ["a", "b"]) == "b"
    assert format_scalar(tango.DevState.ON) == "ON"
    assert format_scalar(1.0, "Not specified") == "1.0"
    assert format_value([1.0, 2.0], "%.1f") == "[1.0, 2.0]"
    assert format_value(list(range(30)), "%d", max_items=3) == "[0, 1, 2, ...]"
    assert format_digits("%8.3f") == (4, 3)
    assert format_digits("%5d") == (5, 0)


def test_error_records():
    rec = error_from_exception(ValueError("bad"), "src")
    assert rec.message == "bad" and rec.reason == "ValueError" and "bad" in rec.text()
    try:
        tango.Except.throw_exception("MyReason", "My description", "origin()")
    except tango.DevFailed as e:
        rec = error_from_exception(e, "dev")
    assert rec.reason == "MyReason" and rec.message == "My description" and "origin()" in rec.html()
