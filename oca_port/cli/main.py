# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)
"""Tool helping to port an addon or missing commits of an addon from one branch
to another.

If the addon does not exist on the target branch, it will assist the user
in the migration, following the OCA migration guide.

If the addon already exists on the target branch, it will retrieve missing
commits to port. If a Pull Request exists for a missing commit, it will be
ported with all its commits if they were not yet (fully) ported.

To check if an addon could be migrated or to get eligible commits to port:

    $ export GITHUB_TOKEN=<token>
    $ oca-port 13.0 14.0 shopfloor --verbose

To effectively migrate the addon or port its commits, use the `--fork` option:

    $ oca-port 13.0 14.0 shopfloor --fork camptocamp


Migration of addon
------------------

The tool follows the usual OCA migration guide to port commits of an addon,
and will invite the user to fullfill the mentionned steps that can't be
performed automatically.

Port of commits/Pull Requests
-----------------------------

The tool will ask the user if he wants to open draft pull requests against
the upstream repository.

If there are several Pull Requests to port, it will ask the user if he wants to
base the next PR on the previous one, allowing the user to cumulate ported PRs
in one branch and creating a draft PR against the upstream repository with all
of them.
"""
import os

import click

from ..app import App
from ..exceptions import ForkValueError, RemoteBranchValueError
from ..utils.misc import bcolors as bc


@click.command()
@click.argument("from_branch", required=True)
@click.argument("to_branch", required=True)
@click.argument("addon", required=True)
@click.option(
    "--from-org",
    default="OCA",
    show_default=True,
    help="Upstream organization name.",
)
@click.option(
    "--from-remote",
    default="origin",
    show_default=True,
    required=True,
    help="Git remote from which source branches are fetched by default.",
)
@click.option("--repo-name", help="Repository name, eg. server-tools.")
@click.option(
    "--fork", help="Git remote where branches with ported commits are pushed."
)
@click.option("--user-org", show_default="--fork", help="User organization name.")
@click.option("--verbose", is_flag=True, help="List the commits of Pull Requests.")
@click.option(
    "--non-interactive", is_flag=True, help="Disable all interactive prompts."
)
@click.option(
    "--output",
    help=(
        "Returns the result in a given format. "
        "This implies the `--non-interactive` option automatically. "
        "Possibles values are: 'json'."
    ),
)
@click.option("--fetch", is_flag=True, help="Fetch remote branches from upstream.")
@click.option("--no-cache", is_flag=True, help="Disable user's cache.")
@click.option("--clear-cache", is_flag=True, help="Clear the user's cache.")
def main(
    from_branch: str,
    to_branch: str,
    addon: str,
    from_org: str,
    from_remote: str,
    repo_name: str,
    fork: str,
    user_org: str,
    verbose: bool,
    non_interactive: bool,
    output: str,
    fetch: bool,
    no_cache: bool,
    clear_cache: bool,
):
    """Migrate ADDON from FROM_BRANCH to TO_BRANCH or list Pull Requests to port
        if ADDON already exists on TO_BRANCH.

        Migration:

            Assist the user in the migration of the addon, following the OCA guidelines.

        Port of Pull Requests (missing commits):

            The PRs are found from FROM_BRANCH commits that do not exist in TO_BRANCH.
    The user will be asked if he wants to port them.

        To start the migration process, the `--fork` option must be provided in
    order to push the resulting branch on the user's remote.
    """
    try:
        app = App(
            addon=addon,
            from_branch=from_branch,
            to_branch=to_branch,
            from_org=from_org,
            from_remote=from_remote,
            repo_path=os.getcwd(),
            repo_name=repo_name,
            fork=fork,
            user_org=user_org,
            verbose=verbose,
            non_interactive=non_interactive,
            output=output,
            fetch=fetch,
            no_cache=no_cache,
            clear_cache=clear_cache,
            cli=True,
        )
    except ForkValueError as exc:
        error_msg = prepare_remote_error_msg(*exc.args)
        error_msg += (
            "\n\nYou can change the GitHub organization with the "
            f"{bc.DIM}--user-org{bc.END} option."
        )
        raise click.ClickException(error_msg) from exc
    except RemoteBranchValueError as exc:
        error_msg = prepare_remote_error_msg(*exc.args)
        raise click.ClickException(error_msg) from exc
    except ValueError as exc:
        raise click.ClickException(exc) from exc
    # Run the app
    try:
        app.run()
    except ValueError as exc:
        raise click.ClickException(exc) from exc


def prepare_remote_error_msg(repo_name, remote):
    return (
        f"No remote {bc.FAIL}{remote}{bc.END} in the current repository.\n"
        "To add it:\n"
        "\t# This mode requires an SSH key in the GitHub account\n"
        f"\t{bc.DIM}$ git remote add {remote} "
        f"git@github.com:{remote}/{repo_name}.git{bc.END}\n"
        "   Or:\n"
        "\t# This will require to enter user/password each time\n"
        f"\t{bc.DIM}$ git remote add {remote} "
        f"https://github.com/{remote}/{repo_name}.git{bc.END}"
    )


if __name__ == "__main__":
    main()
