#! /usr/bin/python -W ignore
'''
This script allows you to check whether certain users and support cases are watchers on the Red Hat Customer Portal.
Also allows you to add or delete users as watchers to the specified support cases

Requirements and Examples:

$ pip install -r requirements.txt
$ export REDHAT_API_TOKEN=<your_token> # Get your token https://access.redhat.com/management/api
$ watcher_case.py list --users rhn-support-jclaretm --case 03112577
$ watcher_case.py list -f file.json
$ watcher_case.py add --users rhn-support-jclaretm --case 03112577
$ watcher_case.py del --users rhn-support-jclaretm --case 03112577

'''
import os
import sys
import argparse
import requests
import json
from colorama import init, Fore
from datetime import datetime, timedelta

# Initialize colorama for colored output
init(autoreset=True)


class WatcherCase:
    def __init__(self):
        # Read environment variables for URL and TOKEN
        self.API_URL = os.getenv('REDHAT_API_URL', default="https://api.access.redhat.com/support")
        self.API_TOKEN = os.getenv('REDHAT_API_TOKEN')

        if self.API_TOKEN is None:
            print(Fore.RED + f"[ERROR] - API token not found. Please set the REDHAT_API_TOKEN environment variable.")
            sys.exit(1)

        self.headers = {'Authorization': 'Bearer ' + self.API_TOKEN}
        self.session = requests.Session()
        self.session.headers.update(self.headers)

        # Initialize the argparse parser
        self.init_parser()

        # Initialize the case cache
        self.case_cache = {}

    def init_parser(self):
        # Define subcommands and arguments using argparse
        self.parser = argparse.ArgumentParser(description='Script to check if given users and support cases are watchers on the Red Hat Customer Portal.')
        subparsers = self.parser.add_subparsers(dest='subcommand', required=True)

        # Help subcommand
        help_parser = subparsers.add_parser('help', help='Show help for subcommands')
        help_parser.add_argument('command', nargs='?', help='Subcommand to show help for')

        # List subcommand
        list_parser = subparsers.add_parser('list', help='List the given users and support cases as watchers')
        list_parser.add_argument('--users', '-u', nargs='+', help='List of user IDs to check')
        list_parser.add_argument('--cases', '-c', nargs='+', help='List of case IDs to check')
        list_parser.add_argument('-f', '--filename', help='Name of the input file with user and case IDs')

        # Add subcommand
        add_parser = subparsers.add_parser('add', help='Add the given users as watchers to the given support cases')
        add_parser.add_argument('--users', '-u', nargs='+', help='List of user IDs to add as watchers')
        add_parser.add_argument('--cases', '-c', nargs='+', help='List of case IDs to add the users as watchers to')
        add_parser.add_argument('-f', '--filename', help='Name of the input file with user and case IDs')

        # Del subcommand
        del_parser = subparsers.add_parser('del', help='Del the given users as watchers to the given support cases')
        del_parser.add_argument('--users', '-u', nargs='+', help='List of user IDs to delete as watchers')
        del_parser.add_argument('--cases', '-c', nargs='+', help='List of case IDs to delete the users as watchers to')
        del_parser.add_argument('-f', '--filename', help='Name of the input file with user and case IDs')

    def refresh_access_token(self):
        # Check if the access token is still valid
        if hasattr(self, 'expires_at') and datetime.now() < self.expires_at:
            return

        # Define the application credentials
        CLIENT_ID = "rhsm-api"
        REFRESH_TOKEN = os.environ.get('REDHAT_API_TOKEN')

        # Define the authorization URL
        AUTH_URL = "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token"

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {"grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": REFRESH_TOKEN}
        response = self.session.post(AUTH_URL, headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()
        self.API_TOKEN = token_data['access_token']
        # Cache the expiration time of the access token (5 minutes from now)
        self.expires_at = datetime.now() + timedelta(seconds=300)
        # print("[INFO] Refreshed access token.")
        self.headers = {'Authorization': 'Bearer ' + self.API_TOKEN}
        self.session.headers.update(self.headers)

    def get_watchers(self, case_id):
        # Check the case cache first
        if case_id in self.case_cache:
            return self.case_cache[case_id]

        # Make API request to get case details
        url = f"{self.API_URL}/v1/cases/{case_id}"
        response = self.session.get(url)
        response.raise_for_status()
        case_data = json.loads(response.text).get('notifiedUsers', [])
        # Extract the ssoUsername values
        sso_usernames = [user.get('ssoUsername', '') for user in case_data]
        # Add the sso_usernames to the case cache
        self.case_cache[case_id] = sso_usernames
        return sso_usernames

    def update_watchers(self, case_ids, user_ids, action):
        # Construct the payload for bulk update
        payload = {
            "user": [{"ssoUsername": user_id} for user_id in user_ids]
        }
        # Make API request to update case details
        for case_id in case_ids:
            url = f"{self.API_URL}/v1/cases/{case_id}/notifiedusers"
            if action == 'add':
                response = self.session.post(url, json=payload)
            elif action == 'del':
                for user_id in user_ids:
                    user_url = f"{url}/{user_id}"
                    response = self.session.delete(user_url)
            response.raise_for_status()

        return True

    def handle_watchers(self, args, action):

        # Check if the user has provided a filename or a list of user and case IDs
        if args.filename:
            # Read the input file with user and case IDs
            try:
                with open(args.filename, 'r') as f:
                    data = json.load(f)
                    users = data.get('users', [])
                    cases = data.get('cases', [])
            except FileNotFoundError:
                print(Fore.RED + f"[ERROR] - Input file '{args.filename}' not found.")
                sys.exit(1)
        else:
            users = args.users or []
            cases = args.cases or []

        if not users or not cases:
            print(Fore.RED + f"[ERROR] - Please provide a list of users and cases or a filename.")
            sys.exit(1)

        self.refresh_access_token()

        # Loop through each user and case ID and perform the action
        user_ids = set(users)
        case_ids = set(cases)
        for case_id in case_ids:
            sso_usernames = set(self.get_watchers(case_id))
            if action == 'list':
                # Check if any user is a watcher on the case
                for user_id in user_ids:
                    if user_id in sso_usernames:
                        print(Fore.GREEN + f'User {user_id} is a watcher on case {case_id}')
                    else:
                        print(Fore.RED + f'User {user_id} is not a watcher on case {case_id}')
            elif action == 'add':
                # Add the users as watchers to the case
                to_add = user_ids.difference(sso_usernames)
                if to_add:
                    result = self.update_watchers([case_id], to_add, 'add')
                    if result:
                        print(Fore.GREEN + f'Users {", ".join(to_add)} added as watchers to case {case_id}')
                else:
                    print(Fore.GREEN + f'Users {", ".join(user_ids)} already watchers on case {case_id}')
            elif action == 'del':
                # Remove the users as watchers from the case
                to_remove = sso_usernames.intersection(user_ids)
                if to_remove:
                    result = self.update_watchers([case_id], to_remove, 'del')
                    if result:
                        print(Fore.GREEN + f'Users {", ".join(to_remove)} deleted as watchers from case {case_id}')
                else:
                    print(Fore.GREEN + f'Users {", ".join(user_ids)} not watchers on case {case_id}')

    def main(self):
        args = self.parser.parse_args()
        if args.subcommand == 'help':
            self.parser.print_help()
        elif args.subcommand == 'list':
            self.handle_watchers(args, 'list')
        elif args.subcommand == 'add':
            self.handle_watchers(args, 'add')
        elif args.subcommand == 'del':
            self.handle_watchers(args, 'del')


if __name__ == '__main__':
    WatcherCase().main()
