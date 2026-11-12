# -*- coding: utf-8 -*-
"""
Compact digit-wheel editors (ATK NumberScalarWheelEditor).

:class:`QWheelEditor` is a plain number editor: each digit has its own up/down
arrows (shown on hover), reacts to the mouse wheel and to the keyboard
(Left/Right select a digit, Up/Down change it, 0-9 type, Enter commits,
Esc reverts). :class:`QAttributeWheelEditor` binds it to a numeric attribute.
"""

import math

from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal, Property, event_pos
from ..core.formatting import format_digits, is_int_type
from .base import TangoAttributeWidget, model_name_property

_ARROW = 7


class QWheelEditor(QtWidgets.QWidget):
    """ Number editor with one wheel per digit.

    Signals:
        valueEdited(float):    the user changed the value
        valueCommitted(float): the value should be applied (every change when
                               ``writeOnChange`` is True, otherwise on Enter)
        editReverted():        Esc pressed
    """

    valueEdited = Signal(float)
    valueCommitted = Signal(float)
    editReverted = Signal()

    def __init__(self, parent=None, integer_digits=4, decimals=2):
        QtWidgets.QWidget.__init__(self, parent)
        self._int_digits = max(1, int(integer_digits))
        self._decimals = max(0, int(decimals))
        self._units = 0             # value in units of 10**-decimals
        self._ref_units = 0         # last value set from outside
        self._min = -math.inf
        self._max = math.inf
        self._write_on_change = False
        self._pending = False
        self._hover = -1
        self._sel = -1
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        font.setPointSizeF(max(font.pointSizeF(), 10.0))
        self.setFont(font)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

    # -- Properties ------------------------------------------------------------
    def integerDigits(self):
        return self._int_digits

    def setIntegerDigits(self, n):
        v = self.value()
        self._int_digits = max(1, int(n))
        self._set_units(self._to_units(v), external=True)
        self.updateGeometry()

    digits = Property(int, integerDigits, setIntegerDigits)

    def decimals(self):
        return self._decimals

    def setDecimals(self, n):
        v = self.value()
        self._decimals = max(0, int(n))
        self._set_units(self._to_units(v), external=True)
        self.updateGeometry()

    decimalPlaces = Property(int, decimals, setDecimals)

    def minimum(self):
        return self._min

    def maximum(self):
        return self._max

    def setRange(self, minimum, maximum):
        self._min = -math.inf if minimum is None else float(minimum)
        self._max = math.inf if maximum is None else float(maximum)
        self.update()

    def writeOnChange(self):
        return self._write_on_change

    def setWriteOnChange(self, on):
        self._write_on_change = bool(on)

    autoWrite = Property(bool, writeOnChange, setWriteOnChange)

    def isPending(self):
        return self._pending

    def value(self):
        return self._units / (10 ** self._decimals)

    def setValue(self, value):
        """ Set from outside (e.g. a new set point); ignored while the user edits """
        if self._pending:
            return
        self._set_units(self._to_units(value), external=True)

    # -- Geometry --------------------------------------------------------------
    def _n_cells(self):
        # sign + integer digits + (point + decimals)
        return 1 + self._int_digits + (1 + self._decimals if self._decimals else 0)

    def _char_w(self):
        return QtGui.QFontMetrics(self.font()).horizontalAdvance("0") + 2

    def sizeHint(self):
        fm = QtGui.QFontMetrics(self.font())
        return QtCore.QSize(self._n_cells() * self._char_w() + 6, fm.height() + 2 * _ARROW + 4)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _cell_rect(self, i):
        w = self._char_w()
        return QtCore.QRect(3 + i * w, _ARROW + 2, w, self.height() - 2 * _ARROW - 4)

    def _cell_at(self, x):
        w = self._char_w()
        i = int((x - 3) // w)
        return i if 0 <= i < self._n_cells() else -1

    def _cell_weight(self, i):
        """ Power-of-ten step (in units) of cell i, or None for sign/point """
        if i <= 0:
            return None
        if i <= self._int_digits:
            return 10 ** (self._int_digits - i + self._decimals)
        j = i - self._int_digits - 1
        if j == 0:
            return None
        return 10 ** (self._decimals - j)

    def _digit_cells(self):
        return [i for i in range(self._n_cells()) if self._cell_weight(i) is not None]

    def _text_cells(self):
        units = abs(self._units)
        digits = str(units).rjust(self._int_digits + self._decimals, "0")
        digits = digits[-(self._int_digits + self._decimals):]
        cells = ["-" if self._units < 0 else "+"]
        cells += list(digits[:self._int_digits])
        if self._decimals:
            cells.append(".")
            cells += list(digits[self._int_digits:])
        return cells

    # -- Value handling --------------------------------------------------------
    def _to_units(self, value):
        try:
            return int(round(float(value) * 10 ** self._decimals))
        except (TypeError, ValueError, OverflowError):
            return 0

    def _clamp(self, units):
        top = 10 ** (self._int_digits + self._decimals) - 1
        units = max(-top, min(top, units))
        scale = 10 ** self._decimals
        if units / scale < self._min:
            units = int(math.ceil(self._min * scale))
        if units / scale > self._max:
            units = int(math.floor(self._max * scale))
        return units

    def _set_units(self, units, external=False):
        self._units = units if external else self._clamp(units)
        if external:
            self._ref_units = self._units
            # Widen rather than hide leading digits: a click would then write a clamped value
            need = len(str(abs(units) // 10 ** self._decimals))
            if need > self._int_digits:
                self._int_digits = need
                self.updateGeometry()
        self.update()

    def _user_change(self, units):
        new = self._clamp(units)
        if new == self._units:
            return
        self._units = new
        self.valueEdited.emit(self.value())
        if self._write_on_change:
            self._pending = False
            self._ref_units = new
            self.valueCommitted.emit(self.value())
        else:
            self._pending = True
        self.update()

    def step(self, cell, direction):
        weight = self._cell_weight(cell)
        if weight is None:
            if cell == 0 and self._min < 0:
                self._user_change(-self._units)
            return
        self._user_change(self._units + direction * weight)

    def commit(self):
        self._pending = False
        self._ref_units = self._units
        self.valueCommitted.emit(self.value())
        self.update()

    def revert(self):
        self._pending = False
        self._units = self._ref_units
        self.editReverted.emit()
        self.update()

    # -- Events ------------------------------------------------------------------
    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        base = pal.color(QtGui.QPalette.ColorRole.Base) if self.isEnabled() else pal.color(QtGui.QPalette.ColorRole.Window)
        p.fillRect(self.rect(), base)
        p.setPen(pal.color(QtGui.QPalette.ColorRole.Mid))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        text_color = QtGui.QColor("darkgreen") if self._pending else pal.color(QtGui.QPalette.ColorRole.Text)
        sel_color = pal.color(QtGui.QPalette.ColorRole.Highlight)
        for i, ch in enumerate(self._text_cells()):
            r = self._cell_rect(i)
            if i == self._sel and self.hasFocus():
                c = QtGui.QColor(sel_color)
                c.setAlpha(60)
                p.fillRect(r, c)
            if i == 0 and ch == "+":
                ch = " "
            p.setPen(text_color)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, ch)
            if i == self._hover and self.isEnabled() and (self._cell_weight(i) is not None or (i == 0 and self._min < 0)):
                self._draw_arrows(p, r)
        p.end()

    def _draw_arrows(self, p, r):
        cx = r.center().x() + 1
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.palette().color(QtGui.QPalette.ColorRole.Highlight))
        top = r.top() - 2
        up = QtGui.QPolygon([QtCore.QPoint(cx - 4, top), QtCore.QPoint(cx + 4, top), QtCore.QPoint(cx, top - _ARROW + 2)])
        bot = r.bottom() + 2
        down = QtGui.QPolygon([QtCore.QPoint(cx - 4, bot), QtCore.QPoint(cx + 4, bot), QtCore.QPoint(cx, bot + _ARROW - 2)])
        p.drawPolygon(up)
        p.drawPolygon(down)

    def mouseMoveEvent(self, event):
        cell = self._cell_at(event_pos(event).x())
        if cell != self._hover:
            self._hover = cell
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            return
        pos = event_pos(event)
        cell = self._cell_at(pos.x())
        if cell < 0:
            return
        if self._cell_weight(cell) is not None:
            self._sel = cell
        self.step(cell, 1 if pos.y() < self.height() / 2 else -1)

    def wheelEvent(self, event):
        if not self.isEnabled():
            return
        cell = self._cell_at(event_pos(event).x())
        if self._cell_weight(cell) is None:
            cell = self._sel
        if self._cell_weight(cell) is None:
            return
        delta = event.angleDelta().y()
        if delta:
            self.step(cell, 1 if delta > 0 else -1)
        event.accept()

    def focusInEvent(self, event):
        if self._sel < 0:
            cells = self._digit_cells()
            self._sel = cells[self._int_digits - 1] if len(cells) >= self._int_digits else cells[0]
        self.update()
        QtWidgets.QWidget.focusInEvent(self, event)

    def focusOutEvent(self, event):
        self.update()
        QtWidgets.QWidget.focusOutEvent(self, event)

    def keyPressEvent(self, event):
        key = event.key()
        cells = self._digit_cells()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if self._sel not in cells:
                self._sel = cells[0]
            else:
                i = cells.index(self._sel) + (-1 if key == Qt.Key.Key_Left else 1)
                self._sel = cells[max(0, min(len(cells) - 1, i))]
            self.update()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            if self._sel in cells:
                self.step(self._sel, 1 if key == Qt.Key.Key_Up else -1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.commit()
        elif key == Qt.Key.Key_Escape:
            self.revert()
        elif key == Qt.Key.Key_Minus and self._min < 0:
            self._user_change(-abs(self._units))
        elif key == Qt.Key.Key_Plus:
            self._user_change(abs(self._units))
        elif event.text() and event.text() in "0123456789":
            if self._sel in cells:
                digit = int(event.text())
                weight = self._cell_weight(self._sel)
                current = (abs(self._units) // weight) % 10
                sign = -1 if self._units < 0 else 1
                self._user_change(self._units + sign * (digit - current) * weight)
                i = cells.index(self._sel)
                self._sel = cells[min(len(cells) - 1, i + 1)]
                self.update()
        else:
            QtWidgets.QWidget.keyPressEvent(self, event)


class QAttributeWheelEditor(TangoAttributeWidget, QWheelEditor):
    """ Wheel editor bound to a writable numeric scalar attribute.

    Digits come from the attribute ``format`` (``%6.2f`` gives 3 integer digits
    and 2 decimals), limits from ``min_value``/``max_value``. As in ATK, every
    click writes at once (``writeOnChange`` True); set it False to write on Enter.
    The editor shows the set point when it is meaningful (memorized attribute or
    already written), otherwise the read value (``setPointMode``).
    """

    modelName = model_name_property()

    def __init__(self, parent=None):
        QWheelEditor.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        self.setWriteOnChange(True)
        self.valueCommitted.connect(self._write_value)
        self.editReverted.connect(self._on_reverted)

    def on_config(self, cfg):
        if is_int_type(cfg.data_type):
            ints, decs = format_digits(cfg.format, default=(6, 0))
            decs = 0
        else:
            ints, decs = format_digits(cfg.format, default=(4, 2))
        self.setIntegerDigits(ints)
        self.setDecimals(decs)

        def num(text):
            try:
                return float(text)
            except (TypeError, ValueError):
                return None
        self.setRange(num(cfg.min_value), num(cfg.max_value))
        self.setEnabled(self.model() is not None and self.model().is_writable())
        self.setToolTip(self.tooltip_text())
        self.updateGeometry()
        if self.attributeValue() is not None:
            self.on_value(self.attributeValue())

    #: "auto" (default), "always" (ATK) or "never"; see TangoAttributeWidget.set_point
    setPointMode = "auto"

    def on_value(self, value):
        if self.write_pending():
            return      # a value read between the user's writes would undo the clicks after it
        self._show(value)

    def _show(self, value):
        shown = self.set_point(value, self.setPointMode)
        try:
            self.setValue(float(shown))
        except (TypeError, ValueError):
            pass

    def on_error(self, err):
        self.setToolTip(self.tooltip_text())

    def on_model_cleared(self):
        """ Unbound: nothing to write to """
        self.setEnabled(False)
        self._tnext = None
        self._pending = False
        self._set_units(0, external=True)
        self.setToolTip("")

    def on_write_done(self, err):
        if err is not None and self.writing():
            self.setToolTip(self.tooltip_text() + "<br/><font color='red'>Write failed: {0}</font>".format(err.message))
            self._on_reverted()     # show the device value again, as the other setters do

    def _write_value(self, value):
        cfg = self.attributeConfig()
        if cfg is not None and is_int_type(cfg.data_type):
            value = int(round(value))
        self.write_latest(value)    # one write at a time, in order

    def _on_reverted(self):
        if self.attributeValue() is not None:
            self._show(self.attributeValue())
