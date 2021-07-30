#! /usr/bin/python -W ignore
# #! /usr/bin/python -W ignore

'''
This script takes a configuration file name as its only argument.
Not passing a configuration file as an option will cause the script
to use its default settings and any environmental settings.

Setting set in the environment override the ones in the configuration file.
'''

import libtelco5g
import sys
import os
import pprint
import datetime
import re

def main():
    
    dpp = pprint.PrettyPrinter(indent=2)

    # Set the default configuration values
    cfg = libtelco5g.set_defaults()

     # Override the defaults with the setting from the configuration file
    if len(sys.argv) > 1:
        if os.path.isfile(sys.argv[1]):
            tfcfg = libtelco5g.read_config(sys.argv[1])
            for key in tfcfg:
                cfg[key] = tfcfg[key]
        else:
            print("File", sys.argv[1], "does not exist")
            exit(1)

    # Override the defaults and configuration file settings 
    # with any environmental settings
    trcfg = libtelco5g.read_env_config(cfg.keys())
    for key in trcfg:
        cfg[key] = trcfg[key]

    # Fix some of the settings so they are easier to use
    cfg['labels'] = cfg['labels'].split(',')

    if cfg['debug'].lower() == 'true':
        cfg['debug'] = True
    else:
        cfg['debug'] = False

    token=libtelco5g.get_token(cfg['offline_token'])
    cases=libtelco5g.get_cases_json(token,cfg['query'],cfg['fields'])
    interval=7
    new_cases=0
    print("new cases opened in the last %d days:" % interval)
    for case in sorted(cases, key = lambda i: i['case_severity']):
        create_date = datetime.datetime.strptime(case['case_createdDate'], '%Y-%m-%dT%H:%M:%SZ')
        time_diff = datetime.datetime.now() - create_date
        if time_diff.days < 7:
            new_cases += 1
            severity = re.sub('\(|\)| |[0-9]', '', case['case_severity'])
            print("https://access.redhat.com/support/cases/#/case/%s\t%s\t%s" % (case['case_number'], severity, case['case_summary']))
    print("%d cases opened in the last %d days" % (new_cases, interval))


        
    
if __name__ == '__main__':
    main()

