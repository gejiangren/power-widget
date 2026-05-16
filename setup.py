"""py2app 配置:把 power_widget.py 打包成 PowerWidget.app"""
from setuptools import setup

APP = ['power_widget.py']
OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'icon.icns',
    'plist': {
        'CFBundleName': 'PowerWidget',
        'CFBundleDisplayName': '功耗 Widget',
        'CFBundleIdentifier': 'com.local.powerwidget',
        'CFBundleVersion': '1.1',
        'CFBundleShortVersionString': '1.1',
        'LSUIElement': True,
        'LSMinimumSystemVersion': '11.0',
        'NSHighResolutionCapable': True,
        'NSPrincipalClass': 'NSApplication',
    },
}

setup(
    app=APP,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
