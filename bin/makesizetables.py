#!/usr/bin/env python
"""Create inode type-specific size tables

Breaks a table containing inode types and sizes into type-specific tables of
sizes.  Usage:

    ./makesizetables.py -v -f cscratch_20181109.sqlite cscratch_20181109_sizebytype.sqlite

where

* -v enables debugging messages (optional)
* -f disables journaling, synchronous writes, and locking
* cscratch_20181109.sqlite is the existing input SQLite database with an
  _entries_ table
* cscratch_20181109_sizebytype.sqlite is the SQLite database to create and
  populate with the demultiplexed output

This script does the equivalent of

    sqlite> .open "cscratch_20181109.sqlite" as main;
    sqlite> attach database "cscratch_20181109_sizebytype.sqlite" as sizes;
    sqlite> pragma journal_mode=off; pragma synchronous=off; pragma locking_mode=exclusive;
    sqlite> CREATE TABLE sizes.files (size integer);
    sqlite> INSERT INTO sizes.files(size) SELECT size FROM main.entries WHERE entries.type == "file";
    sqlite> CREATE INDEX sizes.file_size_idx ON files (size)
    ...
    sqlite> CREATE TABLE sizes.dirs (size integer);
    sqlite> INSERT INTO sizes.dirs(size) SELECT size FROM main.entries WHERE entries.type == "dir";
    sqlite> CREATE INDEX sizes.dir_size_idx ON dirs (size)
    ...

The script works on _entries_ tables that have either the Lustre/Robinhood
or GPFS/mmapplypolicy schemata.  For speed, it's probably a good idea to
create indices on the _entries.type_ column (Lustre) or _entries.mode_
column (GPFS).
"""

import sqlite3
import argparse

VERBOSE = False

# Maps type-specific table names (key) to character prefix of the 'mode' field
# (value) in the output of mmapplypolicy
GPFS_INODE_MAP = {
    "blks": "b",
    "chrs": "c",
    "dirs": "d",
    "fifos": "p",
    "files": "-",
    "socks": "s",
    "symlinks": "l",
}

LUSTRE_INODE_TYPES = [
    'blk',
    'chr',
    'dir',
    'fifo',
    'file',
    'sock',
    'symlink',
]

def vprint(string):
    """Prints message if verbose is enabled"""
    if VERBOSE:
        print(string)

def make_size_tables(conn, output_db, schema_type=None, fast=False):
    """Create type-specific tables

    Args:
        conn (sqlite3.Connection): SQLite database connection to a database
            containing an 'entries' table
        output_db (str): Name of database in which type-specific tables should
            be populated
        schema_type (str, Optional): Either "gpfs" or "lustre" to indicate the
            schema of the input database's 'entries' table.  If None,
            autodetect.
        fast (bool): If true, disable journaling, synchronous commits, and
            locking
    """

    if not schema_type:
        schema_type = infer_table_fstype(conn)
        vprint("Inferred schema: %s" % schema_type)

    if schema_type.lower() == "gpfs" or schema_type[0] in 'gG':
        make_size_tables_func = _make_size_tables_gpfs
    elif schema_type.lower() == "lustre" or schema_type[0] in 'lL':
        make_size_tables_func = _make_size_tables_lustre
    else:
        raise RuntimeError("Unknown schema for entries table")

    cursor = conn.cursor()
    cursor.execute("ATTACH DATABASE '%s' as outputdb" % output_db)

    if fast:
        cursor.execute("PRAGMA journal_mode=off")
        cursor.execute("PRAGMA synchronous=off")
        cursor.execute("PRAGMA locking_mode=exclusive")

    cursor.close()
    make_size_tables_func(conn)

def _make_size_tables_gpfs(conn):
    """Creates type-specific tables for GPFS

    Args:
        conn (sqlite3.Connection): SQLite database connection to a database
            containing an 'entries' table that uses the mmapplypolicy output's
            schema (i.e., encodes inode type in the first character of the
            'mode' column).  Should already have an output database (named
            'outputdb') attached.
    """

    cursor = conn.cursor()
    for table_name, mode_prefix in GPFS_INODE_MAP.items():
        vprint("Demultiplexing %s (symbol: %s)" % (table_name, mode_prefix))
        cursor.execute("CREATE TABLE outputdb.%s (size integer)" % table_name)
        vprint("  Created table '%s'" % table_name)
        vprint("  Executing:")
        vprint("    INSERT INTO outputdb.%s SELECT size FROM main.entries WHERE entries.mode LIKE ?" % table_name)
        vprint("  with parameter:")
        vprint("    %s" % ("%s%%" % mode_prefix))
        cursor.execute(
            ("INSERT INTO outputdb.%s SELECT size FROM main.entries WHERE entries.mode LIKE ?" % table_name),
            (("%s%%" % mode_prefix),))
        vprint("Creating index %s_size_idx for outputdb.%s" % (table_name[:-1], table_name))
        cursor.execute("CREATE INDEX outputdb.%s_size_idx ON %s (size)" % (table_name[:-1], table_name))

def _make_size_tables_lustre(conn):
    """Creates type-specific tables for Lustre

    Args:
        conn (sqlite3.Connection): SQLite database connection to a database
            containing an 'entries' table that uses the Robinhood output's
            schema (e.g., encodes inode type in the 'type' column).  Should
            already have an output database (named 'outputdb') attached.
    """

    cursor = conn.cursor()
    for inode_type in LUSTRE_INODE_TYPES:
        table_name = inode_type + "s"
        vprint("Demultiplexing %s" % table_name)
        cursor.execute("CREATE TABLE outputdb.%s (size integer)" % table_name)
        vprint("  Created table '%s'" % table_name)
        vprint("  Executing:")
        vprint("    INSERT INTO outputdb.%s SELECT size FROM main.entries WHERE entries.type = ?" % table_name)
        vprint("  with parameter:")
        vprint("    %s" % inode_type)
        cursor.execute(
            ("INSERT INTO outputdb.%s SELECT size FROM main.entries WHERE entries.type = ?" % table_name),
            (inode_type,))
        vprint("Creating index %s_size_idx for outputdb.%s" % (table_name[:-1], table_name))
        cursor.execute("CREATE INDEX outputdb.%s_size_idx ON %s (size)" % (table_name[:-1], table_name))

def infer_table_fstype(conn):
    """Determines if a database encodes GPFS or Lustre data

    Args:
        conn (sqlite3.Connection): SQLite database connection to a database
            containing an 'entries' table

    Returns:
        str or None: Either 'gpfs' or 'lustre' if conn's entries table is
            successfully identified, or None if no relevant columns are found.
    """
    columns = []
    cursor = conn.cursor()
    for row in cursor.execute("PRAGMA table_info('entries')").fetchall():
        columns.append(row[1])

    if 'snapshot' in columns:
        return 'gpfs'
    elif 'type' in columns:
        return 'lustre'

    return None

def main(argv=None):
    """Provides CLI wrapper for make_size_tables_*
    """
    global VERBOSE
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=str, help="database containing indexed entries table")
    parser.add_argument('output', type=str, help="database to output demultiplexed inode sizes")
    parser.add_argument('--fstype', type=str, default=None, help="file system of --input arg; either 'lustre' or 'gpfs' (default: autodetect)")
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help="verbose output")
    parser.add_argument('-f', '--fast', action='store_true', default=False, help="disable SQLite journaling/synchronization")
    args = parser.parse_args(argv)

    if args.verbose:
        VERBOSE = True

    conn = sqlite3.connect(args.input) # attached with default name 'main'

    make_size_tables(conn=conn,
                     output_db=args.output,
                     schema_type=args.fstype,
                     fast=args.fast)

    conn.close()

if __name__ == "__main__":
    main()
