#!/usr/bin/env python
"""
This tool takes a MySQL dump of the Robinhood ``entries`` table and generates a
per-inode-type size histogram directly.  It also optionally dumps the raw
collection of (inode type, inode size) tuples for every inode in the entries
table into a CSV file.
"""

import os
import csv
import sys
import math
import argparse
import collections

import dask
import dask.bag
import dask.config
import numpy
import pandas

# allow large content in the dump
csv.field_size_limit(sys.maxsize)

_DEFAULT_BINS = [0] + [2**x for x in range(60)]

ENTRIES_COLS = collections.OrderedDict()
ENTRIES_COLS['id'] = str
ENTRIES_COLS['uid'] = numpy.int64
ENTRIES_COLS['gid'] = numpy.int64
ENTRIES_COLS['size'] = numpy.int64
ENTRIES_COLS['blocks'] = numpy.int64
ENTRIES_COLS['creation_time'] = numpy.int64
ENTRIES_COLS['last_access'] = numpy.int64
ENTRIES_COLS['last_mod'] = numpy.int64
ENTRIES_COLS['last_mdchange'] = numpy.int64
ENTRIES_COLS['type'] = str
ENTRIES_COLS['mode'] = numpy.int64
ENTRIES_COLS['nlink'] = numpy.int64
ENTRIES_COLS['md_update'] = numpy.int64
ENTRIES_COLS['invalid'] = numpy.int64
ENTRIES_COLS['fileclass'] = str
ENTRIES_COLS['class_update'] = str

def parse_values(line):
    """
    Given a file handle and the raw values from a MySQL INSERT statement, write
    the equivalent CSV to the file.

    Parts of this function fall under the following license:
    
    The MIT License (MIT)
    
    Copyright (c) 2014 James Mishra
    
    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:
    
    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.
    
    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
    """
    return_rows = []

    if not line.startswith('INSERT INTO'):
        return return_rows

    values = line.partition('` VALUES ')[2]
    if not values or values[0] != '(':
        return return_rows

    reader = csv.reader(
        [values],
        delimiter=',',
        doublequote=False,
        escapechar='\\',
        quotechar="'",
        strict=True)

    latest_row = []
    for reader_row in reader:
        for column in reader_row:
            # If our current string is empty...
            if len(column) == 0 or column == 'NULL':
                latest_row.append(chr(0))
                continue
            # If our string starts with an open paren
            if column[0] == "(":
                # Assume that this column does not begin
                # a new row.
                new_row = False
                # If we've been filling out a row
                if len(latest_row) > 0:
                    # Check if the previous entry ended in
                    # a close paren. If so, the row we've
                    # been filling out has been COMPLETED
                    # as:
                    #    1) the previous entry ended in a )
                    #    2) the current entry starts with a (
                    if latest_row[-1][-1] == ")":
                        # Remove the close paren.
                        latest_row[-1] = latest_row[-1][:-1]
                        new_row = True
                # If we've found a new row, write it out
                # and begin our new one
                if new_row:
                    return_rows.append({list(ENTRIES_COLS.keys())[i]: latest_row[i] for i in range(len(latest_row))})
                    latest_row = []
                # If we're beginning a new row, eliminate the
                # opening parentheses.
                if len(latest_row) == 0:
                    column = column[1:]
            # Add our column to the row we're working on.
            latest_row.append(column)
        # At the end of an INSERT statement, we'll
        # have the semicolon.
        # Make sure to remove the semicolon and
        # the close paren.
        if latest_row[-1][-2:] == ");":
            latest_row[-1] = latest_row[-1][:-2]
            return_rows.append({list(ENTRIES_COLS.keys())[i]: latest_row[i] for i in range(len(latest_row))})

    return return_rows

def bin_inode_size(size):
    """Converts a size into a histogram bin index
    """
    if size == 0:
        return 0
    return 1 + math.ceil(math.log2(size))

def bin_inode_size_inv(index):
    """Converts a histogram bin index back into a size
    """
    if index == 0:
        return 0
    return 2**(index - 1)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('sqldump', type=str,
                        help='Path to Robinhood MySQL database dump file')
    parser.add_argument('-b', '--blocksize', type=str, default='128MiB',
                        help='Block size for CSV ingest; passed to dask.bag.read_text (default: 128MiB)')
    parser.add_argument('--save-csv', type=str, default=None,
                        help="Path to which full list of (type, size) entries should be saved as CSV (default: do not save)")
    parser.add_argument('--dask-scheduler', type=str, default='processes',
                        help="Dask scheduler to use (threads, processes, or single-threaded; default: processes)")
    parser.add_argument('-o', '--output', type=str, default='histogram.csv',
                        help="Path to CSV file in which inode size histograms should be saved (default: histogram.csv)")
    args = parser.parse_args(argv)

    bag = dask.bag.read_text(args.sqldump, blocksize=args.blocksize).map(parse_values).flatten().map(lambda x: {k: x[k] for k in ('size', 'type')})
    df = bag.to_dataframe(meta={'size': numpy.int64, 'type': str})

    if args.save_csv:
        with dask.config.set(scheduler=args.dask_scheduler):
            df.to_csv(args.save_csv, index=False, single_file=True)
        print("Saved full inode size and type list to %s" % args.save_csv)

    df['bin'] = df['size'].map(bin_inode_size)

    histograms = df.groupby(['type', 'bin']).count()

    with dask.config.set(scheduler=args.dask_scheduler):
        histograms_df = histograms.compute().unstack('type')

    histograms_df.columns = histograms_df.columns.droplevel()
    max_idx = max(histograms_df.index.values)
    new_index = range(0, max_idx)
    histograms_df = histograms_df.reindex(new_index).fillna(0).astype(numpy.int64)
    histograms_df.index = [bin_inode_size_inv(x) for x in histograms_df.index.values]
    histograms_df.index.name = 'size'
    histograms_df.to_csv(args.output)
    print("Saved the following histograms to %s:" % args.output)
    print(histograms_df)

if __name__ == "__main__":
    main()
