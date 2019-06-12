#!/usr/bin/env python
"""
Generates one or more histograms of inode, file, and directory sizes from a
Robinhood database dump.

At present, requires that the Robinhood database be dumped out as SQLite to
match the operating environment at NERSC.  However it should be trivial to
adapt this to work directly against the Robinhood database.

Generate the file size distribution as

    histogram.py cscratch_20181109.sqlite

Alternatively if you have a `_sizebytype.sqlite` database from the
makesizetables.py tool, you can also use this tool to generate histograms of
each inode type:

    ./histogram.py -t files,dirs,symlinks,blks,chrs,fifos,socks cscratch_20181109_sizebytype.sqlite

"""

import argparse
import sqlite3
import pandas

_DEFAULT_BINS = [0] + [2**x for x in range(60)]

QUERY = """
SELECT
    COUNT(%(table)s.%(column)s)
FROM
    %(table)s
WHERE
    %(table)s.%(column)s > ?
AND %(table)s.%(column)s <= ?
    """

class FilesizeHistogram(object):
    def __init__(self, database, table='entries', column='size', bins=_DEFAULT_BINS):
        """Create a histogram of file size distribution
        Args:
            database (sqlite3.Connection or str): Either an existing SQLite3
                connection handle or a path to an SQLite database to open
            table (str): Table to query
            column (str): Column containing the inode size to be binned
            bins (list of int): The bins into which file sizes should be
                categorized
        """

        if isinstance(database, str):
            database = sqlite3.connect(database)

        self.cumul = None
        cursor = database.cursor()
        self.table = table

        maxsizes = []
        filect = []
        for maxsize in bins:
            cursor.execute(QUERY % {'table': table, 'column': column},
                           ("-1" if not maxsizes else str(maxsizes[-1]),
                            str(maxsize)))
            rows = cursor.fetchall()
            assert len(rows) == 1 and len(rows[-1]) == 1

            maxsizes.append(maxsize)
            filect.append(rows[-1][-1])

        assert len(maxsizes) == len(filect)

        self.data = []
        for idx, _ in enumerate(maxsizes):
            self.data.append((maxsizes[idx], filect[idx]))

    def __repr__(self):
        output = ""
        for histbin in self.data:
            output += "%d,%d\n" % histbin
        return output

    def _get_col_name(self):
        return "num_%s" % ('inodes' if self.table == 'entries' else self.table)

    def to_dataframe(self):
        dataframe = pandas.DataFrame(data=[x[1] for x in self.data],
                                     index=[x[0] for x in self.data],
                                     columns=[self._get_col_name()])
        dataframe.index.name = "bin_size"
        return dataframe

    def to_series(self):
        series = pandas.Series(data=[x[1] for x in self.data],
                               index=[x[0] for x in self.data],
                               name=self._get_col_name())
        series.index.name = "bin_size"
        return series

def histogram_dataframe(conn, tables, column='size'):
    """Creates inode size distributions of all inode types

    Args:
        conn (sqlite3.Connection): SQLite database connection to which queries
            should be issued
        tables (list of str): List of inode type tables for which histograms
            should be calculated
        column (str): Column containing the inode size to be binned

    Returns:
        pandas.DataFrame: Dataframe, indexed by inode size, containing inode
            size distributions of each specified inode type
    """
    series = []
    for table in tables:
        series.append(FilesizeHistogram(conn, table=table).to_series())
    return pandas.concat(series, axis=1)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--table', type=str, default='entries', help="Table to query (default: entries)")
    parser.add_argument('-c', '--column', type=str, default='size', help="Column to aggregate into histogram (default: size)")
    parser.add_argument('database', type=str, help="Path to database file")
    args = parser.parse_args(argv)

    conn = sqlite3.connect(args.database)

    if ',' in args.table:
        tables = args.table.split(',')
        dataframe = histogram_dataframe(conn, tables, column=args.column)
    else:
        dataframe = FilesizeHistogram(conn,
                                      table=args.table,
                                      column=args.column).to_dataframe()

    print(dataframe.to_csv(header=True))

if __name__ == "__main__":
    main()
