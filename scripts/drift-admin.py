#!C:\Python27\python.exe
from drift import management
import argparse, os, sys
sys.dont_write_bytecode = True

if __name__ == "__main__":
    path = os.path.dirname(__file__)
    sys.path.insert(0, path)
    management.execute_cmd()
