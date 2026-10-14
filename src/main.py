"""Check the Python version and core dependencies."""

import platform

import numpy
import pandas
import requests


def main() -> None:
    print(f"Python version: {platform.python_version()}")
    print(f"requests version: {requests.__version__}")
    print(f"pandas version: {pandas.__version__}")
    print(f"numpy version: {numpy.__version__}")

    if platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("This project requires Python 3.12")

    print("Environment OK")


if __name__ == "__main__":
    main()
