# -*- coding: utf-8 -*-
""" Device server registered in the test database (polling panel tests) """

import sys

from tango import AttrWriteType, DevState
from tango.server import Device, attribute, command, run


class PQTPoll(Device):

    def init_device(self):
        super().init_device()
        self._value = 1.5
        self.set_state(DevState.ON)

    @attribute(dtype=float, unit="mA", access=AttrWriteType.READ_WRITE)
    def current(self):
        return self._value

    @current.write
    def current(self, v):
        self._value = v

    @attribute(dtype=float)
    def voltage(self):
        return 3.0

    @attribute(dtype=(float,), max_dim_x=16)
    def wave(self):
        return [1.0, 2.0, 3.0, 4.0]

    @attribute(dtype=float)
    def xstart(self):
        return 10.0

    @attribute(dtype=float)
    def xend(self):
        return 20.0

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
    def gain(self):
        return getattr(self, "_gain", 1.0)

    @gain.write
    def gain(self, v):
        self._gain = v

    @attribute(dtype=str, access=AttrWriteType.READ_WRITE)
    def mode_name(self):
        return getattr(self, "_mode", "slow")

    @mode_name.write
    def mode_name(self, v):
        self._mode = v

    @command(dtype_in=str, dtype_out=str)
    def Echo(self, s):
        return s

    @command
    def Reset(self):
        pass


if __name__ == "__main__":
    run((PQTPoll,), args=["PQTPoll"] + sys.argv[1:])
