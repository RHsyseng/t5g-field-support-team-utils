import argparse
import datetime
import json
import re

from faker import Faker


def generate_fake_data(number_of_cases):
    """Generate fake data for use in development environments

    Args:
        number_of_cases (int): Amount of fake cases to generate

    Returns:
        dict: A dictionary containing fake cases, issues, bugs, and cards
    """
    fake = Faker(["en_US", "ja_JP", "es_ES", "ko_KR", "la"])
    Faker.seed(0)

    issues = {}
    bugs = {}
    cards = {}
    accounts = [fake.company() for _ in range(10)]
    engineers = [
        {
            "displayName": fake.name(),
            "key": fake.user_name(),
            "name": fake.user_name(),
        }
        for _ in range(5)
    ]
    cases = generate_fake_cases(fake, number_of_cases, accounts)
    for case_number, case_details in cases.items():
        if fake.boolean():
            # Generate fake issues for case
            private_keywords = generate_fake_private_keywords(fake)
            issues[case_number] = generate_fake_issues(fake, private_keywords)

        if fake.boolean():
            # Generate fake bugs for case
            bugs[case_number] = generate_fake_bugs(fake, case_number)

        # Generate fake card for case
        card = generate_fake_card(
            fake, engineers, bugs, issues, case_number, case_details
        )
        cards.update(card)
    data = {"issues": issues, "bugs": bugs, "cases": cases, "cards": cards}
    return data


def generate_fake_cases(fake, number_of_cases, accounts):
    """Generate fake portal cases for use in development environments

    Args:
        fake (faker.proxy.Faker): Faker object
        number_of_cases (int): Amount of fake cases to generate
        accounts (list): Fake companies to assign cases to

    Returns:
        dict: A dictionary that contains fake cases
    """
    cases = {}
    for _ in range(number_of_cases):
        create_date = (
            # 90% of cases "created" this decade, 10% "created" this week
            fake.date_time_this_decade().replace(microsecond=0).isoformat() + "Z"
            if fake.boolean(chance_of_getting_true=90)
            else fake.date_time_between("-7d").replace(microsecond=0).isoformat() + "Z"
        )
        entry = {
            str(fake.random_number(8)): {
                "account": fake.random_element(accounts),
                "createdate": create_date,
                "description": fake.paragraph(),
                # last_update must be after createdate
                "last_update": fake.date_time_between(
                    start_date=datetime.datetime.strptime(
                        create_date, "%Y-%m-%dT%H:%M:%SZ"
                    )
                )
                .replace(microsecond=0)
                .isoformat()
                + "Z",
                "owner": fake.name(),
                "problem": fake.sentence(),
                "product": f"{fake.word()} {fake.numerify('#.#')}",  # Ex: Word 4.5
                "severity": fake.random_element(
                    ["1 (Urgent)", "2 (High)", "3 (Normal)", "4 (Low)"]
                ),
                "status": fake.random_element(
                    ["Waiting on Red Hat", "Closed", "Waiting on Customer"]
                ),
            }
        }

        # Handle values that may not be present in case
        for case in entry:
            if fake.boolean():
                entry[case]["bug"] = str(fake.random_number(7))  # ex: 1234567
            if fake.boolean():
                # list of words that is any length from 0 to 3 inclusive
                entry[case]["tags"] = [
                    fake.word() for _ in range(fake.random_int(0, 3))
                ]
            if entry[case]["status"] == "Closed":
                # closeddate must be after the createdate
                entry[case]["closeddate"] = (
                    fake.date_time_between(
                        start_date=datetime.datetime.strptime(
                            entry[case]["createdate"], "%Y-%m-%dT%H:%M:%SZ"
                        )
                    )
                    .replace(microsecond=0)
                    .isoformat()
                    + "Z"
                )
        cases.update(entry)
    return cases


def generate_fake_private_keywords(fake):
    """Generate fake private_keywords for use in development environments

    Args:
        fake (faker.proxy.Faker): Faker object

    Returns:
        list | None: Fake private keywords or None
    """
    option = fake.random_element([1, 2, 3])

    if option == 1:
        return [fake.word(), f"Telco:Priority-{fake.random_int(1, 4)}"]
    elif option == 2:
        return [fake.word(), fake.word()]
    else:
        return None


def generate_fake_issues(fake, private_keywords):
    """Generate fake Jira issues for a specific portal case

    Args:
        fake (faker.proxy.Faker): Faker object
        private_keywords (list | None): Private keywords generated by
            generate_fake_private_keywords()

    Returns:
        list: Fake Jira issues for a specific case
    """
    case_issues = []
    for _ in range(fake.random_int(1, 5)):
        issue = {
            "assignee": fake.safe_email() if fake.boolean() else None,
            "fix_versions": (
                # ex: [Word-4.56] or ["---"] or None
                [f"{fake.word()}-{fake.numerify('#.##')}" if fake.boolean() else "---"]
                if fake.boolean()
                else None
            ),
            "id": fake.random_number(6),  # ex: 123456
            "jira_severity": (
                fake.random_element(
                    ["Critical", "Important", "Moderate", "Low", "Informational"]
                )
                if fake.boolean()
                else None
            ),
            "jira_type": (
                fake.random_element(["Feature Request", "Bug"])
                if fake.boolean()
                else None
            ),
            "priority": (
                fake.random_element(
                    ["Major", "Minor", "Normal", "Blocker", "Critical", "Undefined"]
                )
                if fake.boolean()
                else None
            ),
            "private_keywords": private_keywords,
            "qa_contact": fake.safe_email() if fake.boolean() else None,
            "status": fake.random_element(
                [
                    "New",
                    "ASSIGNED",
                    "POST",
                    "ON_QA",
                    "Verified",
                    "Release Pending",
                    "Closed",
                    "MODIFIED",
                ]
            ),
            "title": fake.sentence(),
            "updated": fake.date_time_this_decade().isoformat(),
            "url": f"https://{fake.safe_domain_name()}",
        }
        case_issues.append(issue)
    return case_issues


def generate_fake_bugs(fake, case):
    """Generate fake Bugzilla bugs for a specific case

    Args:
        fake (faker.proxy.Faker): Faker object
        case (str): ID of fake case generated earlier

    Returns:
        list: Fake Bugzilla bugs for a specific case
    """
    case_bugs = []
    for _ in range(fake.random_int(1, 5)):
        bugzilla_number = str(fake.random_number(6))

        bug = {
            "bugzillaLink": (
                f"https://{fake.safe_domain_name()}"
                f"/show_bug.cgi?id={bugzilla_number}"
            ),
            "bugzillaNumber": bugzilla_number,
            "caseNumber": case,
            "linkedAt": fake.date_time_this_decade().isoformat() + "Z",
            "status": fake.random_element(
                [
                    "POST",
                    "MODIFIED",
                    "ON_DEV",
                    "ON_QA",
                    "VERIFIED",
                    "RELEASE_PENDING",
                    "ASSIGNED",
                    "CLOSED",
                ]
            ),
            "summary": fake.sentence(),
            "target_release": [fake.numerify(text="#.#z") if fake.boolean else "---"],
            "assignee": fake.safe_email(),
            "last_change_time": fake.date_time_this_decade().isoformat(),
            "internal_whiteboard": fake.word(),
            "qa_contact": fake.safe_email(),
            "severity": fake.random_element(
                ["low", "medium", "high", "urgent", "unspecified"]
            ),
        }
        case_bugs.append(bug)
    return case_bugs


def generate_fake_card(fake, engineers, bugs, issues, case_number, case_details):
    """Generate fake T5G cards using previously generated fake data.

    Args:
        fake (faker.proxy.Faker): Faker object
        engineers (list): Pool of fakepod engineers to assign to card
        bugs (dict): All fake bugs that have been generated
        issues (dict): All fake Jira issues that have been generated
        case_number (int): ID of fake case to create card for
        case_details (dict): Details of fake case to create card for

    Returns:
        dict: Fake T5G Card intended to mimic production data
    """
    time_now = datetime.datetime.now(datetime.timezone.utc)

    card = {
        # ex: TEST-1234
        fake.bothify("????-####").upper(): {
            "account": case_details["account"],
            "assignee": (
                fake.random_element(engineers)
                if fake.boolean(chance_of_getting_true=95)
                else {"displayName": None, "key": None, "name": None}
            ),
            "bugzilla": bugs.get(case_number),
            "card_created": fake.date_time_this_decade().isoformat() + ".000+0000",
            "card_status": fake.random_element(
                [
                    "Eng Working",
                    "Backlog",
                    "Debugging",
                    "Backport",
                    "Ready To Close",
                    "Done",
                ]
            ),
            "case_created": case_details["createdate"],
            "case_days_open": (  # Calculate number of days since "createdate"
                time_now.replace(tzinfo=None)
                - datetime.datetime.strptime(
                    case_details["createdate"], "%Y-%m-%dT%H:%M:%SZ"
                )
            ).days,
            "case_number": case_number,
            "case_status": case_details["status"],
            # Convert last_update to correct format
            "case_updated_date": datetime.datetime.strftime(
                datetime.datetime.strptime(
                    case_details["last_update"], "%Y-%m-%dT%H:%M:%SZ"
                ),
                "%Y-%m-%d %H:%M",
            ),
            "comments": [
                (
                    fake.paragraph(),
                    fake.date_time_this_decade().isoformat() + "Z",
                )
                for _ in range(fake.random_int(0, 5))
            ],
            "contributor": (
                [
                    {
                        "displayName": fake.name(),
                        "key": fake.user_name(),
                        "name": fake.user_name(),
                    }
                    for _ in range(fake.random_int(0, 3))
                ]
            ),
            "crit_sit": fake.boolean(),
            "daily_telco": fake.boolean(),
            "description": case_details["description"],
            "escalated": fake.boolean(),
            "escalated_link": (
                f"https://{fake.safe_domain_name()}" if fake.boolean() else None
            ),
            "group_name": fake.word() if fake.boolean() else None,
            "issues": issues.get(case_number),
            "labels": [fake.word() for _ in range(fake.random_int(1, 3))],
            "notified_users": [
                {"ssoUsername": fake.safe_email(), "title": fake.name()}
                for _ in range(fake.random_int(0, 2))
            ],
            "potential_escalation": fake.boolean(),
            "priority": fake.random_element(["Major", "Minor"]),
            "product": case_details["product"],
            "relief_at": (  # relief_at must be after createdate
                fake.date_time_between(
                    start_date=datetime.datetime.strptime(
                        case_details["createdate"], "%Y-%m-%dT%H:%M:%SZ"
                    )
                )
                .replace(microsecond=0)
                .isoformat()
                + "Z"
                if fake.boolean()
                else None
            ),
            "resolved_at": (  # resolved_at must be after createdate
                fake.date_time_between(
                    start_date=datetime.datetime.strptime(
                        case_details["createdate"], "%Y-%m-%dT%H:%M:%SZ"
                    )
                )
                .replace(microsecond=0)
                .isoformat()
                + "Z"
                if fake.boolean()
                else None
            ),
            "severity": re.search(r"[a-zA-Z]+", case_details["severity"]).group(),
            "summary": case_details["problem"],
            "tags": case_details.get("tags", []),
        }
    }
    return card


def main():
    """Parse arguments, generate fake data, and dump to JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-n",
        "--number_of_cases",
        help="Enter the number of fake cases you'd like to generate. Default: 10",
        type=int,
        default=10,
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help=(
            "path of JSON where fake data will be placed."
            "Default: ../dashboard/src/data/fake_data.json"
        ),
        default="../dashboard/src/data/fake_data.json",
    )
    args = parser.parse_args()
    fake_data = generate_fake_data(args.number_of_cases)
    with open(f"{args.output}", "w", encoding="utf8") as json_file:
        json.dump(fake_data, json_file, ensure_ascii=False)
    print(f"dumped fake data to {args.output}")


if __name__ == "__main__":
    main()
