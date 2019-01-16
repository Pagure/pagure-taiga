#!/usr/bin/env python

from __future__ import print_function, unicode_literals

import argparse
import os

from sqlalchemy import create_engine
import pagure.config

from pagure_taiga.model import BASE, PagureTaiga, PagureTaigaMapping


parser = argparse.ArgumentParser(
    description="Create/Update the Pagure database"
)
parser.add_argument(
    "--config",
    "-c",
    dest="config",
    help="Configuration file to use for pagure.",
)

args = parser.parse_args()

if args.config:
    config = args.config
    if not config.startswith("/"):
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)))
        config = os.path.join(here, config)
    os.environ["PAGURE_CONFIG"] = config
    pagure.config.reload_config()

db_url = pagure.config.config.get("DB_URL")

if db_url.startswith("postgres"):
    engine = create_engine(db_url, echo=True, client_encoding="utf8")
else:
    engine = create_engine(db_url, echo=True)


BASE.metadata.create_all(
    engine, tables=[PagureTaiga.__table__, PagureTaigaMapping.__table__]
)
