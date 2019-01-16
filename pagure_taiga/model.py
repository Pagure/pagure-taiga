# -*- coding: utf-8 -*-

"""
 (c) 2018 - Copyright Red Hat Inc

 Authors:
   Pierre-Yves Chibon <pingou@pingoured.fr>

"""

from __future__ import unicode_literals, print_function

import logging
import sqlalchemy as sa

from sqlalchemy.orm import backref
from sqlalchemy.orm import relation

from pagure.lib.model_base import BASE
from pagure.lib.model import Project


_log = logging.getLogger(__name__)


# DB Model


class PagureTaiga(BASE):
    """ Stores information about a taiga project linked to a pagure one.

    Table -- pagure_taiga
    """

    __tablename__ = "pagure_taiga"
    __table_args__ = (sa.UniqueConstraint("taiga_url", "project_name"),)

    id = sa.Column(sa.Integer, primary_key=True)
    project_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("projects.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    taiga_url = sa.Column(sa.String(255), nullable=True, unique=False)
    taiga_token = sa.Column(sa.String(255), nullable=True, index=True)
    project_name = sa.Column(sa.String(255), nullable=True)
    project_type = sa.Column(sa.String(255), nullable=True)
    taiga_project_id = sa.Column(
        sa.Integer, nullable=True, unique=True, index=True
    )

    project = relation(
        "Project",
        remote_side=[Project.id],
        backref=backref(
            "taiga",
            cascade="delete, delete-orphan",
            single_parent=True,
            uselist=False,
        ),
    )


class PagureTaigaMapping(BASE):
    """ Stores mapping information between pagure and taiga.
    For the moment, it stores more precisely the mapping between tickets
    in pagure and issues/user stories in taiga.

    Table -- pagure_taiga_mapping
    """

    __tablename__ = "pagure_taiga_mapping"
    __table_args__ = (
        sa.UniqueConstraint("taiga_project", "pagure_ticket_id", "taiga_type"),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    taiga_project = sa.Column(
        sa.Integer,
        sa.ForeignKey(
            "pagure_taiga.taiga_project_id",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    taiga_id = sa.Column(sa.Integer, nullable=False, index=True)
    pagure_ticket_id = sa.Column(sa.Integer, nullable=False, index=True)
    taiga_type = sa.Column(sa.String(255), nullable=False)
