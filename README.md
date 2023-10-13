[![Pre-commit Status](https://github.com/OCA/oca-port/actions/workflows/pre-commit.yml/badge.svg?branch=main)](https://github.com/OCA/oca-port/actions/workflows/pre-commit.yml?query=branch%3Amain)

oca-port
========

Tool helping to port an addon or missing commits of an addon from one branch
to another.

Installing
----------

    $ pipx install oca-port
    $ #OR
    $ git clone git@github.com:oca/oca-port.git
    $ cd oca-port
    $ pipx install .

Using
-----

If the addon does not exist on the target branch, it will assist the user in
the migration, following the OCA migration guide.

If the addon already exists on the target branch, it will retrieve missing
commits to port. If a Pull Request exists for a missing commit, it will be
ported with all its commits if they were not yet (fully) ported.

To check if an addon could be migrated or to get eligible commits to port:

    $ export GITHUB_TOKEN=<token>
    $ oca-port 14.0 15.0 shopfloor --verbose

To effectively migrate the addon or port its commits, use the `--fork` option:

    $ oca-port 14.0 15.0 shopfloor --fork camptocamp

You can also directly blacklist a bunch of PRs on a given branch thanks to the
`oca-port-pr` tool:

    $ oca-port-pr blacklist OCA/wms#250,OCA/wms#251 15.0 shopfloor

You could give a more detailed reason of this blacklist with `--reason` parameter:

    $ oca-port-pr blacklist OCA/wms#250,OCA/wms#251 15.0 shopfloor --reason "Refactored in 15.0, not needed anymore"

And if the module has been moved to another repository, you can specify its remote as well:

    $ git remote add new_repo git@github.com:OCA/new-repo.git
    $ oca-port-pr blacklist OCA/wms#250,OCA/wms#251 15.0 shopfloor --remote new_repo

Migration of addon
------------------

The tool follows the usual OCA migration guide to port commits of an addon,
and will invite the user to fullfill the mentionned steps that can't be
performed automatically.

**Output example:**
![image](https://user-images.githubusercontent.com/5315285/129355442-f863adff-33c0-4c91-b0cb-b6882312e340.png)

If used with the `--non-interactive` option, the returned exit code is `100`
if an addon could be migrated.

Port of commits/Pull Requests
-----------------------------

The tool will ask the user if he wants to open draft pull requests against
the upstream repository.

If there are several Pull Requests to port, it will ask the user if he wants
to base the next PR on the previous one, allowing the user to cumulate ported
PRs in one branch and creating a draft PR against the upstream repository
with all of them.

More details here : [OCA Days 2022 - Sébastien Alix and Simone Orsi: oca-port:new OCA tool to help with modules migration](https://www.youtube.com/watch?v=idGLkQiJ5N0)

**Output example (with --verbose):**
![oca_port_pr_verbose](https://user-images.githubusercontent.com/5315285/129207041-12ac6c4a-ea96-4b8c-bd68-ae661531ad92.png)

If used with the `--non-interactive` option, the returned exit code is `110`
if some pull requests/commits could be ported.

API
---

You can also use `oca-port` as a Python package:

```python
>>> import oca_port
>>> app = oca_port.App(
...     from_branch="14.0",
...     to_branch="16.0",
...     addon="stock_move_auto_assign",
...     from_org": "OCA",
...     from_remote": "origin",
...     repo_path": "/home/odoo/OCA/stock-logistics-warehouse",
...     output": "json",
...     fetch": True,
...     github_token: "ghp_sheeXai3xu1yoopheiquoo3ohch0AefooSob"
... )
>>> json_data = app.run()
>>> data = json.loads(json_data)
>>> from pprint import pprint as pp
>>> pp(data)
{'process': 'port_commits',
 'results': {'1631': {'author': 'TDu',
                      'merged_at': '2023-04-04T17:06:03Z',
                      'missing_commits': ['41416c1d7dad15ce4745e07d0541c79e938c2710',
                                          'd43985a443e29641447a3811f2310d54b886ab3d',
                                          '6bd9fcff3e814a6802c7aefadb9c646194cde42b'],
                      'ref': 'OCA/stock-logistics-warehouse#1631',
                      'title': '[14][ADD] stock_move_auto_assign_auto_release '
                               '- backport',
                      'url': 'https://github.com/OCA/stock-logistics-warehouse/pull/1631'}}}
```
