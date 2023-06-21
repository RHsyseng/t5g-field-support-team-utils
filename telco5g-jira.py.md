
# telco5g-jira

This script parses an email that contains a Saleforce Telco5G Open case report.
After the script parses the email, it then parses a Jira board for existing
cases and reports on any new cases that need Jira cards created based upon the
case priority (Normal, High, and Urgent).

If desired, the script will also create the Jira cards for the new cases.

## Requisites

You better use a virtualenv to avoid messing with the python modules as:

    python3 -m venv venv
    source venv/bin/activate
    pip install -r bin/telco5g-jira-requirements.txt

### Use

The script take an optional, but recommended, single option that specifies a
configuration file. There is a sample file under the cfg directory.
See the sample.cfg file for the default settings in the script.

#### Jira Personal Access Token (PAT)

The jira PAT can be specified multiple ways.

- password key in the configuration file
- t5g_password environment variable
- passwd via stdin to the command (echo passwd | telco5g-jira.py)
- prompted for by the script. This is done if it is not specified by other means.

For security reasons, the password can be stored in a file with restrictive
permissions and then passed via stdin to the script.

    # ls -l jira.passwd
    -r--------. 1 jirauser jirauser 13 Sep  5 11:17 jira.passwd

    # cat jira.passwd | telco5g-jira.py

#### Source Email

The ***email*** key in the configuration file or the ***t5g_email*** environment
variable can be unset, set to a local file, or set to a url.

It is best to leave this unset or set to an empty string.
Doing so, will cause the script to to query the mail list archive for todays
email and parse it.

If it is set to a local disk file, the file will have its newlines stripped from
it. This file should contain the html table that is the open case report.The
file should not be in quoted-text format.

If it points to a url, the url will be parsed without change.

#### Creating Cards

By default the script will not create any Jira cards.

Instead, it will report on what needs to be done.

To have the script create any new Jira cards, set the key ***card_action*** in
the configuration file or set the ***t5g_card_action*** environment variable.

### Examples

The following will take the password from the **jira.passwd** file and run
script using the sample.cfg file for its settings. Unless this file is changed,
it will simply report if any cards need created:

    cat jira.passwd | telco5g-jira.py sample.ini

The following will create any needed cards:

    cat jira.passwd | t5g_card_action=create telco5g-jira.py sample.ini

And show debug output:

    cat jira.passwd | t5g_debug=true t5g_card_action=create telco5g-jira.py sample.ini

Specify password as a variable:

    t5g_password=changeme t5g_card_action=create telco5g-jira.py sample.ini

Override the user:

    cat jira.passwd | t5g_user=jirauser2 telco5g-jira.py sample.ini

Of course all of these could be set in the configuration file.
