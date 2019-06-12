#!/usr/bin/env bash
#
#  This script takes an SQLite database containing a Lustre 'entries' and
#  'names' tables and creates:
#
#  1. a new "_dirdist.sqlite" database containing the parent inodes and how many
#     children each has
#  2. a "_dirdist_hist.csv" CSV file containing a histogram of this directory
#     size distribution
#
#  This script does not yet support data from GPFS.

set -e

orig_db=$1
if [ -z "$orig_db" ]; then
    echo "Syntax: $0 <original.db>" >&2
    exit 1
fi

dirdist_db="$(basename $orig_db .sqlite)_dirdist.sqlite"
if [ -f $dirdist_db ]; then
    echo "ERROR: $dirdist_db already exists" >&2
    exit 1
else
    echo "Creating $dirdist_db"
fi

sqlite3 $orig_db <<EOF
pragma journal_mode=off; pragma synchronous=off; pragma locking_mode=exclusive;
attach database "$dirdist_db" as dd;
CREATE TABLE dd.dirdist(parent_id TEXT, id TEXT, size INTEGER, type TEXT);
INSERT INTO dd.dirdist SELECT names.parent_id, entries.id, entries.size, entries.type FROM entries INNER JOIN names ON entries.id = names.id;
EOF

sqlite3 $dirdist_db <<EOF
CREATE TABLE child_counts (
    parent_id text,
    count integer
);
INSERT INTO child_counts 
    SELECT parent_id, count(id) FROM dirdist GROUP BY parent_id;
CREATE INDEX count_idx on child_counts (count);
EOF

csv_file=$(basename $dirdist_db .sqlite)_hist.csv
echo "Creating $csv_file"
$(dirname $(readlink -f ${BASH_SOURCE[0]}))/histogram.py -t child_counts -c count $dirdist_db | tee $csv_file 
