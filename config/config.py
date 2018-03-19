#!/usr/bin/env python

import re
import os

DATA = [
    
    {
        'project'   : re.compile(r'flowb'),
        'branch'    : re.compile(r'.*'),    # Any
        'flow'      : re.compile(r'.*'),    # Any
        'flow_file' : "{}/flowb/flows/default.json".format(os.environ['HOME']),
    },

    # Catch all - Results in an ERROR from the tool
    {
        'project'   : re.compile(r'.*'),
        'branch'    : re.compile(r'.*'),
        'flow'      : re.compile(r'.*'),
        'flow_file' : None,
    },

]
