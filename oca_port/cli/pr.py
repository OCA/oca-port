# Copyright 2023 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import os

import click
import git

from ..exceptions import RemoteBranchValueError
from ..utils.git import Branch
from ..utils.storage import InputStorage


@click.group()
def cli():
    pass


@cli.command()
@click.argument("prs", required=True)
@click.argument("target_branch", required=True)
@click.argument("addon", required=True)
@click.option(
    "--reason",
    default="Nothing to port from PR #{pr_ref}",
    show_default=True,
)
@click.option(
    "--remote",
    default="origin",
    show_default=True,
)
def blacklist(
    prs: str,
    target_branch: str,
    addon: str,
    reason: str,
    remote: str,
):
    """Blacklist one or more PRs"""
    # eg: https://github.com/user/repo/pull/1234 or just the number
    # TODO: validate! Must be URL or ref like `OCA/edi#1`
    pr_refs = [x.strip() for x in prs.split(",") if x.strip()]

    # TODO: we assume you are in the right repo folder when you run this
    repo = git.Repo(os.getcwd())
    if repo.is_dirty(untracked_files=True):
        raise ValueError("changes not committed detected in this repository.")
    # Transform branch strings to Branch objects
    try:
        branch = Branch(repo, target_branch, default_remote=remote)
    except ValueError as exc:
        if exc.args[1] not in repo.remotes:
            raise RemoteBranchValueError(repo.name, exc.args[1]) from exc

    storage = InputStorage(branch, addon)
    for ref in pr_refs:
        storage.blacklist_pr(ref, reason=reason.format(pr_ref=ref))
    if storage.dirty:
        msg = f"oca-port: blacklist PR(s) {', '.join(pr_refs)} for {addon}"
        storage.commit(msg)


if __name__ == "__main__":
    cli()
