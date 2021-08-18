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
import jira
import json

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
    if cfg.get('team') != None:
        cfg['team'] = json.loads(cfg['team'])
    else:
        print("Please provide a team variable and rerun the script in order to proceed.")
        exit (1)
    if cfg['debug'].lower() == 'true':
        cfg['debug'] = True
    else:
        cfg['debug'] = False

    # Check for the password
    if len(cfg['password']) <= 0:
        if sys.stdin.isatty():
            cfg['password'] = getpass.getpass('Enter the Jira password: ')
        else:
            cfg['password'] = sys.stdin.readline().rstrip()

    #cases = libtelco5g.parse_spreadsheet(cfg['sheet_id'], cfg['range_name'])
    
    token=libtelco5g.get_token(cfg['offline_token'])
    cases_json=libtelco5g.get_cases_json(token,cfg['query'],cfg['fields'])
    cases=libtelco5g.get_cases(cases_json)
    
    if cfg['debug']:
        print('\nDEBUG: Cases not closed in the spreadsheet')
        dpp.pprint(len(cases))
        dpp.pprint(cases)
    
    print('Connecting to Jira instance')
    options = { 'server': cfg['server'] }

    try:
        conn = libtelco5g.jira_connection(options, cfg)
    except jira.exceptions as e:
        if e.status_code ==401:
            print("Login to JIRA failed. Check your username and password")
            exit (1)

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
    print ('\nFetching sprint name for board:', cfg['sprintname'])
    sprint = libtelco5g.get_latest_sprint(conn, board.id, cfg['sprintname'])
    print('    Latest:', sprint)

    if cfg['debug']:
        print('\nDEBUG: Sprint')
        dpp.pprint(vars(sprint))
    
    print('\nFetching cards in latest sprint')
    existing_cards = libtelco5g.get_cards(conn, sprint.id)
    print('    Cards:', len(existing_cards))

    if cfg['debug']:
        print('\nDEBUG: Existing Cards')
        dpp.pprint(existing_cards)

    print('\nDetermining which cases need cards created')
    to_create = libtelco5g.parse_cases(conn, cases, existing_cards, cfg['debug'])
    print('    Cards needed:', len(to_create))

    number_of_cards=len(to_create)
    if cfg['debug']:
        print('\nDEBUG: Cards to Create')
        dpp.pprint(to_create)
    print("to create: %d" % (number_of_cards))
    if number_of_cards >= 10:
        email_content = ["Warning: more than 10 cases will be created, so refusing to proceed. Please check log output.\n"]
        cfg['to'] = cfg['alert_to']
        cfg['subject'] = 'High New Case Count Detected'
        libtelco5g.notify(cfg, email_content)
        if cfg['slack_token'] and cfg['slack_channel']: 
            libtelco5g.slack_notify(cfg, email_content)
        exit(0)

    email_body = libtelco5g.create_cases(conn, cfg, sprint.id, cases, to_create, cfg['team'], cfg['card_action'])
    if email_body:
        print('\nNotifying the team about the new Jira cards')
        libtelco5g.notify(cfg, email_body)
        if cfg['slack_token'] and cfg['slack_channel']:
            libtelco5g.slack_notify(cfg, email_body)
        else:
            print('no slack_token and/or slack_channel specified')


if __name__ == '__main__':
    main()

