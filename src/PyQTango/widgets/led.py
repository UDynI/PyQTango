# -*- coding: utf-8 -*-
"""
Created on Tue May 12 11:13:29 2020

@author: Michele Devetta <michele.devetta@cnr.it>
"""

from ..qt import QtCore, QtGui, QtWidgets, Slot, Property

from .icons import get_image_path


class QStatusLed(QtWidgets.QLabel):

    Off = 0
    On = 1
    Blinking = 2
    Error = 3

    def __init__(self, parent=None):
        # Parent constructor
        QtWidgets.QLabel.__init__(self, parent)

        # Icons
        self.setupIcons(self.size())

        # Label
        self.setPixmap(self.icon_off)
        self.__state = QStatusLed.Off

        self.timer_id = None
        self.timer_icon_on = False

    def update_state(self):
        if self.__state == QStatusLed.On:
            self.setPixmap(self.icon_green)
        elif self.__state == QStatusLed.Blinking:
            self.setPixmap(self.icon_green)
            self.timer_icon_on = True
            if self.timer_id is None:
                self.timer_id = self.startTimer(1000)
        elif self.__state == QStatusLed.Error:
            self.setPixmap(self.icon_red)
        else:
            self.setPixmap(self.icon_off)

    def timerEvent(self, event):
        if self.__state == QStatusLed.Blinking:
            # Swap icon
            if self.timer_icon_on:
                self.setPixmap(self.icon_off)
                self.timer_icon_on = False
            else:
                self.setPixmap(self.icon_green)
                self.timer_icon_on = True
        else:
            # Stop timer
            self.killTimer(self.timer_id)
            self.timer_id = None
        event.accept()

    def getState(self):
        """ The state (``led.state`` reads the same value: it is the Qt property) """
        return self.__state

    @Slot(int)
    def setState(self, state):
        if state == QStatusLed.On:
            self.__state = QStatusLed.On
        elif state == QStatusLed.Blinking:
            self.__state = QStatusLed.Blinking
        elif state == QStatusLed.Error:
            self.__state = QStatusLed.Error
        else:
            self.__state = QStatusLed.Off
        self.update_state()

    state = Property(int, getState, setState)

    def resizeEvent(self, event):
        if event.size().isValid():
            sz = event.size()
            self.setupIcons(sz)
            self.update_state()

    def setupIcons(self, sz):
        gicon = QtGui.QPixmap(get_image_path("led-green.png"))
        self.icon_green = gicon.scaled(sz.width(), sz.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)
        ricon = QtGui.QPixmap(get_image_path("led-red.png"))
        self.icon_red = ricon.scaled(sz.width(), sz.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)
        oicon = QtGui.QPixmap(get_image_path("led-off.png"))
        self.icon_off = oicon.scaled(sz.width(), sz.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)
