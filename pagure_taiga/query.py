# -*- coding: utf-8 -*-

"""
 (c) 2019 - Copyright Red Hat Inc

 Authors:
   Pierre-Yves Chibon <pingou@pingoured.fr>

"""

from __future__ import unicode_literals, print_function

import logging
import os

from celery import Celery
from celery.signals import after_setup_task_logger
from taiga import TaigaAPI
import taiga.exceptions

from pagure.lib.tasks_utils import pagure_task
from pagure.config import config as pagure_config
import pagure.lib.query
import pagure.lib.model

from pagure_taiga import model

_log = logging.getLogger(__name__)


if os.environ.get("PAGURE_BROKER_URL"):
    broker_url = os.environ["PAGURE_BROKER_URL"]
elif pagure_config.get("BROKER_URL"):
    broker_url = pagure_config["BROKER_URL"]
else:
    broker_url = "redis://%s" % pagure_config["REDIS_HOST"]

conn = Celery("tasks", broker=broker_url, backend=broker_url)
conn.conf.update(pagure_config["CELERY_CONFIG"])


@after_setup_task_logger.connect
def augment_celery_log(**kwargs):
    pagure.utils.set_up_logging(force=True)


def get_ticket_mapping_from_pagure(
    session, taiga_project_id, pagure_id, taiga_type
):
    """ Returns the mapping stored in the database between the object in
    taiga and the one in pagure.
    """
    query = session.query(model.PagureTaigaMapping).filter(
        model.PagureTaigaMapping.taiga_project == taiga_project_id,
        model.PagureTaigaMapping.pagure_ticket_id == pagure_id,
        model.PagureTaigaMapping.taiga_type == taiga_type,
    )
    return query.first()


def get_ticket_mapping_from_taiga(
    session, taiga_project_id, taiga_id, taiga_type
):
    """ Returns the mapping stored in the database between the object in
    taiga and the one in pagure.
    """
    query = session.query(model.PagureTaigaMapping).filter(
        model.PagureTaigaMapping.taiga_project == taiga_project_id,
        model.PagureTaigaMapping.taiga_id == taiga_id,
        model.PagureTaigaMapping.taiga_type == taiga_type,
    )
    return query.first()


def get_pagure_project_from_taiga(session, taiga_project_id):
    """ Return the pagure project corresponding to the provided taiga project
    identifier.
    """
    query = session.query(model.PagureTaiga).filter(
        model.PagureTaiga.taiga_project_id == taiga_project_id
    )

    mapping = query.first()
    if mapping:
        return mapping.project


def get_comment_of_ticket(session, ticket, comment_text):
    """ Return the IssueComment of the specified ticket having the given
    text.
    """
    query = session.query(pagure.lib.model.IssueComment).filter(
        pagure.lib.model.IssueComment.issue_uid == ticket.uid,
        pagure.lib.model.IssueComment.comment == comment_text,
    )
    return query.first()


def _get_issue(session, project, taiga_data):
    """ Return the issue corresponding to the data retrieved from taiga
    based on the mapping stored in the database.
    """
    taiga_project_id = taiga_data["data"]["project"]["id"]

    # Ensure the issue already exists
    _log.info("Checking if the ticket exists in the pagure's project")
    mapping = get_ticket_mapping_from_taiga(
        session,
        taiga_project_id,
        taiga_data["data"]["ref"],
        taiga_data["type"],
    )
    if not mapping:
        _log.info("Ticket not found in the database, creating it")
        create_ticket_from_taiga(session, taiga_data)
        mapping = get_ticket_mapping_from_taiga(
            session,
            taiga_project_id,
            taiga_data["data"]["ref"],
            taiga_data["type"],
        )
        if not mapping:
            _log.info("Ticket still not found in the database, bailing")
            return

    # Issue found
    _log.info(
        "Issue (taiga ref %s) found in our mapping" % taiga_data["data"]["ref"]
    )

    issue = pagure.lib.query.search_issues(
        session, project, issueid=mapping.pagure_ticket_id
    )
    if issue:
        _log.info(
            "Issue (taiga ref %s) found in pagure: %s"
            % (taiga_data["data"]["ref"], issue)
        )
        return issue


@conn.task(
    queue=pagure_config.get("PAGURE_TAIGA_CELERY_QUEUE", None), bind=True
)
@pagure_task
def new_ticket(self, session, data):
    """ Create a new ticket on taiga. """
    reponame = data["project"]["name"]
    username = (
        data["project"]["user"]["name"] if data["project"]["parent"] else None
    )
    namespace = data["project"]["namespace"]
    project = pagure.lib.query.get_authorized_project(
        session, reponame, user=username, namespace=namespace
    )

    api = TaigaAPI(
        token=project.taiga.taiga_token, host=project.taiga.taiga_url
    )
    if project.taiga.project_type == "kanboard":
        taiga_type = "userstory"
    else:
        taiga_type = "issue"

    taiga_project = api.projects.get_by_slug(project.taiga.project_name)
    if get_ticket_mapping_from_pagure(
        session,
        taiga_project_id=taiga_project.id,
        pagure_id=data["issue"]["id"],
        taiga_type=taiga_type,
    ):
        _log.info("Ticket already exists in taiga, bailing")
        return

    if project.taiga.project_type == "kanboard":
        _log.info("Project is kanboard - adding userstory")
        taiga_user_story = taiga_project.add_user_story(
            subject=data["issue"]["title"],
            description=data["issue"]["content"],
        )
        _log.info(
            "Adding mapping: %s to %s for project: %s",
            taiga_user_story.ref,
            data["issue"]["id"],
            taiga_project.id,
        )
        mapping = model.PagureTaigaMapping(
            taiga_project=taiga_project.id,
            taiga_id=taiga_user_story.ref,
            pagure_ticket_id=data["issue"]["id"],
            taiga_type="userstory",
        )
        session.add(mapping)
        session.commit()
    else:
        taiga_issue = taiga_project.add_issue(
            subject=data["issue"]["title"],
            priority=data["issue"]["priority"],
            status=taiga_project.issue_statuses.get(
                name=data["issue"]["status"]
            ),
            issue_type=None,
            severity=None,
            description=data["issue"]["content"],
        )
        _log.info(
            "Adding mapping: %s to %s for project: %s",
            taiga_issue.ref,
            data["issue"]["id"],
            taiga_project.id,
        )
        mapping = model.PagureTaigaMapping(
            taiga_project=taiga_project.id,
            taiga_id=taiga_issue.ref,
            pagure_ticket_id=data["issue"]["id"],
            taiga_type="issue",
        )
        session.add(mapping)
        session.commit()
    _log.info("Ticket created in taiga from pagure")


@conn.task(
    queue=pagure_config.get("PAGURE_TAIGA_CELERY_QUEUE", None), bind=True
)
@pagure_task
def new_comment_ticket(self, session, data):
    """ Add a new comment on a ticket in taiga. """
    reponame = data["project"]["name"]
    username = (
        data["project"]["user"]["name"] if data["project"]["parent"] else None
    )
    namespace = data["project"]["namespace"]
    project = pagure.lib.query.get_authorized_project(
        session, reponame, user=username, namespace=namespace
    )

    api = TaigaAPI(
        token=project.taiga.taiga_token, host=project.taiga.taiga_url
    )

    taiga_project = api.projects.get_by_slug(project.taiga.project_name)

    if project.taiga.project_type == "kanboard":
        issue_type = "userstory"
    else:
        issue_type = "issue"

    mapping = get_ticket_mapping_from_pagure(
        session=session,
        taiga_project_id=taiga_project.id,
        pagure_id=data["issue"]["id"],
        taiga_type=issue_type,
    )
    if not mapping:
        print("No corresponding issue found in our mapping")
        return

    issue = taiga_project.get_userstory_by_ref(mapping.taiga_id)

    if issue:
        _log.info("Found issue, searching comment")
        found = False
        if issue_type == "userstory":
            history = api.history.user_story.get(issue.id)
        else:
            history = api.history.issue.get(issue.id)
        new_comment = data["issue"]["comments"][-1]
        for comment in history:
            if comment["delete_comment_date"]:
                # Ignore deleted comments
                continue
            # if comment["user"]["name"] != new_comment["user"]["name"]:
            # Ignore comment made by someone else
            # continue
            if comment["comment"] == new_comment["comment"]:
                # Comment already posted
                found = True

        if not found:
            issue.add_comment(data["issue"]["comments"][-1]["comment"])


@conn.task(
    queue=pagure_config.get("PAGURE_TAIGA_CELERY_QUEUE", None), bind=True
)
@pagure_task
def delete_ticket_on_taiga_from_pagure(self, session, data):
    """ Delete the ticket in taiga based on the information provided by
    pagure.
    """
    reponame = data["project"]["name"]
    username = (
        data["project"]["user"]["name"] if data["project"]["parent"] else None
    )
    namespace = data["project"]["namespace"]
    project = pagure.lib.query.get_authorized_project(
        session, reponame, user=username, namespace=namespace
    )

    api = TaigaAPI(
        token=project.taiga.taiga_token, host=project.taiga.taiga_url
    )

    taiga_project = api.projects.get_by_slug(project.taiga.project_name)

    if project.taiga.project_type == "kanboard":
        issue_type = "userstory"
    else:
        issue_type = "issue"

    mapping = get_ticket_mapping_from_pagure(
        session=session,
        taiga_project_id=taiga_project.id,
        pagure_id=data["issue"]["id"],
        taiga_type=issue_type,
    )
    if not mapping:
        print("No corresponding issue found in our mapping")
        return

    try:
        issue = taiga_project.get_userstory_by_ref(mapping.taiga_id)
        issue.delete()
        session.delete(mapping)
        session.commit()
    except taiga.exceptions.TaigaRestException:
        _log.exception("Could find/delete the ticket")


@conn.task(
    queue=pagure_config.get("PAGURE_TAIGA_CELERY_QUEUE", None), bind=True
)
@pagure_task
def create_ticket_from_taiga(self, session, taiga_data):
    """ Creates a ticket in pagure based on the information provided by
    taiga's webhook.
    """

    taiga_project_id = taiga_data["data"]["project"]["id"]
    project = get_pagure_project_from_taiga(session, taiga_project_id)
    if not project:
        _log.info("No pagure project found associated, bailing")
        return

    # username = taiga_data["by"]["username"]
    username = "pingou"
    assignee = taiga_data["data"]["assigned_to"]
    milestone = taiga_data["data"]["milestone"]
    priority = None
    tags = [taiga_data["data"]["status"]["name"]] + taiga_data["data"]["tags"]

    # Check if tag/status exist in the project, if not add them
    _log.info("Checking if tags and status exist in the pagure's project")

    # Check if issue already exists
    _log.info("Checking if the ticket exists in the pagure's project")
    if get_ticket_mapping_from_taiga(
        session,
        taiga_project_id,
        taiga_data["data"]["ref"],
        taiga_data["type"],
    ):
        _log.info("Ticket already in the database, bailing")
        return

    # Issue not found, adding it
    _log.info(
        "Issue (taiga ref %s) not found, adding it to pagure"
        % taiga_data["data"]["ref"]
    )
    issue_id = pagure.lib.query.get_next_id(session, project.id)
    mapping = model.PagureTaigaMapping(
        taiga_project=taiga_project_id,
        taiga_id=taiga_data["data"]["ref"],
        pagure_ticket_id=issue_id,
        taiga_type=taiga_data["type"],
    )
    session.add(mapping)
    session.commit()
    pagure.lib.query.new_issue(
        session,
        repo=project,
        issue_id=issue_id,
        title=taiga_data["data"]["subject"],
        content=taiga_data["data"]["description"],
        private=False,
        user=username,
        assignee=assignee,
        milestone=milestone,
        priority=priority,
        tags=tags,
    )
    session.commit()


@conn.task(
    queue=pagure_config.get("PAGURE_TAIGA_CELERY_QUEUE", None), bind=True
)
@pagure_task
def comment_on_ticket_from_taiga(self, session, taiga_data):
    """ Comment on a ticket in pagure based on the information provided by
    taiga's webhook.
    """
    taiga_project_id = taiga_data["data"]["project"]["id"]
    project = get_pagure_project_from_taiga(session, taiga_project_id)
    if not project:
        _log.info("No pagure project found associated, bailing")
        return

    # username = taiga_data["by"]["username"]
    username = "pingou"
    assignee = taiga_data["data"]["assigned_to"]
    milestone = taiga_data["data"]["milestone"]
    priority = None
    tags = [taiga_data["data"]["status"]["name"]] + taiga_data["data"]["tags"]

    # Check if tag/status exist in the project, if not add them
    _log.info("Checking if tags and status exist in the pagure's project")

    issue = _get_issue(session, project, taiga_data)
    if not issue:
        _log.info("No corresponding issue found")
        return

    if not get_comment_of_ticket(
        session, issue, taiga_data["change"]["comment"]
    ):
        pagure.lib.query.add_issue_comment(
            session,
            issue=issue,
            comment=taiga_data["change"]["comment"],
            # user=taiga_data["by"]["username"],
            user="pingou",
        )
    else:
        _log.info("Comment already existing on the ticket, bailing")


@conn.task(
    queue=pagure_config.get("PAGURE_TAIGA_CELERY_QUEUE", None), bind=True
)
@pagure_task
def update_ticket_status_from_taiga(self, session, taiga_data):
    """ Update the status of a ticket in pagure based on the information
    provided by taiga's webhook.
    """
    taiga_project_id = taiga_data["data"]["project"]["id"]
    project = get_pagure_project_from_taiga(session, taiga_project_id)
    if not project:
        _log.info("No pagure project found associated, bailing")
        return

    issue = _get_issue(session, project, taiga_data)
    if not issue:
        _log.info("No corresponding issue found")
        return

    new_tag = taiga_data["change"]["diff"]["status"]["to"]
    old_tag = taiga_data["change"]["diff"]["status"]["from"]

    issue_tags_text = [t.tag for t in project.tags_colored]
    if new_tag not in issue_tags_text:
        pagure.lib.query.new_tag(
            session=session,
            tag_name=taiga_data["data"]["status"]["name"],
            tag_description=taiga_data["data"]["status"]["name"],
            tag_color=taiga_data["data"]["status"]["color"],
            project_id=project.id,
        )
        session.commit()

    tags = issue.tags_text
    if old_tag in tags:
        tags.remove(old_tag)
    tags.append(new_tag)

    # username = taiga_data["by"]["username"]
    username = "pingou"

    messages = set(
        pagure.lib.query.update_tags(
            session=session, obj=issue, tags=tags, username=username
        )
    )
    not_needed = set(["Comment added", "Updated comment"])
    pagure.lib.query.add_metadata_update_notif(
        session=session,
        obj=issue,
        messages=messages - not_needed,
        user=username,
    )
    session.commit()


@conn.task(
    queue=pagure_config.get("PAGURE_TAIGA_CELERY_QUEUE", None), bind=True
)
@pagure_task
def update_ticket_status_on_taiga(self, session, data):
    """ Update the status of a ticket in taiga based on the information
    provided by pagure.
    """
    reponame = data["project"]["name"]
    username = (
        data["project"]["user"]["name"] if data["project"]["parent"] else None
    )
    namespace = data["project"]["namespace"]
    project = pagure.lib.query.get_authorized_project(
        session, reponame, user=username, namespace=namespace
    )

    issue_tags = data["tags"]

    api = TaigaAPI(
        token=project.taiga.taiga_token, host=project.taiga.taiga_url
    )

    taiga_project = api.projects.get_by_slug(project.taiga.project_name)

    if project.taiga.project_type == "kanboard":
        issue_type = "userstory"
        statuses = taiga_project.list_user_story_statuses()
    else:
        issue_type = "issue"
        statuses = taiga_project.list_issue_statuses()
    statuses_text = [i.name for i in statuses]

    mapping = get_ticket_mapping_from_pagure(
        session=session,
        taiga_project_id=taiga_project.id,
        pagure_id=data["issue"]["id"],
        taiga_type=issue_type,
    )
    if not mapping:
        print("No corresponding issue found in our mapping")
        return

    issue = taiga_project.get_userstory_by_ref(mapping.taiga_id)
    new_status = None
    for tag in issue_tags:
        if tag in statuses_text:
            if new_status and statuses_text.index(tag) > new_status:
                new_status = statuses_text.index(tag)
            else:
                new_status = statuses_text.index(tag)
    if new_status:
        _log.info(
            "Updating the status to %s (id:%s)",
            statuses_text[new_status],
            statuses[new_status].id,
        )
        issue.status = statuses[new_status].id
        issue.update()


@conn.task(
    queue=pagure_config.get("PAGURE_TAIGA_CELERY_QUEUE", None), bind=True
)
@pagure_task
def delete_ticket_on_pagure_from_taiga(self, session, taiga_data):
    """ Delete the ticket in pagure based on the information provided by
    taiga's webhook.
    """
    print(dir(session))
    session.commit()
    session.expunge_all()

    taiga_project_id = taiga_data["data"]["project"]["id"]
    project = get_pagure_project_from_taiga(session, taiga_project_id)
    if not project:
        _log.info("No pagure project found associated, bailing")
        return

    issue = _get_issue(session, project, taiga_data)
    if not issue:
        _log.info("No corresponding issue found")
        return

    # username = taiga_data["by"]["username"]
    username = "pingou"

    pagure.lib.query.drop_issue(session=session, issue=issue, user=username)
    mapping = get_ticket_mapping_from_taiga(
        session,
        taiga_project_id,
        taiga_data["data"]["ref"],
        taiga_data["type"],
    )
    if mapping:
        session.delete(mapping)
    session.commit()
