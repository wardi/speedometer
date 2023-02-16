#!/usr/bin/env python
#
# Urwid setup.py exports the useful bits
#    Copyright (C) 2004-2010  Ian Ward
#
#    This library is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 2.1 of the License, or (at your option) any later version.
#
#    This library is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, see <http://www.gnu.org/licenses/>.
#
# Urwid web site: http://excess.org/urwid/

from setuptools import setup

import os

setup_d = {
    'name': "Speedometer",
    'version': '2.9',
    'author': "Ian Ward",
    'author_email': "ian@excess.org",
    'url': "http://excess.org/speedometer/",
    'entry_points': {
        'console_scripts': ['speedometer = speedometer:console'],},
    'install_requires': ['urwid >= 0.9.9.1', 'psutil'],
    'license':"LGPL",
    'keywords':"network bandwidth monitor system speed download file progress console",
    'platforms':"Linux",
    'description':"Console monitor of the rate of data across a network connection or data being stored in a file.",
    'classifiers':[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Environment :: Console :: Curses",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)",
        "Operating System :: POSIX :: Linux",
        "Topic :: System :: Monitoring",
        "Topic :: System :: Networking :: Monitoring",
        ],
     }


setup(** setup_d)
