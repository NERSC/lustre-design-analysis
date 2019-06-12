#!/usr/bin/env bash
#
#  Removes output cells from a notebook
#

jupyter nbconvert --ClearOutputPreprocessor.enabled=True --inplace $@
