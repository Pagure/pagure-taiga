# -*- coding: utf-8 -*-

"""
 (c) 2018 - Copyright Red Hat Inc

 Authors:
   Pierre-Yves Chibon <pingou@pingoured.fr>

"""

from __future__ import unicode_literals, print_function
import logging
import time

import flask
import blinker
import wtforms

from sqlalchemy.exc import SQLAlchemyError
import taiga
import taiga.exceptions

import pagure.forms

from pagure_taiga import model
from pagure_taiga import query

_log = logging.getLogger(__name__)

TAIGA_NS = flask.Blueprint(
    "taiga_ns", __name__, url_prefix="/_taiga", template_folder="templates"
)


# UI Pieces


class TaigaConfiForm(pagure.forms.PagureForm):
    """ Form to configure taiga for a project. """

    taiga_url = wtforms.StringField(
        'URL to the taiga instance <span class="error">*</span>',
        [wtforms.validators.DataRequired()],
    )
    taiga_token = wtforms.StringField(
        'Auth token for taiga <span class="error">*</span>',
        [wtforms.validators.DataRequired()],
    )
    project_name = wtforms.StringField(
        'Project name in taiga <span class="error">*</span>',
        [wtforms.validators.DataRequired()],
    )
    project_type = wtforms.SelectField(
        'Project type in taiga <span class="error">*</span>',
        [wtforms.validators.DataRequired()],
        choices=[("kanban", "kanban"), ("scrum", "scrum")],
    )


@TAIGA_NS.route("/<repo>/webhook", methods=["GET", "POST"])
@TAIGA_NS.route("/<namespace>/<repo>/webhook", methods=["GET", "POST"])
def webhook(repo, namespace=None):
    """ Endpoint called by taiga to sync with pagure. """
    import pprint

    pprint.pprint(flask.request.json)
    # Wait a sec before processing the request from taiga -- reduces
    # chances of race conditions
    time.sleep(1)

    data = flask.request.json
    taiga_type = data["type"]
    action = data["action"]
    if action == "create":
        if taiga_type in ["issue", "userstory"]:
            print("Create new ticket for corresponding %s" % taiga_type)
            query.create_ticket_from_taiga.delay(data)
        else:
            print("Un-supported create action on: %s" % taiga_type)
    elif action == "change":
        if "comment" in data["change"]:
            if data["change"]["edit_comment_date"]:
                print("Edit comment in %s" % taiga_type)
            elif data["change"]["delete_comment_date"]:
                print("Deleting comment on %s" % taiga_type)
            elif data["change"]["comment"]:
                print("Adding a new comment on %s" % taiga_type)
                query.comment_on_ticket_from_taiga.delay(data)
            elif data["change"]["diff"].get("status"):
                print("Changing status of %s" % taiga_type)
                query.update_ticket_status_from_taiga.delay(data)
            else:
                print("Un-supported change on %s" % taiga_type)
    elif action == "delete":
        print("Deleting %s" % taiga_type)
        query.delete_ticket_on_pagure_from_taiga.delay(data)
    else:
        print("Un-support action: %s on %s" % (action, taiga_type))
    return "all good"


@TAIGA_NS.route("/<repo>/config/", methods=["GET", "POST"])
@TAIGA_NS.route("/<repo>/config", methods=["GET", "POST"])
@TAIGA_NS.route("/<namespace>/<repo>/config/", methods=["GET", "POST"])
@TAIGA_NS.route("/<namespace>/<repo>/config/", methods=["GET", "POST"])
def settings(repo, namespace=None):
    """ Configure the taiga integration for the specified project. """

    repo = flask.g.repo

    form = TaigaConfiForm()
    if form.validate_on_submit():

        api = taiga.TaigaAPI(
            token=form.taiga_token.data, host=form.taiga_url.data
        )

        project_name = form.project_name.data

        try:
            taiga_project = api.projects.get_by_slug(project_name)
        except taiga.exceptions.TaigaRestException as err:
            flask.flash(str(err), "error")
            return flask.redirect(
                flask.url_for(
                    "ui_ns.view_settings",
                    repo=repo.name,
                    namespace=repo.namespace,
                )
            )

        create = True
        url = flask.url_for(
            "taiga_ns.webhook",
            repo=repo.name,
            namespace=repo.namespace,
            _external=True,
        )
        for webhook in taiga_project.list_webhooks():
            if webhook.name == "pagure_webhook":
                create = False
                webhook.url = (url,)
                webhook.key = form.taiga_token.data
                break

        if create:
            print(url, form.taiga_token.data)
            taiga_project.add_webhook(
                name="pagure_webhook", url=url, key=form.taiga_token.data
            )

        if repo.taiga:
            repo.taiga.taiga_url = form.taiga_url.data
            repo.taiga.taiga_token = form.taiga_token.data
            repo.taiga.project_name = project_name
            repo.taiga.project_type = form.project_type.data
            repo.taiga.taiga_project_id = taiga_project.id
            flask.g.session.add(repo.taiga)
        else:
            pagure_taiga = model.PagureTaiga(
                project_id=repo.id,
                taiga_url=form.taiga_url.data,
                taiga_token=form.taiga_token.data,
                project_name=form.project_name.data,
                project_type=form.project_type.data,
                taiga_project_id=taiga_project.id,
            )
            flask.g.session.add(pagure_taiga)
        try:
            flask.g.session.commit()
            flask.flash("Taiga configured!")
        except SQLAlchemyError as err:  # pragma: no cover
            flask.g.session.rollback()
            _log.exception(err)
            flask.flash(
                "Could not configure taiga properly in the database", "error"
            )
        return flask.redirect(
            flask.url_for(
                "ui_ns.view_settings", repo=repo.name, namespace=repo.namespace
            )
        )
    elif flask.request.method == "GET":
        if repo.taiga:
            form.taiga_url.data = repo.taiga.taiga_url
            form.taiga_token.data = repo.taiga.taiga_token
            form.project_name.data = repo.taiga.project_name
            form.project_type.data = repo.taiga.project_type

    return flask.render_template(
        "taiga_config.html", select="Taiga Integration", repo=repo, form=form
    )


# Sync logic

pagure_signal = blinker.signal("pagure")


@pagure_signal.connect
def receive_data(sender, topic, message, **kw):
    print("=" * 80)
    print("pagure-taiga received a notification")
    import pprint

    pprint.pprint(topic)
    pprint.pprint(message)
    try:
        if topic == "issue.new":
            query.new_ticket.delay(message)
        elif topic == "issue.comment.added":
            query.new_comment_ticket.delay(message)
        elif topic == "issue.drop":
            query.delete_ticket_on_taiga_from_pagure.delay(message)
        elif topic == "issue.tag.added":
            query.update_ticket_status_on_taiga.delay(message)
    except Exception:
        _log.exception("Could not act as desired")
    print("=" * 80)
    return "received!"
