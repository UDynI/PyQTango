""" PyQTango

"""

# Always prefer setuptools over distutils
from setuptools import setup, find_packages
import pathlib

here = pathlib.Path(__file__).parent.resolve()

# Get the long description from the README file
long_description = (here / 'README.md').read_text(encoding='utf-8')

setup(
    name='PyQTango',
    version='0.2.1',
    description='A library of event-aware Tango widgets for PyQt5 and PyQt6',

    # Long description from README.md
    long_description=long_description,
    long_description_content_type='text/markdown',

    # GIT
    url='https://storage.udyni.lab/git/UDynI/PyQTango',

    author='Michele Devetta',
    author_email='michele.devetta@cnr.it',

    # Classifiers (see https://pypi.org/classifiers/)
    classifiers=[
        # How mature is this project? Common values are
        'Development Status :: 4 - Beta',

        # License
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',

        # Programming languages
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Environment :: X11 Applications :: Qt',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.13',

        # Operating system
        'Operating System :: OS Independent',
    ],

    # Keywords
    keywords='tango, pytango, qt5, qt6, pyqt5, pyqt6, widgets',

    # When your source code is in a subdirectory under the project root, e.g.
    # `src/`, it is necessary to specify the `package_dir` argument.
    package_dir={'': 'src'},

    # Packages
    packages=find_packages(where='src'),

    # Python version
    python_requires='>=3.7, <4',

    # Dependencies: PyQt5 is the default binding (lab GUIs); PyQt6 is also supported
    # through PyQTango.qt (select it with PYQTANGO_QT_API=pyqt6 or by importing it first).
    install_requires=['pyqt5>=5.15', 'pytango>=9.5', 'numpy'],
    extras_require={
        'pyqt6': ['pyqt6>=6.4'],
        'test': ['pytest', 'pytest-qt'],
    },

    # If there are data files included in your packages that need to be
    # installed, specify them here.
    package_data={  # Optional
        'PyQTango': ['images/*.png', 'images/*.svg'],
    },
)
