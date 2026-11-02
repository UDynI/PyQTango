# -*- coding: utf-8 -*-
"""
QTangoMainWindow: extension of QMainWindow that setup Tango event translation
to Qt events and support GUI scaling for HiDpi screens.

Created on Wed Mar 16 2022

@author: Michele Devetta <michele.devetta@cnr.it>
"""

from .qt import QtGui, QtWidgets, no_window_flags

import inspect
import os.path as osp
from .TangoWindows import TangoEvents2Qt, WindowScaling


class QTangoMainWindow(TangoEvents2Qt, WindowScaling, QtWidgets.QMainWindow):
    """
    QTangoMainWindow(parent=None, flags=no_window_flags())

    Extension of QMainWindow to create Tango enabled GUIs. The class puts in
    place all that is needed to handle Tango events in Qt GUIs. Connect all
    Tango subscriptions to eventCallback(). Then overload in you derived class
    the method on_TangoEvent(self, event). The method will be supplied with
    EventData structures from Tango.

    NOTE: do not handle Tango events directly in Qt or you will get into
    trobles.

    scaleUi(main_window): this method handle GUI scaling for HiDpi screens. The
    system is designed to be used with GUIs compiled by pyuic5. Use this method
    the same way you use setupUi().

    setIcon(main_window, pixmap): this method set the window icon.

    getImage(image): search for an image and return a QPixmap. The image file
    is searched first in the icons subdirectory of the calling process
    main directory. If not found, it searches also the calling process main
    directory itself.

    """

    def __init__(self, parent=None, flags=no_window_flags()):
        """ Constructor
        """
        # Call parent constructor
        QtWidgets.QMainWindow.__init__(self, parent, flags)
        TangoEvents2Qt.__init__(self)
        WindowScaling.__init__(self)

    def setIcon(self, ui, pixmap):
        """ Set window icon
        """
        icon = QtGui.QIcon()
        icon.addPixmap(pixmap, QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.Off)
        ui.setWindowIcon(icon)

    def getImage(self, image):
        frame = inspect.stack()[1]
        module = inspect.getmodule(frame[0])
        path = osp.abspath(osp.dirname(module.__file__))

        image_path = osp.join(path, 'icons', image)
        if not osp.isfile(image_path):
            image_path = osp.join(path, image)
            if not osp.isfile(image_path):
                return QtGui.QPixmap()

        return QtGui.QPixmap(osp.abspath(image_path))


class QTangoDialog(TangoEvents2Qt, WindowScaling, QtWidgets.QDialog):
    """ Same as QTangoMainWindow but for QDialogs
    """

    def __init__(self, parent=None, f=no_window_flags()):
        """ Constructor
        """
        # Call parent constructor
        QtWidgets.QDialog.__init__(self, parent, f)
        TangoEvents2Qt.__init__(self)
        WindowScaling.__init__(self)
