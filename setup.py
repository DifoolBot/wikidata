# wikidata/setup.py
from setuptools import setup, find_packages

setup(
    name='wikidata-projects',
    version='0.1',
    packages=find_packages(where='projects'),
    package_dir={'': 'projects'},
)