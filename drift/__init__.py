import os


def read_version():
    directory = os.path.dirname(__file__)
    with open(os.path.join(directory, "VERSION"), "r") as version_file:
        version = version_file.readline().strip()
        return version


__version__ = read_version()
