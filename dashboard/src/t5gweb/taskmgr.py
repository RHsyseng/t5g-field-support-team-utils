"""start celery and manage tasks"""

import json
import logging
import os
import xmlrpc

import bugzilla
import redis
import t5gweb.cache as cache
import t5gweb.libtelco5g as libtelco5g
from celery import Celery
from celery.schedules import crontab
from t5gweb.utils import email_notify, set_cfg

mgr = Celery("t5gweb", broker="redis://redis:6379/0", backend="redis://redis:6379/0")


# https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html#entries
@mgr.on_after_configure.connect
def setup_scheduled_tasks(sender, **kwargs):
    cfg = set_cfg()

    # Anything except for 'true' will be set to False
    read_only = os.getenv("READ_ONLY", "false") == "true"

    if read_only is False:
        # Run tasks that alter Jira cards, send emails, or send Slack messages
        logging.warning("Not read only: making changes to Jira Boards")
        # check for new cases
        sender.add_periodic_task(
            crontab(hour="*", minute="10"),  # 10 mins after every hour
            portal_jira_sync.s(),
            name="portal2jira_sync",
        )

        # ensure case severities match card priorities
        sender.add_periodic_task(
            crontab(hour="3", minute="12"),  # everyday at 3:12
            t_sync_priority.s(),
            name="priority_sync",
        )

        # tag telco5g bugzillas and JIRAs with 'Telco' and/or 'Telco:Case'
        if "telco5g" in cfg["query"]:
            sender.add_periodic_task(
                crontab(hour="*/24", minute="33"),  # once a day + 33 for randomness
                tag_bz.s(),
                name="tag_bz",
            )
    else:
        logging.warning("Read only - Not making changes to Jira boards.")

    # update card cache
    sender.add_periodic_task(
        crontab(hour="*", minute="21"),  # on the hour + offset
        cache_data.s("cards"),
        name="card_sync",
    )

    # update case cache
    sender.add_periodic_task(
        crontab(hour="*", minute="*/15"),  # every 15 minutes
        cache_data.s("cases"),
        name="case_sync",
    )

    # update details cache
    sender.add_periodic_task(
        crontab(hour="*/12", minute="24"),  # twice a day
        cache_data.s("details"),
        name="details_sync",
    )

    # update Jira bug details cache
    sender.add_periodic_task(
        crontab(hour="*/12", minute="54"),  # twice a day
        cache_data.s("issues"),
        name="issues_sync",
    )

    # generate daily stats
    sender.add_periodic_task(
        crontab(hour="4", minute="40"),  # every day at 4:40
        cache_stats.s(),
        name="cache_stats",
    )

    # optional tasks

    # update bugzilla details cache
    if cfg["bz_key"] is not None and cfg["bz_key"] != "":
        sender.add_periodic_task(
            crontab(hour="*/12", minute="48"),  # twice a day
            cache_data.s("bugs"),
            name="bugs_sync",
        )

    # update escalations cache
    if cfg["jira_escalations_project"] and cfg["jira_escalations_label"]:
        sender.add_periodic_task(
            crontab(hour="*/2", minute="37"),  # 12x a day
            cache_data.s("escalations"),
            name="escalations_sync",
        )


@mgr.task
def portal_jira_sync():

    logging.warning("job: checking for new cases")
    have_lock = False
    sync_lock = redis.Redis(host="redis").lock("sync_lock", timeout=60 * 60 * 2)
    try:
        have_lock = sync_lock.acquire(blocking=False)
        if have_lock:
            result = libtelco5g.sync_portal_to_jira()
        else:
            result = {"locked": "Task is Locked"}
    finally:
        if have_lock:
            sync_lock.release()
    return result


@mgr.task(autoretry_for=(Exception,), max_retries=5, retry_backoff=30)
def cache_data(data_type):
    logging.warning("job: sync {}".format(data_type))

    cfg = set_cfg()

    result = None

    if data_type == "cases":
        cache.get_cases(cfg)
    elif data_type == "cards":
        # Use redis locks to prevent concurrent refreshes

        have_lock = False
        refresh_lock = redis.Redis(host="redis").lock("refresh_lock", timeout=60 * 30)
        try:
            have_lock = refresh_lock.acquire(blocking=False)
            if have_lock:
                result = cache.get_cards(cfg)
            else:
                logging.warning("lock found. bailing...")
        finally:
            if have_lock:
                refresh_lock.release()
    elif data_type == "details":
        cache.get_case_details(cfg)
    elif data_type == "bugs":
        cache.get_bz_details(cfg)
    elif data_type == "issues":
        cache.get_issue_details(cfg)
    elif data_type == "escalations":
        cases = libtelco5g.redis_get("cases")
        escalations = cache.get_escalations(cfg, cases)
        libtelco5g.redis_set("escalations", json.dumps(escalations))
    else:
        logging.warning("unknown data type")

    return result


@mgr.task(autoretry_for=(Exception,), max_retries=3, retry_backoff=30)
def tag_bz():
    # telco5g specific

    cfg = set_cfg()
    if cfg["jira_query"] != "field":
        logging.warning("bz tagging not enabled for {}".format(cfg["jira_query"]))
        return

    logging.warning("getting bugzillas")
    bz_url = "bugzilla.redhat.com"
    bz_api = bugzilla.Bugzilla(bz_url, api_key=cfg["bz_key"])
    cases = libtelco5g.redis_get("cases")
    bugs = libtelco5g.redis_get("bugs")
    issues = libtelco5g.redis_get("issues")
    jira_conn = libtelco5g.jira_connection(cfg)
    email_body = {
        "Cards with No Private Keywords Field": {"cards": []},
        "Script Tagged Private Keywords": {"cards": []},
        "Cards with No Internal Whiteboard Field": {"cards": []},
        "Script Tagged Internal Whiteboard": {"cards": []},
        "Non-Bug Cards Linked to Cases, Not Tagged": {"cards": []},
    }

    logging.warning("tagging bugzillas")
    for case in bugs:
        if case in cases:
            for bug in bugs[case]:
                try:
                    bz = bz_api.getbug(bug["bugzillaNumber"])
                except xmlrpc.client.Fault:
                    logging.warning(
                        "error: {} is restricted".format(bug["bugzillaNumber"])
                    )
                    bz = None
                if bz:
                    update = None
                    if "telco" not in bz.internal_whiteboard.lower():
                        update = bz_api.build_update(
                            internal_whiteboard="Telco Telco:Case "
                            + bz.internal_whiteboard,
                            minor_update=True,
                        )
                    elif "telco:case" not in bz.internal_whiteboard.lower():
                        update = bz_api.build_update(
                            internal_whiteboard=bz.internal_whiteboard + " Telco:Case",
                            minor_update=True,
                        )
                    if update:
                        logging.warning("tagging BZ:" + str(bz.id))
                        try:
                            bz_api.update_bugs([bz.id], update)
                        except xmlrpc.client.Fault:
                            logging.warning("Tried and failed to tag " + str(bz.id))
                            continue
    logging.warning("tagging Jira Bugs")
    for case in issues:
        if case in cases:
            for issue in issues[case]:
                if issue["jira_type"] == "Bug":
                    attribute_error = False
                    tagged = False
                    card = jira_conn.issue(issue["id"])
                    try:
                        private_keywords = card.fields.customfield_12323649
                    except AttributeError:
                        logging.warning(
                            "No Private Keywords field for {}, skipping".format(
                                str(card)
                            )
                        )
                        attribute_error = True
                        email_body["Cards with No Private Keywords Field"][
                            "cards"
                        ].append(str(card))

                    # Skip if Private Keywords are not enabled.
                    if not attribute_error:
                        if private_keywords is None:
                            private_keywords = []
                        new_keywords = [keyword.value for keyword in private_keywords]
                        if "Telco" not in new_keywords:
                            new_keywords.extend(["Telco", "Telco:Case"])
                            private_keywords_dict = {
                                "customfield_12323649": [
                                    {"value": keyword} for keyword in new_keywords
                                ]
                            }
                            logging.warning("tagging Jira Bug:" + str(card))
                            card.update(private_keywords_dict)
                            email_body["Script Tagged Private Keywords"][
                                "cards"
                            ].append(str(card))
                        elif "Telco:Case" not in new_keywords:
                            new_keywords.append("Telco:Case")
                            private_keywords_dict = {
                                "customfield_12323649": [
                                    {"value": keyword} for keyword in new_keywords
                                ]
                            }
                            logging.warning("tagging Jira Bug:" + str(card))
                            card.update(private_keywords_dict)
                            email_body["Script Tagged Private Keywords"][
                                "cards"
                            ].append(str(card))
                        tagged = True

                    if tagged is False:
                        try:
                            internal_whiteboard = card.fields.customfield_12322040
                        except AttributeError:
                            logging.warning(
                                "No Internal Whiteboard field for {}, skipping".format(
                                    str(card)
                                )
                            )
                            email_body["Cards with No Internal Whiteboard Field"][
                                "cards"
                            ].append(str(card))
                            continue
                        if internal_whiteboard is None:
                            internal_whiteboard = ""
                        if "telco" not in internal_whiteboard.lower():
                            logging.warning("tagging Jira Bug:" + str(card))
                            internal_whiteboard = (
                                "Telco Telco:Case " + internal_whiteboard
                            )
                            update = card.update(
                                customfield_12322040=internal_whiteboard
                            )
                            email_body["Script Tagged Internal Whiteboard"][
                                "cards"
                            ].append(str(card))
                        elif "telco:case" not in internal_whiteboard.lower():
                            logging.warning("tagging Jira Bug:" + str(card))
                            internal_whiteboard = internal_whiteboard + " Telco:Case"
                            update = card.update(
                                customfield_12322040=internal_whiteboard
                            )
                            email_body["Script Tagged Internal Whiteboard"][
                                "cards"
                            ].append(str(card))
                else:
                    email_body["Non-Bug Cards Linked to Cases, Not Tagged"][
                        "cards"
                    ].append(issue["id"])

    for category in email_body:
        message = f"{category}:\n"
        if email_body[category]["cards"]:
            for card in email_body[category]["cards"]:
                message += f"   - {card}\n"
        else:
            message += "   - No cards in this category\n"
        email_body[category]["full_message"] = message
    cfg["to"] = os.environ.get("bug_email")
    cfg["subject"] = "Summary: Jira Bug Tagging"
    email_notify(cfg, email_body)


@mgr.task
def cache_stats():
    logging.warning("job: cache stats")
    cache.get_stats()


@mgr.task(bind=True)
def refresh_background(self):
    """Refresh Jira cards cache in background. If the refresh is already in progress,
    the task will be locked and won't run. The lock is released when the task completes
    or after five minutes.
    Lock code derived from
    http://loose-bits.com/2010/10/distributed-task-locking-in-celery.html
    """

    have_lock = False
    refresh_lock = redis.Redis(host="redis").lock("refresh_lock", timeout=60 * 30)
    try:
        have_lock = refresh_lock.acquire(blocking=False)
        if have_lock:
            libtelco5g.redis_set("refresh_id", json.dumps(self.request.id))
            cfg = set_cfg()
            cache.get_cards(cfg, self, background=True)
            response = {
                "current": 100,
                "total": 100,
                "status": "Done",
                "result": "Refresh Complete",
            }
        else:
            response = {"locked": "Task is Locked"}
    finally:
        if have_lock:
            refresh_lock.release()
    return response


@mgr.task
def t_sync_priority():
    """Ensure that the severity of a case matches the priority of the card"""
    logging.warning("sync case severity to card priority...")
    cfg = set_cfg()
    libtelco5g.sync_priority(cfg)
    logging.warning("...sync completed")
