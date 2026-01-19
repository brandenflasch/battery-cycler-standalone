"""
Setup script for building Battery Cycler as a macOS app bundle.
Uses battery CLI for direct SMC control - no AlDente required.

Run: python setup.py py2app
"""

from setuptools import setup

APP = ['battery_cycler_gui.py']
DATA_FILES = [
    ('', ['battery_cycle.sh']),
    ('bin', ['bin/battery', 'bin/smc', 'bin/stress-ng']),
]
OPTIONS = {
    'argv_emulation': False,
    'iconfile': None,
    'plist': {
        'CFBundleName': 'Battery Cycler',
        'CFBundleDisplayName': 'Battery Cycler',
        'CFBundleIdentifier': 'com.brandenflasch.battery-cycler',
        'CFBundleVersion': '2.0.0',
        'CFBundleShortVersionString': '2.0.0',
        'LSUIElement': True,  # Hide from Dock (menu bar app)
        'NSHighResolutionCapable': True,
    },
    'packages': ['rumps'],
}

setup(
    app=APP,
    name='Battery Cycler',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
