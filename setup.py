from setuptools import setup, find_packages

setup(
    name="bdrc_etext_sync",
    version="0.1.0",
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