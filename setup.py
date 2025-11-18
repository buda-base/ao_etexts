from setuptools import setup, find_packages
from bdrc_etext_sync import __version__

setup(
    name="bdrc_etext_sync",
    version=__version__,
    packages=find_packages(),
    package_data={
        "bdrc_etext_sync.schemas": ["*.rng"],
    },
    install_requires=[
        "lxml",
    ],
    entry_points={
        "console_scripts": [
            "bdrc-etext-sync=bdrc_etext_sync.bdrc_etext_sync:main",
        ],
    },
)