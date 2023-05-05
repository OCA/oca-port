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

Migration of addon
------------------

The tool follows the usual OCA migration guide to port commits of an addon,
and will invite the user to fullfill the mentionned steps that can't be
performed automatically.

**Output example:**
![image](https://user-images.githubusercontent.com/5315285/129355442-f863adff-33c0-4c91-b0cb-b6882312e340.png)

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
