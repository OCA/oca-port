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

To effectively migrate the addon or port its commits, use the `--destination` option:

    $ oca-port 13.0 14.0 shopfloor --destination camptocamp/wms#14-mig-shopfloor

Note that you can specify organization,
repo and branch at the same time for both source and target:

    $ oca-port OCA/wms#13.0 camptocamp/wms#14-dev

The organization will be used by default as the remote name but you can override that
by using `--source-remote`, `--target-remote` and `--destination-remote`.

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

import click

from ..app import App
from ..exceptions import ForkValueError, RemoteBranchValueError
from ..utils.misc import bcolors as bc


@click.command()
@click.argument("source", required=True)
@click.argument("target", required=True)
@click.argument("addon", required=True)
@click.option(
    "--destination",
    help=(
        "Git reference where work will be pushed, "
        "e.g. 'camptocamp/server-tools#16.0-dev'."
    ),
)
@click.option(
    "--source-remote",
    help="Git remote from which source branch is fetched, e.g. 'origin'.",
)
@click.option(
    "--target-remote",
    help="Git remote from which target branch is fetched, e.g. 'origin'.",
)
@click.option(
    "--destination-remote",
    help="Git remote to which destination branch is pushed, e.g. 'camptocamp'.",
)
@click.option("--repo-name", help="Repository name, e.g. 'server-tools'.")
@click.option("--verbose", is_flag=True, help="List the commits of Pull Requests.")
@click.option(
    "--non-interactive", is_flag=True, help="Disable all interactive prompts."
)
@click.option("--dry-run", is_flag=True, help="Print results, no nothing.")
@click.option(
    "--skip-dest-branch-recreate",
    is_flag=True,
    help="Avoid recreating the destination branch "
    "if existing when porting PRs (and asking for it)",
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
    addon: str,
    source: str,
    target: str,
    destination: str,
    source_remote: str,
    target_remote: str,
    destination_remote: str,
    repo_name: str,
    verbose: bool,
    non_interactive: bool,
    skip_dest_branch_recreate: bool,
    output: str,
    fetch: bool,
    no_cache: bool,
    clear_cache: bool,
    dry_run: bool,
):
    """Migrate ADDON from SOURCE to TARGET or list Pull Requests to port
        if ADDON already exists on TARGET.

        E.g.:

        $ oca-port OCA/server-tools#14.0 OCA/server-tools#16.0 auditlog

        Migration:

            Assist the user in the migration of the addon, following the OCA guidelines.

        Port of Pull Requests (missing commits):

            The PRs are found from SOURCE commits that do not exist in TARGET.
    The user will be asked if he wants to port them.

        To start the migration process, the `--destination` option must be provided in
    order to push the resulting branch on the user's remote.
    """
    try:
        app = App(
            addon=addon,
            source=source,
            target=target,
            destination=destination,
            source_remote=source_remote,
            target_remote=target_remote,
            destination_remote=destination_remote,
            skip_dest_branch_recreate=skip_dest_branch_recreate,
            repo_name=repo_name,
            verbose=verbose,
            non_interactive=non_interactive,
            output=output,
            fetch=fetch,
            no_cache=no_cache,
            clear_cache=clear_cache,
            dry_run=dry_run,
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
