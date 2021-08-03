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
    
    today = datetime.date.today()
    closed = 0
    opened = 0
    age = 7
    for case in cases:
        if case["case_status"] == "Closed":
            closed_date = datetime.datetime.strptime(case["case_lastModifiedDate"], '%Y-%m-%dT%H:%M:%SZ').date()
            if (today - closed_date).days < age:
                print("%s case closed on %s" % (case["case_number"], closed_date))
                closed += 1
        else:
            opened_date = datetime.datetime.strptime(case["case_createdDate"], '%Y-%m-%dT%H:%M:%SZ').date()
            if (today - opened_date).days < age:
                print("%s case opened on %s" % (case["case_number"], opened_date))
                opened += 1
    
    print("Closed cases in the past %s days: %s" % (age, closed))
    print("Opened cases in the past %s days: %s" % (age, opened))
            



if __name__ == '__main__':
    main()

