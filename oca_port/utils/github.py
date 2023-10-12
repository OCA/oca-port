# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import re

import requests

from .git import PullRequest

GITHUB_API_URL = "https://api.github.com"


class GitHub:
    def __init__(self, token=None):
        self.token = token

    def request(self, url: str, method: str = "get", params=None, json=None):
        """Request GitHub API."""
        headers = {"Accept": "application/vnd.github.groot-preview+json"}
        if self.token:
            headers.update({"Authorization": f"token {self.token}"})
        full_url = "/".join([GITHUB_API_URL, url])
        kwargs = {"headers": headers}
        if json:
            kwargs.update(json=json)
        if params:
            kwargs.update(params=params)
        response = getattr(requests, method)(full_url, **kwargs)
        if not response.ok:
            raise RuntimeError(response.text)
        return response.json()

    def get_original_pr(
        self, from_org: str, repo_name: str, branch: str, commit_sha: str
    ):
        """Return original GitHub PR data of a commit."""
        gh_commit_pulls = self.request(
            f"repos/{from_org}/{repo_name}/commits/{commit_sha}/pulls"
        )
        gh_commit_pull = [
            data
            for data in gh_commit_pulls
            if (
                data["base"]["ref"] == branch
                and data["base"]["repo"]["full_name"] == f"{from_org}/{repo_name}"
            )
        ]
        return gh_commit_pull and gh_commit_pull[0] or {}

    def search_migration_pr(
        self, from_org: str, repo_name: str, branch: str, addon: str
    ):
        """Return an existing migration PR (if any) of `addon` for `branch`."""
        # NOTE: If the module we are looking for is named 'a_b' and the PR title is
        # written 'a b', we won't get any result, but that's better than returning
        # the wrong PR to the user.
        # NOTE 2: we first search for open PRs, then closed ones (could be closed
        # automatically by bots for inactivity)
        repo = f"{from_org}/{repo_name}"
        for pr_state in ("open", "unmerged"):
            prs = self.request(
                f"search/issues?q=is:pr+is:{pr_state}+repo:{repo}"
                f"+base:{branch}+in:title++mig+{addon}"
            )
            for pr in prs.get("items", {}):
                # Searching for 'a' on GitHub could return a result containing 'a_b'
                # so we check the result for the exact module name to return a relevant PR.
                if self._addon_in_text(addon, pr["title"]):
                    return PullRequest(
                        number=pr["number"],
                        url=pr["html_url"],
                        author=pr["user"]["login"],
                        title=pr["title"],
                        body=pr["body"],
                    )

    def _addon_in_text(self, addon: str, text: str):
        """Return `True` if `addon` is present in `text`."""
        return any(addon == term for term in re.split(r"\W+", text))
