"""GitLab API integration for fetching group repositories."""

import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    requests = None

from .util import log


class GitLabException(Exception):
    """Base exception for GitLab API errors."""
    pass


class GitLabGroupNotFoundException(GitLabException):
    """Raised when a GitLab group is not found."""
    pass


class GitLabAuthException(GitLabException):
    """Raised when GitLab authentication fails."""
    pass


class GitLabAPIException(GitLabException):
    """Raised when GitLab API returns an error."""
    pass


def get_gitlab_token() -> Optional[str]:
    """
    Get GitLab access token from environment variables.

    Tries in order:
    1. GitlabAccessToken (for local development and general CI/CD)
    2. GitlabCIJobToken (automatically available in GitLab CI)

    Returns:
        The access token if found, None otherwise.
    """
    return os.environ.get('GitlabAccessToken') or os.environ.get('GitlabCIJobToken')


def parse_gitlab_group_url(url: str) -> Tuple[str, str]:
    """
    Parse a GitLab group URL to extract the host and group path.

    Args:
        url: GitLab group URL (e.g., 'https://gitlab.com/my-group/subgroup')

    Returns:
        Tuple of (gitlab_host, group_path)
        Example: ('https://gitlab.com', 'my-group/subgroup')

    Raises:
        ValueError: If the URL is invalid or doesn't contain a group path.
    """
    parsed = urlparse(url)

    if not parsed.scheme:
        # If no scheme, assume https://
        url = f"https://{url}"
        parsed = urlparse(url)

    if not parsed.netloc:
        raise ValueError(f"Invalid GitLab group URL: {url}")

    gitlab_host = f"{parsed.scheme}://{parsed.netloc}"
    group_path = parsed.path.strip('/')

    if not group_path:
        raise ValueError(f"GitLab group URL must contain a group path: {url}")

    return gitlab_host, group_path


def _get_group_id(gitlab_host: str, group_path: str, token: Optional[str]) -> int:
    """
    Get the GitLab group ID from the group path.

    Args:
        gitlab_host: GitLab instance URL (e.g., 'https://gitlab.com')
        group_path: Group path (e.g., 'my-group/subgroup')
        token: GitLab access token (optional for public groups)

    Returns:
        The group ID

    Raises:
        GitLabGroupNotFoundException: If the group is not found
        GitLabAuthException: If authentication fails
        GitLabAPIException: If the API returns an error
    """
    if requests is None:
        raise GitLabAPIException(
            "The 'requests' library is required for GitLab group support. "
            "Install it with: pip install requests"
        )

    headers = {}
    if token:
        headers['PRIVATE-TOKEN'] = token

    # URL encode the group path
    import urllib.parse
    encoded_group_path = urllib.parse.quote(group_path, safe='')

    url = f"{gitlab_host}/api/v4/groups/{encoded_group_path}"

    try:
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 404:
            raise GitLabGroupNotFoundException(
                f"GitLab group not found: {group_path}\n"
                f"Make sure the group exists and you have access to it."
            )
        elif response.status_code == 401:
            raise GitLabAuthException(
                f"GitLab authentication failed for group: {group_path}\n"
                f"Make sure you have set the GitlabAccessToken or GitlabCIJobToken environment variable."
            )
        elif response.status_code != 200:
            raise GitLabAPIException(
                f"GitLab API error (status {response.status_code}): {response.text}"
            )

        group_data = response.json()
        return group_data['id']

    except (GitLabGroupNotFoundException, GitLabAuthException, GitLabAPIException):
        # Re-raise our custom exceptions
        raise
    except Exception as e:
        # Catch all other exceptions (including RequestException if requests is real)
        raise GitLabAPIException(f"Failed to connect to GitLab API: {str(e)}")


def _fetch_group_projects(
    gitlab_host: str,
    group_id: int,
    token: Optional[str],
    include_subgroups: bool = True
) -> List[Dict]:
    """
    Fetch all projects from a GitLab group.

    Args:
        gitlab_host: GitLab instance URL
        group_id: GitLab group ID
        token: GitLab access token (optional for public groups)
        include_subgroups: If True, includes projects from subgroups

    Returns:
        List of project dictionaries with keys: id, name, path, http_url_to_repo,
        default_branch, archived

    Raises:
        GitLabAPIException: If the API returns an error
    """
    if requests is None:
        raise GitLabAPIException(
            "The 'requests' library is required for GitLab group support. "
            "Install it with: pip install requests"
        )

    headers = {}
    if token:
        headers['PRIVATE-TOKEN'] = token

    url = f"{gitlab_host}/api/v4/groups/{group_id}/projects"
    params = {
        'per_page': 100,
        'page': 1,
        'include_subgroups': str(include_subgroups).lower()
    }

    all_projects = []

    try:
        while True:
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 401:
                raise GitLabAuthException(
                    "GitLab authentication failed when fetching projects.\n"
                    "Make sure you have set the GitlabAccessToken or GitlabCIJobToken environment variable."
                )
            elif response.status_code != 200:
                raise GitLabAPIException(
                    f"GitLab API error (status {response.status_code}): {response.text}"
                )

            projects = response.json()
            if not projects:
                break

            all_projects.extend(projects)

            # Check if there are more pages
            if 'x-next-page' not in response.headers or not response.headers['x-next-page']:
                break

            params['page'] += 1

        return all_projects

    except (GitLabAuthException, GitLabAPIException):
        # Re-raise our custom exceptions
        raise
    except Exception as e:
        # Catch all other exceptions (including RequestException if requests is real)
        raise GitLabAPIException(f"Failed to fetch projects from GitLab API: {str(e)}")


def _apply_filters(
    projects: List[Dict],
    branch_filter: Optional[str] = None,
    name_pattern: Optional[str] = None,
    include_archived: bool = False
) -> List[Dict]:
    """
    Apply filters to a list of GitLab projects.

    Args:
        projects: List of project dictionaries from GitLab API
        branch_filter: Only include projects with this default branch
        name_pattern: Regex pattern to match project names/paths
        include_archived: If False, excludes archived projects

    Returns:
        Filtered list of projects
    """
    filtered = projects

    # Filter archived projects
    if not include_archived:
        filtered = [p for p in filtered if not p.get('archived', False)]

    # Filter by branch
    if branch_filter:
        filtered = [p for p in filtered if p.get('default_branch') == branch_filter]

    # Filter by name pattern
    if name_pattern:
        try:
            pattern = re.compile(name_pattern)
            filtered = [
                p for p in filtered
                if pattern.search(p.get('name', '')) or pattern.search(p.get('path', ''))
            ]
        except re.error as e:
            log.warning(f"Invalid regex pattern '{name_pattern}': {e}")

    return filtered


def fetch_gitlab_group_repos(
    group_url: str,
    branch_filter: Optional[str] = None,
    name_pattern: Optional[str] = None,
    include_archived: bool = False,
    include_subgroups: bool = True
) -> List[Dict[str, str]]:
    """
    Fetch all repositories from a GitLab group with optional filtering.

    Args:
        group_url: GitLab group URL (e.g., 'https://gitlab.com/my-group')
        branch_filter: Only include repos with this default branch (optional)
        name_pattern: Regex pattern to filter repo names (optional)
        include_archived: Include archived repositories (default: False)
        include_subgroups: Recursively include subgroups (default: True)

    Returns:
        List of dictionaries with keys:
        - name: Repository name
        - url: Repository clone URL
        - default_branch: Default branch name

    Raises:
        GitLabGroupNotFoundException: If the group is not found
        GitLabAuthException: If authentication fails
        GitLabAPIException: If the API returns an error
    """
    log.info(f"Fetching repositories from GitLab group: {group_url}")

    # Parse the group URL
    gitlab_host, group_path = parse_gitlab_group_url(group_url)

    # Get access token
    token = get_gitlab_token()
    if not token:
        log.info("No GitLab access token found. Only public groups will be accessible.")

    # Get group ID
    group_id = _get_group_id(gitlab_host, group_path, token)

    # Fetch all projects
    projects = _fetch_group_projects(gitlab_host, group_id, token, include_subgroups)

    log.info(f"Found {len(projects)} total repositories in group")

    # Apply filters
    filtered_projects = _apply_filters(projects, branch_filter, name_pattern, include_archived)

    if len(filtered_projects) < len(projects):
        log.info(f"After filtering: {len(filtered_projects)} repositories")

    if not filtered_projects:
        log.warning(f"No repositories found matching the specified filters in group: {group_url}")

    # Convert to simplified format
    repos = []
    for project in filtered_projects:
        repos.append({
            'name': project['path'],  # Use path (slug) as name
            'url': project['http_url_to_repo'],
            'default_branch': project.get('default_branch', 'main')
        })

    return repos
