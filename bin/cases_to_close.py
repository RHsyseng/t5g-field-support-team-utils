#! /usr/bin/python -W ignore
'''
This script hits the API to check for cases that are closed but the associated card is still open
'''
import os
import sys
import requests

def check_cases(api_url):
    '''
    Compare cases to cards for a given tag
    '''
    cases = requests.get("{}/api/cases".format(api_url))
    if cases.status_code == 200:
        closed_cases = {c: d for (c, d) in cases.json().items() if d['status'] == 'Closed'}
    else:
        print("could not retrieve cases: {}".format(cases.status_code))
        sys.exit(1)
    cards = requests.get("{}/api/cards".format(api_url))
    if cases.status_code == 200:
        open_cards = {c: d for (c, d) in cards.json().items() if d['card_status'] not in ('Done', 'Won\'t Fix / Obsolete')}
    else:
        print("could not retrieve cards: {}".format(cards.status_code))
        sys.exit(1)
    for card in open_cards:
        if open_cards[card]['case_number'] in closed_cases.keys():
            print("https://issues.redhat.com/browse/{} : {} ({})".format(
                card, open_cards[card]['case_number'], open_cards[card]['assignee']['displayName']))

def main():
    '''
    sets some things and then runs check_cases
    '''
    api_url = os.environ.get('DASH_API')
    if api_url is None:
        print('No API URL specified. Please export DASH_API=<host> and try again')
        sys.exit(1)

    print("searching {} for closed cases / open cards".format(api_url))
    check_cases(api_url)

if __name__ == '__main__':
    main()
