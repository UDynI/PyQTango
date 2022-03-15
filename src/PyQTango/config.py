# -*- coding: utf-8 -*-
"""
Created on Tue May 12 11:13:29 2020

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import sys
import os.path as osp


def get_image_path(image, module="PyQTango"):
    """ Return the absolute path to the required image from the module
    """
    # Get module absolute path
    path = osp.abspath(osp.dirname(sys.modules[module].__file__))

    # Add image subdirectory
    path = osp.join(path, 'images')

    # Add image name
    path = osp.join(path, image)

    # Check if file exists
    if osp.isfile(path):
        return osp.abspath(path)

    else:
        return ""
