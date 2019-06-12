#!/usr/bin/env python

import os
import sys

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

import fsanalysis.histogram

if __name__ == "__main__":
    fsanalysis.histogram.main(sys.argv)
