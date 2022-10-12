#! /usr/bin/python -W ignore

'''
This script takes a configuration file name as its only argument.
Not passing a configuration file as an option will cause the script
to use its default settings and any environmental settings.

Setting set in the environment override the ones in the configuration file.
'''


#import t5gweb.utils
import sys
import os
import getpass
import pprint
import json
from t5gweb.libtelco5g import (
    jira_connection,
    get_project_id,
    get_component_id,
    get_board_id,
    get_latest_sprint,
    get_sprint_summary
)
from t5gweb.utils import (
    set_defaults,
    read_config,
    read_env_config
)

def main():
    print('Generating sprint summary')

    cfg = set_defaults()
    dpp = pprint.PrettyPrinter(indent=2)

    # Override the defaults with the setting from the configuration file
    if len(sys.argv) > 1:
        if os.path.isfile(sys.argv[1]):
            tfcfg = read_config(sys.argv[1])
            for key in tfcfg:
                cfg[key] = tfcfg[key]
        else:
            print("File", sys.argv[1], "does not exist")
            exit(1)

    # Override the defaults and configuration file settings 
    # with any environmental settings
    trcfg = read_env_config(cfg.keys())
    for key in trcfg:
        cfg[key] = trcfg[key]

    # Fix some of the settings so they are easier to use
    cfg['labels'] = cfg['labels'].split(',')

    if cfg['debug'].lower() == 'true':
        cfg['debug'] = True
    else:
        cfg['debug'] = False
    
    cfg['team'] = json.loads(cfg['team'])

    # Check for the Jira PAT
    if len(cfg['password']) <= 0:
        if sys.stdin.isatty():
            cfg['password'] = getpass.getpass('Enter the Jira PAT: ')
        else:
            cfg['password'] = sys.stdin.readline().rstrip()

    print('Connecting to Jira instance')

    conn = jira_connection(cfg)
    
    if cfg['debug']:
        print('\nDEBUG: Connection')
        dpp.pprint(vars(conn))
    
    print('\nFetching ID for project:', cfg['project'])
    project = get_project_id(conn, cfg['project'])
    print('    Id:', project.id)

    if cfg['debug']:
        print('\nDEBUG: Project')
        dpp.pprint(vars(project))

    print('\nFetching ID for component:', cfg['component'])
    component = get_component_id(conn, project.id, cfg['component'])
    print('    Id:', component.id)

    if cfg['debug']:
        print('\nDEBUG: Component')
        dpp.pprint(vars(component))

    print('\nFetching ID for board:', cfg['board'])
    board = get_board_id(conn, cfg['board'])
    print('    Id:', board.id)

    if cfg['debug']:
        print('\nDEBUG: Board')
        dpp.pprint(vars(board))

    print('\nFetching latest sprint for board:', cfg['board'])
    sprint = get_latest_sprint(conn, board.id, cfg['sprintname'])
    print('    Latest:', sprint)

    if cfg['debug']:
        print('\nDEBUG: Sprint')
        dpp.pprint(vars(sprint))
    
    
    print('\nFetching sprint summary')
    sprint_summary = get_sprint_summary(conn, board.id, cfg['sprintname'], cfg['team'])


   
if __name__ == '__main__':
    main()
