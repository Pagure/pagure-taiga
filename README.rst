Pagure-taiga
============

Pagure is a git-centered forge, python based using pygit2.

With pagure you can host your project with its documentation, let your users
report issues or request enhancements using the ticketing system and build your
community of contributors by allowing them to fork your projects and contribute
to it via the now-popular pull-request mechanism.


Homepage: https://pagure.io/pagure

See it at work: https://pagure.io


pagure-taiga is a plugin for pagure allowing to integrate pagure with
`taiga <https://taiga.io/>`_.

It currently supports:

- syncing new tickets from pagure to issue (scrum projects) or user-stories
   (kanban projects) in taiga and from taiga to pagure

- syncing new comments made on a ticket in pagure to taiga and from taiga
   to pagure

- syncing issue/user-stories status update to pagure as tags and syncing
  tag update in pagure as status change in taiga if the tag correspond to
  one of the status in taiga


Get it running
==============

Run a taiga instance:
^^^^^^^^^^^^^^^^^^^^^

We advice to run taiga using `docker <https://hub.docker.com/search/?type=edition&offering=community>`_
using the project `https://github.com/benhutchins/docker-taiga-example
<https://github.com/benhutchins/docker-taiga-example>`_.


Get pagure-taiga running
^^^^^^^^^^^^^^^^^^^^^^^^

``Documentation to come``
