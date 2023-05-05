# Copyright 2022 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)

import os

import requests

GITHUB_API_URL = "https://api.github.com"


def request(url, method="get", params=None, json=None):
    """Request GitHub API."""
    headers = {"Accept": "application/vnd.github.groot-preview+json"}
    if os.environ.get("GITHUB_TOKEN"):
        token = os.environ.get("GITHUB_TOKEN")
        headers.update({"Authorization": f"token {token}"})
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


def get_original_pr(upstream_org: str, repo_name: str, branch: str, commit_sha: str):
    """Return original GitHub PR data of a commit."""
    gh_commit_pulls = request(
        f"repos/{upstream_org}/{repo_name}/commits/{commit_sha}/pulls"
    )
    gh_commit_pull = [
        data
        for data in gh_commit_pulls
        if (
            data["base"]["ref"] == branch
            and data["base"]["repo"]["full_name"] == f"{upstream_org}/{repo_name}"
        )
    ]
    return gh_commit_pull and gh_commit_pull[0] or {}
