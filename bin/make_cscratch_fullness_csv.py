#!/usr/bin/env python
"""Generates the file system fullness CSV file for the purpose of calculating
the required endurance for N9.
"""

import argparse
import datetime
import functools
import multiprocessing
import pandas
import tokio.tools.lfsstatus as lfsstatus

DEFAULT_OUTPUT_TEMPLATE = 'cscratch_fullness-%s_%s.csv'

def main(argv=None):
    """Entry point for the CLI interface
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--threads", type=int, default=1,
                        help="number of parallel threads")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="output file")
    parser.add_argument("filesystem",
                        help="logical file system name (e.g., cscratch)")
    parser.add_argument("start_date",
                        help="start date of interest, inclusive, in YYYY-MM-DD format")
    parser.add_argument("end_date",
                        help="end date of interest, exclusive, in YYYY-MM-DD format")
    args = parser.parse_args(argv)

    start_date = datetime.datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.datetime.strptime(args.end_date, "%Y-%m-%d")
    if end_date <= start_date:
        raise argparse.ArgumentTypeError('start_date must be less than end_date')

    # Figure out the dates we're going to examine
    this_date = start_date
    process_dates = []
    while this_date < end_date:
        process_dates.append(this_date)
        this_date += datetime.timedelta(days=1)

    results = []
    if args.threads == 1:
        for this_date in process_dates:
            print("Processing " + this_date.strftime("%Y-%m-%d"))
            results.append(lfsstatus.get_fullness(
                args.filesystem,
                this_date))
            this_date += datetime.timedelta(days=1)
    else:
        for result in multiprocessing.Pool(args.threads).imap(
                functools.partial(get_fullness, file_system=args.filesystem), process_dates):
            if result:
                results.append(result)

    dataframe = pandas.DataFrame.from_dict({a: b for a, b in zip([x.strftime("%Y-%m-%d %H:%M:%S") for x in process_dates], results)}, orient='index')
    dataframe.index.name = 'timestamp'

    if args.output is None:
        output_file = DEFAULT_OUTPUT_TEMPLATE % (
            start_date.strftime("%Y-%m-%d"),
            (end_date - datetime.timedelta(days=1)).strftime("%Y-%m-%d"))
    else:
        output_file = args.output
    dataframe.sort_index().to_csv(output_file, header=True)
    print("Wrote output to " + output_file)

def get_fullness(datetime_target, file_system):
    """Wraps lfsstatus.get_fullness with reordered parameters
    """
    print("Processing " + datetime_target.strftime("%Y-%m-%d"))
    try:
        return lfsstatus.get_fullness(datetime_target=datetime_target, file_system=file_system)
    except:
        return None

if __name__ == "__main__":
    main()
