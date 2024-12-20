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

To automatically apply code patterns with [odoo-module-migrator](https://github.com/OCA/odoo-module-migrator), install library with below syntax:

    $ pipx install git+https://github.com/OCA/odoo-module-migrator.git@master

Using
-----

If the addon does not exist on the target branch, it will assist the user in
the migration, following the OCA migration guide.

If the addon already exists on the target branch, it will retrieve commits
not fully ported grouped by Pull Request and propose to port them.

Syntax:

    $ oca-port <source> <target> <module_path> [options]
    $ oca-port --help

GITHUB_TOKEN can be passed by exposing to environment:

    $ export GITHUB_TOKEN=<token>

Alternatively, you can pass the token directly using the `--github-token` option

If neither method is used, the tool will attempt to obtain the token using the `gh` client (if it's installed).

To check if an addon could be migrated or to get eligible commits to port:

    $ cd <path/to/OCA/cloned_repository>
    $ oca-port origin/16.0 origin/18.0 <module_path> --verbose --dry-run

To effectively migrate the addon or port its commits, remove the `--dry-run` option
so the tool will create a working local branch automatically (called destination)
from the `<target>` branch:

    $ oca-port origin/16.0 origin/18.0 <module_path>

You can control the destination with the `--destination` option:

    $ oca-port origin/16.0 origin/18.0 <module_path> --destination camptocamp/18.0-port-things

The module can be located in a subfolder, and the tool can be used in any kind of repository, e.g:

    $ oca-port origin/main origin/18.0-mig --source-version=16.0 --target-version=18.0 --upstream-org=camptocamp ./odoo/local-src/MY_MODULE --verbose --destination sebalix/18.0-mig-MY_MODULE

- parameters `--source-version` and `--target-version` are mandatory as soon as
  the `source`/`target` parameters cannot be recognized as Odoo versions (here
  `origin/main` is hosting a `16.0` version)
- `--upstream-org` defaults to `OCA`, here we set it to `camptocamp` for GitHub API requests

You can also directly blacklist a bunch of PRs on a given branch thanks to the
`oca-port-pr` tool:

    $ oca-port-pr blacklist OCA/wms#250,OCA/wms#251 16.0 shopfloor

You could give a more detailed reason of this blacklist with `--reason` parameter:

    $ oca-port-pr blacklist OCA/wms#250,OCA/wms#251 16.0 shopfloor --reason "Refactored in 16.0, not needed anymore"

And if the module has been moved to another repository, you can specify its remote as well:

    $ git remote add new_repo git@github.com:OCA/new-repo.git
    $ oca-port-pr blacklist OCA/wms#250,OCA/wms#251 16.0 shopfloor --remote new_repo

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
...     source="origin/14.0",
...     target="origin/16.0",
...     addon_path="stock_move_auto_assign",
...     upstream_org": "OCA",
...     repo_path": "/home/odoo/OCA/stock-logistics-warehouse",
...     output": "json",
...     fetch": True,
...     github_token: "<TOKEN>"
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
