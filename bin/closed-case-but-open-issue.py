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
import getpass
import pprint

def main():
    print('Searching for duplicate cases')

    cfg = libtelco5g.set_defaults()
    dpp = pprint.PrettyPrinter(indent=2)


    user = None
    # Override the defaults with the setting from the configuration file
    if len(sys.argv) > 1:
        if os.path.isfile(sys.argv[1]):
            tfcfg = libtelco5g.read_config(sys.argv[1])
            for key in tfcfg:
                cfg[key] = tfcfg[key]
        else:
            print("File", sys.argv[1], "does not exist")
            exit(1)
    if len(sys.argv) > 2:
        user = sys.argv[2]
    

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

    # Check for the Jira PAT
    if len(cfg['password']) <= 0:
        if sys.stdin.isatty():
            cfg['password'] = getpass.getpass('Enter the Jira PAT: ')
        else:
            cfg['password'] = sys.stdin.readline().rstrip()

    print('Connecting to Jira instance')
    
    conn = libtelco5g.jira_connection(cfg)
    
    if cfg['debug']:
        print('\nDEBUG: Connection')
        dpp.pprint(vars(conn))
    
    print('\nFetching ID for project:', cfg['project'])
    project = libtelco5g.get_project_id(conn, cfg['project'])
    print('    Id:', project.id)

    if cfg['debug']:
        print('\nDEBUG: Project')
        dpp.pprint(vars(project))

    print('\nFetching ID for component:', cfg['component'])
    component = libtelco5g.get_component_id(conn, project.id, cfg['component'])
    print('    Id:', component.id)

    if cfg['debug']:
        print('\nDEBUG: Component')
        dpp.pprint(vars(component))

    print('\nFetching ID for board:', cfg['board'])
    board = libtelco5g.get_board_id(conn, cfg['board'])
    print('    Id:', board.id)

    if cfg['debug']:
        print('\nDEBUG: Board')
        dpp.pprint(vars(board))

    print('\nFetching latest sprint for board:', cfg['board'])
    sprint = libtelco5g.get_latest_sprint(conn, board.id, cfg['sprintname'])
    print('    Latest:', sprint)

    if cfg['debug']:
        print('\nDEBUG: Sprint')
        dpp.pprint(vars(sprint))
    
    print('\nFetching cards in latest sprint')
    existing_cards = libtelco5g.get_cards(conn, sprint.id, user=user, include_closed=False)
    print('    Cards:', len(existing_cards))

    if cfg['debug']:
        print('\nDEBUG: Existing Cards')
        dpp.pprint(existing_cards)

    for card in existing_cards:
        print(card)
    
    token=libtelco5g.get_token(cfg['offline_token'])
    cases_json=libtelco5g.get_cases_json(token,cfg['query'],cfg['fields'])
    cases=libtelco5g.get_cases(cases_json)
    libtelco5g.closed_cases(conn, cases, existing_cards, True)


   
if __name__ == '__main__':
    main()