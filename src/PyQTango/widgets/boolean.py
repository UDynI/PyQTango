# -*- coding: utf-8 -*-
"""
Boolean widgets added in ATK 9.4/10.0:

* :class:`QBooleanLabel` - ATK ``BooleanScalarLabelViewer`` (coloured label) and
  ``BooleanScalarTickViewer`` (tick / cross), selected with ``displayMode``.
* :class:`QSwitchButton` - painted on/off switch (ATK ``SwitchButton``), no Tango.
* :class:`QSwitchSetter` - title + switch bound to a DevBoolean attribute
  (ATK ``BooleanScalarSwitchButton``), with an optional confirmation.
"""

import tango

from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal, Property, enum_value
from ..core.formatting import quality_color
from .base import TangoAttributeWidget, model_name_property

_TICK = u"✔"
_CROSS = u"✕"
_WRITABLE = (tango.AttrWriteType.READ_WRITE, tango.AttrWriteType.READ_WITH_WRITE, tango.AttrWriteType.WRITE)
_NO_LABEL = ("", "Not specified")
_CENTER = enum_value(Qt.AlignmentFlag.AlignCenter)


def text_color_for(background):
    """ Black or white text, whichever reads better on ``background`` (ATK rule) """
    c = QtGui.QColor(background)
    luminance = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255.0
    return QtGui.QColor("#000000") if luminance > 0.5 else QtGui.QColor("#ffffff")


def ask_yes_no(parent, title, message):
    """ Modal Yes/No question, "No" by default. Returns True for Yes. """
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Warning, title, message,
                                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                                parent)
    box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.No)
    return box.exec() == QtWidgets.QMessageBox.StandardButton.Yes


def _color_property(attr):
    def getter(self):
        return QtGui.QColor(getattr(self, attr))

    def setter(self, color):
        setattr(self, attr, QtGui.QColor(color))
        self._update_look()
    return Property(QtGui.QColor, getter, setter)


def _text_property(attr):
    def getter(self):
        return getattr(self, attr)

    def setter(self, text):
        setattr(self, attr, text or "")
        self._update_look()
    return Property(str, getter, setter)


class QBooleanLabel(TangoAttributeWidget, QtWidgets.QLabel):
    """ Read-only view of a DevBoolean attribute.

    ``displayMode``:

    * ``"label"`` (default, ATK ``BooleanScalarLabelViewer``): the text (attribute
      label, or ``trueText``/``falseText`` when set) on ``trueColor`` (green) or
      ``falseColor`` (white);
    * ``"tick"`` (ATK ``BooleanScalarTickViewer``): a large tick or cross on
      ``trueColor``/``falseColor`` (white / light grey in this mode by default).

    Read errors and invalid values show ``errorColor`` (red). ATK hides the label
    until a valid attribute is set; set ``hideUntilValid`` to get that behaviour.
    """

    modelName = model_name_property()

    def __init__(self, parent=None):
        QtWidgets.QLabel.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        self._mode = "label"
        self._true_color = QtGui.QColor("#00ff00")
        self._false_color = QtGui.QColor("#ffffff")
        self._error_color = QtGui.QColor("#ff0000")
        self._true_text = ""
        self._false_text = ""
        self._hide_until_valid = False
        self._state = None          # True, False or None (unknown / error)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMargin(2)
        self._update_look()

    # -- Properties ---------------------------------------------------------------
    def getDisplayMode(self):
        return self._mode

    def setDisplayMode(self, mode):
        mode = "tick" if mode == "tick" else "label"
        if mode != self._mode:
            self._mode = mode
            # Mode defaults, as in ATK
            if mode == "tick":
                self._true_color, self._false_color = QtGui.QColor("#ffffff"), QtGui.QColor("#c0c0c0")
            else:
                self._true_color, self._false_color = QtGui.QColor("#00ff00"), QtGui.QColor("#ffffff")
        self._update_look()

    displayMode = Property(str, getDisplayMode, setDisplayMode)
    trueColor = _color_property("_true_color")
    falseColor = _color_property("_false_color")
    errorColor = _color_property("_error_color")
    trueText = _text_property("_true_text")
    falseText = _text_property("_false_text")

    def getHideUntilValid(self):
        return self._hide_until_valid

    def setHideUntilValid(self, b):
        self._hide_until_valid = bool(b)
        self._update_look()

    hideUntilValid = Property(bool, getHideUntilValid, setHideUntilValid)

    def booleanValue(self):
        """ True / False, or None when unknown or in error """
        return self._state

    # -- Model hooks ----------------------------------------------------------------
    def on_config(self, cfg):
        self.setToolTip(self.tooltip_text())
        self._update_look()

    def on_value(self, value):
        if value.quality == tango.AttrQuality.ATTR_INVALID or value.value is None:
            self._state = None
        else:
            self._state = bool(value.value)
        self.setToolTip(self.tooltip_text())
        self._update_look()

    def on_error(self, err):
        if err is not None:
            self._state = None
        self.setToolTip(self.tooltip_text())
        self._update_look()

    def on_model_cleared(self):
        self._state = None
        self.setToolTip("")
        self._update_look()

    # -- Rendering -------------------------------------------------------------------
    def _label_text(self):
        cfg = self.attributeConfig()
        if cfg is not None and cfg.label not in _NO_LABEL:
            return cfg.label
        m = self.model()
        return m.attr_name if m is not None else ""

    def _update_look(self):
        state = self._state
        if self._mode == "tick":
            text = "?" if state is None else (_TICK if state else _CROSS)
            font = self.font()
            font.setBold(True)
            font.setPointSizeF(max(QtWidgets.QApplication.font().pointSizeF(), 9.0) * 1.6)
            self.setFont(font)
        else:
            text = (self._true_text if state else self._false_text) if state is not None else ""
            text = text or self._label_text()
            self.setFont(QtWidgets.QApplication.font())
        bg = self._error_color if state is None else (self._true_color if state else self._false_color)
        if self.model() is None:
            bg = self.palette().color(QtGui.QPalette.ColorRole.Window)
        self.setText(text)
        self.setStyleSheet("background-color: {0}; color: {1}; border: 1px solid #808080; padding: 1px 4px;".format(
            bg.name(), text_color_for(bg).name()))
        if self._hide_until_valid:
            self.setVisible(state is not None)


class QSwitchButton(QtWidgets.QAbstractButton):
    """ Painted on/off switch (ATK ``SwitchButton``).

    A checkable button: click or Space toggles it with a short animation. The
    "on" side shows ``onText`` on ``onColor``, the "off" side ``offText`` on
    ``offColor``; the text colour follows the background luminance.

    With ``needsConfirmation`` a Yes/No question (``warningMessage``, with
    ``{current}`` and ``{next}`` placeholders) is asked first. If the state is
    changed from outside while the question is open, the toggle is dropped.

    Signals: ``switched(bool)`` only for user toggles (``toggled`` also fires for
    programmatic changes).
    """

    switched = Signal(bool)

    def __init__(self, parent=None, onText="ON", offText="OFF", needsConfirmation=False):
        QtWidgets.QAbstractButton.__init__(self, parent)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        self._on_text = onText
        self._off_text = offText
        self._on_color = QtGui.QColor("#00ff00")
        self._off_color = QtGui.QColor("#ffffff")
        self._needs_confirmation = bool(needsConfirmation)
        self._warning = "Switch from {current} to {next}?"
        self._asking = False
        self._pos = 0.0     # 0 = off, 1 = on (animated)
        self._anim = QtCore.QVariantAnimation(self)
        self._anim.setDuration(120)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)

    # -- Properties ----------------------------------------------------------------
    def _update_look(self):
        self.updateGeometry()
        self.update()

    onText = _text_property("_on_text")
    offText = _text_property("_off_text")
    onColor = _color_property("_on_color")
    offColor = _color_property("_off_color")

    def getNeedsConfirmation(self):
        return self._needs_confirmation

    def setNeedsConfirmation(self, b):
        self._needs_confirmation = bool(b)

    needsConfirmation = Property(bool, getNeedsConfirmation, setNeedsConfirmation)

    def getWarningMessage(self):
        return self._warning

    def setWarningMessage(self, text):
        self._warning = text or "Switch from {current} to {next}?"

    warningMessage = Property(str, getWarningMessage, setWarningMessage)

    def isAskingConfirmation(self):
        return self._asking

    # -- Behaviour -------------------------------------------------------------------
    def ask_confirmation(self, message):
        """ Override (or replace on the instance) to change how confirmation is asked """
        return ask_yes_no(self, "Confirm", message)

    def nextCheckState(self):
        before = self.isChecked()
        if self._needs_confirmation:
            current, nxt = (self._on_text, self._off_text) if before else (self._off_text, self._on_text)
            self._asking = True
            try:
                ok = self.ask_confirmation(self._warning.format(current=current, next=nxt))
            finally:
                self._asking = False
            if not ok or self.isChecked() != before:
                return
        self.setChecked(not before)
        self.switched.emit(not before)

    def _animate(self, checked):
        target = 1.0 if checked else 0.0
        self._anim.stop()
        if not self.isVisible():
            self._pos = target
            self.update()
            return
        self._anim.setStartValue(float(self._pos))
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_anim(self, v):
        self._pos = float(v)
        self.update()

    # -- Geometry and painting ----------------------------------------------------------
    def sizeHint(self):
        fm = self.fontMetrics()
        h = fm.height() + 8
        w = max(fm.horizontalAdvance(self._on_text), fm.horizontalAdvance(self._off_text)) + h + 12
        return QtCore.QSize(max(w, 2 * h), h)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        h = r.height()
        knob = h - 4
        travel = r.width() - knob - 4
        enabled = self.isEnabled()

        def tone(c):
            return c if enabled else QtGui.QColor(c).darker(115)

        # Background: off colour, on colour blended in with the knob position
        p.setPen(QtGui.QPen(QtGui.QColor("#808080")))
        p.setBrush(tone(self._off_color))
        p.drawRect(r)
        if self._pos > 0:
            p.setOpacity(self._pos)
            p.setBrush(tone(self._on_color))
            p.drawRect(r)
            p.setOpacity(1.0)
        # Text on the free side
        on = self._pos >= 0.5
        bg = self._on_color if on else self._off_color
        p.setPen(text_color_for(bg) if enabled else QtGui.QColor("#808080"))
        if on:
            text_rect = QtCore.QRectF(r.left() + 4, r.top(), travel, h)
            p.drawText(text_rect, _CENTER, self._on_text)
        else:
            text_rect = QtCore.QRectF(r.left() + knob + 4, r.top(), travel, h)
            p.drawText(text_rect, _CENTER, self._off_text)
        # Knob
        x = r.left() + 2 + self._pos * travel
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.palette().color(QtGui.QPalette.ColorRole.WindowText) if enabled else QtGui.QColor("#a0a0a0"))
        p.drawRect(QtCore.QRectF(x, r.top() + 2, knob, knob))
        if self.hasFocus():
            p.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.ColorRole.Highlight), 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r.adjusted(1, 1, -1, -1))
        p.end()

    def hitButton(self, pos):
        return self.rect().contains(pos)


class QSwitchSetter(TangoAttributeWidget, QtWidgets.QWidget):
    """ Title and on/off switch bound to a writable DevBoolean attribute
    (ATK ``BooleanScalarSwitchButton``).

    * the title is the attribute label, or ``trueLabel``/``falseLabel`` when set,
      or a fixed ``title``;
    * the switch follows the read value (``setPointMode`` "never" by default) and
      writes on each user toggle;
    * with ``needsConfirmation`` the toggle asks first; values arriving while the
      question is open are applied, and a toggle whose starting state changed
      meanwhile is dropped;
    * the switch is disabled while the attribute is in error or not writable; a
      failed write puts it back and shows the error in the tooltip;
    * ``showQuality`` colours the title background with the ATK quality colour.
    """

    modelName = model_name_property()
    setPointMode = "never"

    def __init__(self, parent=None, title=None, onText="ON", offText="OFF", needsConfirmation=False):
        QtWidgets.QWidget.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QtWidgets.QLabel(self)
        self.switch = QSwitchButton(self, onText, offText, needsConfirmation)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.switch, 0)
        self._title = title or ""
        self._true_label = ""
        self._false_label = ""
        self._show_quality = False
        self._writable = False
        self.switch.setEnabled(False)
        self.switch.switched.connect(self._on_switched)
        self._update_look()

    # -- Properties ------------------------------------------------------------------
    title = _text_property("_title")
    trueLabel = _text_property("_true_label")
    falseLabel = _text_property("_false_label")

    def getShowQuality(self):
        return self._show_quality

    def setShowQuality(self, b):
        self._show_quality = bool(b)
        self._update_look()

    showQuality = Property(bool, getShowQuality, setShowQuality)

    def setNeedsConfirmation(self, b):
        self.switch.setNeedsConfirmation(b)

    def needsConfirmation(self):
        return self.switch.getNeedsConfirmation()

    def setWarningMessage(self, text):
        self.switch.setWarningMessage(text)

    def setOnText(self, text):
        self.switch.onText = text

    def setOffText(self, text):
        self.switch.offText = text

    def setOnColor(self, color):
        self.switch.onColor = QtGui.QColor(color)

    def setOffColor(self, color):
        self.switch.offColor = QtGui.QColor(color)

    def isChecked(self):
        return self.switch.isChecked()

    # -- Model hooks ----------------------------------------------------------------------
    def on_config(self, cfg):
        self._writable = cfg.writable in _WRITABLE
        self.setToolTip(self.tooltip_text())
        self._update_look()

    def on_value(self, value):
        shown = self.set_point(value, self.setPointMode)
        if shown is not None and value.quality != tango.AttrQuality.ATTR_INVALID:
            self.switch.blockSignals(True)
            self.switch.setChecked(bool(shown))
            self.switch.blockSignals(False)
            # (toggled is blocked: move the knob directly)
            self.switch._animate(bool(shown))
        self._update_look()

    def on_error(self, err):
        self.setToolTip(self.tooltip_text())
        self._update_look()

    def on_write_done(self, err):
        tip = self.tooltip_text()
        if err is not None:
            tip += "<br/><font color='red'>Write failed: {0}</font>".format(err.message)
            if self.attributeValue() is not None:
                self.on_value(self.attributeValue())
        self.setToolTip(tip)

    def on_model_cleared(self):
        self._writable = False
        self.setToolTip("")
        self._update_look()

    def _on_switched(self, checked):
        if self._writable:
            self.write(bool(checked))

    # -- Rendering ------------------------------------------------------------------------
    def _update_look(self):
        value = self.attributeValue()
        in_error = self.attributeError() is not None
        self.switch.setEnabled(self.model() is not None and self._writable and not in_error)
        text = self._title
        if not text and value is not None:
            text = self._true_label if (self.switch.isChecked() and self._true_label) else ""
            if not self.switch.isChecked() and self._false_label:
                text = self._false_label
        if not text:
            cfg = self.attributeConfig()
            if cfg is not None and cfg.label not in _NO_LABEL:
                text = cfg.label
            elif self.model() is not None:
                text = self.model().attr_name
        self.label.setText(text)
        if self._show_quality and value is not None:
            self.label.setStyleSheet("background-color: {0}; padding: 1px 4px;".format(quality_color(value.quality)))
        else:
            self.label.setStyleSheet("padding: 1px 4px;")
