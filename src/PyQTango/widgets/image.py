# -*- coding: utf-8 -*-
"""
Image viewers (ATK ``NumberImageViewer``, ``StringImageTableViewer``, ``RawImageViewer``).

* :class:`QImageViewer`: numeric image on pyqtgraph, with colour maps, automatic
  or fixed levels, zoom, the value under the cursor, a histogram, horizontal and
  vertical profiles, and Save as PNG, TIFF or CSV. ``set_data(array)`` shows any
  2D array; ``setModel(name)`` binds it to an image attribute.
* :class:`QStringImageViewer`: a string image as a table.
* :class:`QRawImageViewer`: a DevEncoded attribute (JPEG, GRAY8, GRAY16, RGB24)
  decoded with :func:`decode_encoded` into a QImageViewer.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import numpy as np

from ..qt import QtGui, QtWidgets, Qt, Signal
from .base import TangoAttributeWidget, model_name_property
import pyqtgraph as pg

__all__ = ["QImageViewer", "QStringImageViewer", "QRawImageViewer", "decode_encoded", "COLOR_MAPS",
           "EncodedImageError"]

#: Colour maps offered by QImageViewer (label -> pyqtgraph name; "Gray" is built in)
COLOR_MAPS = {"Gray": None, "Viridis": "viridis", "Inferno": "inferno", "Plasma": "plasma",
              "Magma": "magma", "Cividis": "cividis", "Turbo": "turbo", "Fire": "CET-L3"}


def _colormap(label):
    name = COLOR_MAPS.get(label)
    if name is None:
        return pg.ColorMap([0.0, 1.0], [(0, 0, 0), (255, 255, 255)])
    return pg.colormap.get(name)


class EncodedImageError(ValueError):
    pass


def decode_encoded(value):
    """ Decode a DevEncoded value ``(format, bytes)`` into a numpy image.

    Returns a 2D array (gray formats) or an (h, w, 3) uint8 array (colour JPEG,
    RGB24). Tango's GRAY8, GRAY16 and RGB24 encodings start with a 4-byte
    big-endian header (width, height), as written by ``EncodedAttribute``.
    """
    fmt, data = value
    fmt = (fmt or "").upper()
    data = bytes(data)
    if "JPEG" in fmt or "JPG" in fmt:
        img = QtGui.QImage.fromData(data)
        if img.isNull():
            raise EncodedImageError("Invalid JPEG data")
        gray = "GRAY" in fmt or img.isGrayscale()
        img = img.convertToFormat(QtGui.QImage.Format.Format_Grayscale8 if gray else QtGui.QImage.Format.Format_RGB888)
        w, h, bpl = img.width(), img.height(), img.bytesPerLine()
        ptr = img.constBits()
        ptr.setsize(h * bpl)
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, bpl)
        return arr[:, :w].copy() if gray else arr[:, :w * 3].reshape(h, w, 3).copy()
    if fmt in ("GRAY8", "GRAY16", "RGB24"):
        if len(data) < 4:
            raise EncodedImageError("{0}: missing header".format(fmt))
        w = (data[0] << 8) | data[1]
        h = (data[2] << 8) | data[3]
        body = data[4:]
        size, dtype, shape = {"GRAY8": (1, np.uint8, (h, w)), "GRAY16": (2, ">u2", (h, w)),
                              "RGB24": (3, np.uint8, (h, w, 3))}[fmt]
        if len(body) < w * h * size:
            raise EncodedImageError("{0}: {1}x{2} needs {3} bytes, got {4}".format(fmt, w, h, w * h * size, len(body)))
        arr = np.frombuffer(body[:w * h * size], dtype=dtype).reshape(shape)
        return arr.astype(np.uint16) if fmt == "GRAY16" else arr.copy()
    raise EncodedImageError("Unsupported encoded format: " + (fmt or "(empty)"))


class QImageViewer(TangoAttributeWidget, QtWidgets.QWidget):
    """ 2D array viewer: ``set_data(array)`` with rows as y and columns as x.

    Signals:
        imageChanged(): new data shown
    """

    imageChanged = Signal()
    modelName = model_name_property()

    def __init__(self, parent=None, toolbar=True):
        QtWidgets.QWidget.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bar = QtWidgets.QWidget(self)
        bar = QtWidgets.QHBoxLayout(self.bar)
        bar.setContentsMargins(2, 2, 2, 2)
        self.colormap = QtWidgets.QComboBox(self.bar)
        self.colormap.addItems(list(COLOR_MAPS))
        self.colormap.setCurrentText("Viridis")
        self.auto_levels = QtWidgets.QCheckBox("Auto levels", self.bar)
        self.auto_levels.setChecked(True)
        self.min_level = QtWidgets.QLineEdit(self.bar)
        self.max_level = QtWidgets.QLineEdit(self.bar)
        for w, tip in ((self.min_level, "Minimum level"), (self.max_level, "Maximum level")):
            w.setFixedWidth(72)
            w.setToolTip(tip)
            w.setEnabled(False)
            w.editingFinished.connect(self._fixed_levels)
        self.profiles = QtWidgets.QCheckBox("Profiles", self.bar)
        self.save_button = QtWidgets.QPushButton("Save...", self.bar)
        self.colormap.setToolTip("Colour map")
        bar.addWidget(self.colormap)
        bar.addWidget(self.auto_levels)
        bar.addWidget(self.min_level)
        bar.addWidget(self.max_level)
        bar.addWidget(self.profiles)
        bar.addStretch(1)
        bar.addWidget(self.save_button)
        layout.addWidget(self.bar)
        self.bar.setVisible(toolbar)
        split = QtWidgets.QSplitter(Qt.Orientation.Vertical, self)
        self.view = pg.ImageView(split)
        self.view.ui.roiBtn.hide()
        self.view.ui.menuBtn.hide()
        split.addWidget(self.view)
        self.profile_widget = pg.GraphicsLayoutWidget(split)
        self.profile_widget.setBackground("w")
        self.h_profile = self.profile_widget.addPlot(row=0, col=0, title="Horizontal profile")
        self.v_profile = self.profile_widget.addPlot(row=0, col=1, title="Vertical profile")
        self.h_curve = self.h_profile.plot(pen=pg.mkPen("#0050c0"))
        self.v_curve = self.v_profile.plot(pen=pg.mkPen("#c00000"))
        split.addWidget(self.profile_widget)
        self.profile_widget.hide()
        layout.addWidget(split, 1)
        self.position = QtWidgets.QLabel(self)
        layout.addWidget(self.position)
        self.h_line = pg.InfiniteLine(angle=0, movable=True, pen=pg.mkPen("#0050c0"))
        self.v_line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#c00000"))
        for line in (self.h_line, self.v_line):
            line.hide()
            line.sigPositionChanged.connect(self._update_profiles)
            self.view.getView().addItem(line)
        self.view.getView().scene().sigMouseMoved.connect(self._mouse_moved)
        self.colormap.currentTextChanged.connect(self.set_colormap)
        self.auto_levels.toggled.connect(self._auto_toggled)
        self.profiles.toggled.connect(self.show_profiles)
        self.save_button.clicked.connect(self.save_dialog)
        self._data = None
        self._first = True
        self._profile_set = False
        self.set_colormap("Viridis")
        self.setMinimumSize(320, 240)

    # -- Data ------------------------------------------------------------------
    def set_data(self, data):
        data = np.asarray(data)
        if data.ndim == 3 and data.shape[2] in (3, 4):
            rgb = True
        else:
            data = np.atleast_2d(np.asarray(data, dtype=float))
            rgb = False
        auto = self.auto_levels.isChecked()
        draw = data
        kwargs = {"autoRange": self._first, "autoLevels": False, "autoHistogramRange": auto}
        if not rgb:
            # pyqtgraph fails on a range with inf, or with only NaN: draw inf as NaN
            # and take the automatic levels from the finite values
            finite = np.isfinite(data)
            if not finite.all():
                draw = np.where(finite, data, np.nan)
            if auto:
                kwargs["levels"] = ((float(data[finite].min()), float(data[finite].max()))
                                    if finite.any() else (0.0, 1.0))
                kwargs["autoHistogramRange"] = bool(finite.any())
            else:
                kwargs["levels"] = self._levels()
        else:
            kwargs["autoLevels"] = auto
        # pyqtgraph images are indexed [x, y]: transpose so rows run down the y axis
        img = draw.transpose(1, 0, 2) if rgb else draw.T
        self.view.setImage(img, **kwargs)
        self._data = data           # only once drawn: the cursor and profiles read it
        self._first = False
        if auto and not rgb:
            lo, hi = self.view.getLevels()
            self.min_level.setText("{0:.4g}".format(lo))
            self.max_level.setText("{0:.4g}".format(hi))
        if self.profiles.isChecked():
            self._update_profiles()
        self.imageChanged.emit()

    def data(self):
        return self._data

    def levels(self):
        return self.view.getLevels()

    def set_levels(self, lo, hi):
        """ Fixed levels (turns automatic levels off) """
        self.auto_levels.setChecked(False)
        self.min_level.setText("{0:g}".format(lo))
        self.max_level.setText("{0:g}".format(hi))
        self._fixed_levels()

    def set_auto_levels(self, on=True):
        self.auto_levels.setChecked(on)

    def set_colormap(self, label):
        if label not in COLOR_MAPS:
            raise ValueError("Unknown colour map: " + label)
        if self.colormap.currentText() != label:
            self.colormap.setCurrentText(label)
            return
        self.view.setColorMap(_colormap(label))

    def colormap_name(self):
        return self.colormap.currentText()

    def _levels(self):
        lo, hi = self.view.getLevels() if self._data is not None else (0.0, 1.0)
        try:
            lo = float(self.min_level.text())
        except ValueError:
            pass
        try:
            hi = float(self.max_level.text())
        except ValueError:
            pass
        return lo, hi

    def _auto_toggled(self, on):
        self.min_level.setEnabled(not on)
        self.max_level.setEnabled(not on)
        if on and self._data is not None:
            self.set_data(self._data)

    def _fixed_levels(self):
        if self.auto_levels.isChecked() or self._data is None:
            return
        self.view.setLevels(*self._levels())

    # -- Profiles --------------------------------------------------------------
    def show_profiles(self, on=True):
        if self.profiles.isChecked() != bool(on):
            self.profiles.setChecked(bool(on))
            return
        self.profile_widget.setVisible(bool(on))
        for line in (self.h_line, self.v_line):
            line.setVisible(bool(on))
        if on and self._data is not None:
            rows, cols = self._data.shape[:2]
            if not self._profile_set or not (0 <= self.h_line.value() < rows):
                self.h_line.setValue(rows // 2 + 0.5)
            if not self._profile_set or not (0 <= self.v_line.value() < cols):
                self.v_line.setValue(cols // 2 + 0.5)
            self._profile_set = True
            self._update_profiles()

    def set_profile_position(self, x, y):
        self._profile_set = True
        self.v_line.setValue(x + 0.5)
        self.h_line.setValue(y + 0.5)
        self._update_profiles()

    def profile_data(self):
        """ (row index, row values, column index, column values) or None """
        if self._data is None or self._data.ndim != 2:
            return None
        rows, cols = self._data.shape
        if rows == 0 or cols == 0:
            return None
        r = int(np.clip(np.floor(self.h_line.value()), 0, rows - 1))
        c = int(np.clip(np.floor(self.v_line.value()), 0, cols - 1))
        return r, self._data[r, :], c, self._data[:, c]

    def _update_profiles(self, *_):
        p = self.profile_data()
        if p is None or not self.profile_widget.isVisible():
            return
        r, row, c, col = p
        self.h_curve.setData(np.arange(len(row)), row)
        self.v_curve.setData(np.arange(len(col)), col)
        self.h_profile.setTitle("Horizontal profile (y={0})".format(r))
        self.v_profile.setTitle("Vertical profile (x={0})".format(c))

    # -- Save ------------------------------------------------------------------
    def ask_save_path(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save image", "",
                                                        "PNG image (*.png);;TIFF image (*.tif *.tiff);;"
                                                        "CSV values (*.csv)")
        return path or None

    def save_dialog(self):
        path = self.ask_save_path()
        if path:
            try:
                return self.save(path)
            except (IOError, OSError, ValueError) as e:
                QtWidgets.QMessageBox.critical(self, "Error", str(e))
        return None

    def save(self, path):
        """ PNG or TIFF (rendered with the colour map and levels) or CSV (raw values) """
        if self._data is None:
            raise ValueError("No image to save")
        p = str(path)
        if p.lower().endswith(".csv"):
            data = self._data if self._data.ndim == 2 else self._data.reshape(self._data.shape[0], -1)
            np.savetxt(p, data, delimiter=",", fmt="%.10g")
            return p
        item = self.view.getImageItem()
        qimg = item.qimage
        if qimg is None:
            item.render()
            qimg = item.qimage
        if qimg is None or not qimg.save(p):
            raise IOError("Cannot save " + p)
        return p

    # -- Cursor ----------------------------------------------------------------
    def value_at(self, x, y):
        if self._data is None:
            return None
        rows, cols = self._data.shape[:2]
        if 0 <= x < cols and 0 <= y < rows:
            return self._data[y, x]
        return None

    def _mouse_moved(self, pos):
        if self._data is None:
            return
        p = self.view.getImageItem().mapFromScene(pos)
        x, y = int(np.floor(p.x())), int(np.floor(p.y()))
        v = self.value_at(x, y)
        self.position.setText("" if v is None else "x={0} y={1} value={2}".format(x, y, v))

    # -- Attribute binding -----------------------------------------------------
    def on_value(self, value):
        if value.value is None:
            return
        try:
            self.set_data(self.image_of(value.value))
            self.position.setStyleSheet("")
        except Exception as e:  # noqa: BLE001  (pyqtgraph raises plain Exception)
            self.position.setText(str(e))
            self.position.setStyleSheet("color: red;")

    def image_of(self, value):
        return value

    def on_error(self, err):
        if err is not None:
            self.position.setText(err.message)
            self.position.setStyleSheet("color: red;")
        else:
            self.position.setStyleSheet("")


class QRawImageViewer(QImageViewer):
    """ DevEncoded attribute decoded into an image (JPEG, GRAY8, GRAY16, RGB24) """

    def image_of(self, value):
        return decode_encoded(value)

    def on_value(self, value):
        if value.value is None:
            return
        try:
            self.set_data(decode_encoded(value.value))
            self.position.setStyleSheet("")
            self.position.setText("{0} {1}x{2}".format(value.value[0], self._data.shape[1], self._data.shape[0]))
        except (EncodedImageError, ValueError, TypeError) as e:
            self.position.setText(str(e))
            self.position.setStyleSheet("color: red;")


class QStringImageViewer(TangoAttributeWidget, QtWidgets.QTableWidget):
    """ String image as a table (ATK ``StringImageTableViewer``) """

    modelName = model_name_property()

    def __init__(self, parent=None):
        QtWidgets.QTableWidget.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

    def set_data(self, rows):
        rows = [list(r) for r in (rows or [])]
        ncols = max((len(r) for r in rows), default=0)
        self.setRowCount(len(rows))
        self.setColumnCount(ncols)
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                item = self.item(i, j)
                if item is None:
                    self.setItem(i, j, QtWidgets.QTableWidgetItem(str(v)))
                else:
                    item.setText(str(v))

    def data(self):
        return [[self.item(i, j).text() if self.item(i, j) else "" for j in range(self.columnCount())]
                for i in range(self.rowCount())]

    def on_value(self, value):
        v = value.value
        if v is None:
            self.set_data([])
            return
        if len(v) and isinstance(v[0], str):
            # PyTango flattens a string image with one row
            v = [v]
        self.set_data(v)
        self.setStyleSheet("")

    def on_error(self, err):
        self.setStyleSheet("" if err is None else "QTableWidget { border: 2px solid red; }")
        self.setToolTip("" if err is None else err.message)
