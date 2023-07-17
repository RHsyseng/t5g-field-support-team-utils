#! /usr/bin/python -W ignore

"""
Checks how many cases have been opened and closed in the last week
"""
import datetime
import os
import sys

import requests


def case_report(api_url, case_tag):
    """
    Checks for newly opened and closed cases for a given tag
    """
    cases = requests.get("{}/api/cases/{}".format(api_url, case_tag))
    if cases.status_code == 200:
        cases = cases.json()
    else:
        print("could not retrieve cases: {}".format(cases.status_code))
        sys.exit(1)

    today = datetime.date.today()
    age = 7

    closed_cases = {
        c: d
        for (c, d) in cases.items()
        if d["status"] == "Closed"
        and (
            today
            - datetime.datetime.strptime(d["last_update"], "%Y-%m-%dT%H:%M:%SZ").date()
        ).days
        < age
    }

    opened_cases = {
        c: d
        for (c, d) in cases.items()
        if d["status"] != "Closed"
        and (
            today
            - datetime.datetime.strptime(d["createdate"], "%Y-%m-%dT%H:%M:%SZ").date()
        ).days
        < age
    }

    print("{} cases closed in the past {} days:".format(len(closed_cases), age))
    for case in closed_cases:
        print("{}: {}".format(case, closed_cases[case]["problem"]))
    print("{} cases opened in the past {} days:".format(len(opened_cases), age))
    for case in opened_cases:
        print("{}: {}".format(case, opened_cases[case]["problem"]))


def main():
    """
    sets some things and then runs check_cases
    """
    api_url = os.environ.get("T5G_API")
    if api_url is None:
        print("No API URL specified. Please export T5G_API=<host> and try again")
        sys.exit(1)

    if len(sys.argv) == 2:
        case_tag = sys.argv[1]
    else:
        sys.exit("no case tag specified")
    print(
        "searching {} for newly opened and closed cases ({})".format(api_url, case_tag)
    )
    if case_tag in ["cnv", "telco5g"]:
        case_report(api_url, case_tag)
    else:
        sys.exit("invalid case tag specified: {}".format(case_tag))


if __name__ == "__main__":
    main()
