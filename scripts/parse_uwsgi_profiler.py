#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2016, Florent Thiery
# Run uwsgi with '--profiler pycall' and run the parser on uwsgi.log

import sys
from collections import Counter

from click import echo

HEADER = '##############'
PATTERN = "[uWSGI Python profiler"
TOP = 20


def main():

    with open(sys.argv[1]) as f:
        echo('Reading file')
        d = f.read().strip()

    calls = list()
    modules = list()
    profiler_name = 'pyline'

    echo('Splitting lines')
    lines = d.split('\n')
    echo('Parsing lines')
    for l in lines:
        if l.startswith(PATTERN):
            if ' CALL: ' in l:
                # pycall
                profiler_name = 'pycall'
                module = l.split(' CALL: ')[1].split(' (')[0]
                call = l.split(' ')[-5]
            else:
                # pyline
                module = l.split(' file ')[1].split(' line ')[0]
                call = l.split(' ')[-2]
            calls.append("%s > %s" % (module, call))
            modules.append(module)

    def count(items, items_name='calls'):
        if len(items) != 0:
            echo('Counting %s' % items_name)
            counter = Counter(items)
            echo('\n%s\nTop %s %s\n%s\n' % (HEADER, TOP, items_name, HEADER))
            items_count = len(items)
            top = counter.most_common(TOP)
            for t in top:
                percent = int(round(100*t[1]/items_count))
                if percent > 0:
                    echo("{} {}%".format(t[0], percent))

    echo('uWSGI python profiler %s results' % profiler_name)
    count(calls, 'calls')
    count(modules, 'modules')


if __name__ == "__main__":
    main()
