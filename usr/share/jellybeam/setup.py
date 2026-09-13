# setup.py
from setuptools import setup, find_packages
from utils.constants import APP_VERSION

setup(
    name="jellybeam",
    version=APP_VERSION,
    description="Install Jellyfin on Samsung Tizen TVs and projectors",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="JellyBeam Team",
    author_email="jellybeam@example.com",
    url="https://github.com/jellybeam/jellybeam",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GPL License",
        "Operating System :: POSIX :: Linux",
        "Environment :: X11 Applications :: GTK",
    ],
    python_requires=">=3.8",
    install_requires=[
        "PyGObject>=3.40.0",
        "cryptography>=3.4.0",
        "requests>=2.25.0",
        "netifaces>=0.11.0",
    ],
    entry_points={
        "console_scripts": [
            "jellybeam=main:main",
        ],
    },
    data_files=[
        ("share/applications", ["data/com.github.jellybeam.desktop"]),
        (
            "share/icons/hicolor/48x48/apps",
            ["data/icons/48x48/com.github.jellybeam.png"],
        ),
        (
            "share/icons/hicolor/64x64/apps",
            ["data/icons/64x64/com.github.jellybeam.png"],
        ),
        (
            "share/icons/hicolor/128x128/apps",
            ["data/icons/128x128/com.github.jellybeam.png"],
        ),
    ],
)
