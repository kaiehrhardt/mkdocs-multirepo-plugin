"""GitLab Artifacts API integration for fetching job artifacts."""

import io
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional
from fnmatch import fnmatch

try:
    import requests
except ImportError:
    requests = None

from .gitlab_api import (
    GitLabAPIException,
    GitLabAuthException,
    GitLabException,
    get_gitlab_token,
    parse_gitlab_group_url,
    _get_group_id,
    _fetch_group_projects,
    _apply_filters,
)
from .util import log


class GitLabArtifactNotFoundException(GitLabException):
    """Raised when a GitLab artifact is not found."""
    pass


def find_docs_job(
    gitlab_host: str,
    project_id: int,
    ref: str,
    token: Optional[str],
    job_name: Optional[str] = None
) -> Optional[str]:
    """
    Find a job that produces documentation artifacts.

    Args:
        gitlab_host: GitLab instance URL
        project_id: GitLab project ID
        ref: Git ref (branch, tag, or commit SHA)
        token: GitLab access token
        job_name: Optional job name to search for

    Returns:
        Job name if found, None otherwise
    """
    if requests is None:
        raise GitLabAPIException(
            "The 'requests' library is required for GitLab artifacts support. "
            "Install it with: pip install requests"
        )

    headers = {}
    if token:
        headers['PRIVATE-TOKEN'] = token

    # Get jobs from the latest pipeline for the ref
    url = f"{gitlab_host}/api/v4/projects/{project_id}/pipelines"
    params = {'ref': ref, 'per_page': 1, 'order_by': 'updated_at', 'sort': 'desc'}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code != 200:
            log.warning(
                f"Failed to fetch pipelines for project {project_id} (status {response.status_code})"
            )
            return None

        pipelines = response.json()
        if not pipelines:
            log.warning(f"No pipelines found for project {project_id} on ref {ref}")
            return None

        pipeline_id = pipelines[0]['id']

        # Get jobs from the pipeline
        jobs_url = f"{gitlab_host}/api/v4/projects/{project_id}/pipelines/{pipeline_id}/jobs"
        jobs_response = requests.get(
            jobs_url, headers=headers, params={'per_page': 100}, timeout=30
        )

        if jobs_response.status_code != 200:
            log.warning(
                f"Failed to fetch jobs for pipeline {pipeline_id} (status {jobs_response.status_code})"
            )
            return None

        jobs = jobs_response.json()

        # Filter to successful jobs with artifacts
        jobs_with_artifacts = [
            j for j in jobs 
            if j.get('status') == 'success' and j.get('artifacts_file')
        ]

        if not jobs_with_artifacts:
            log.warning(f"No successful jobs with artifacts found in pipeline {pipeline_id}")
            return None

        # If job_name is specified, look for exact match
        if job_name:
            matching_jobs = [j for j in jobs_with_artifacts if j['name'] == job_name]
            if matching_jobs:
                return job_name
            log.warning(
                f"Job '{job_name}' not found in project {project_id}. "
                f"Available jobs: {', '.join(j['name'] for j in jobs_with_artifacts)}"
            )
            return None

        # Auto-detect: look for common documentation job names
        common_names = ['pages', 'build_docs', 'docs', 'documentation', 'mkdocs', 'build:docs']
        for name in common_names:
            matching_jobs = [j for j in jobs_with_artifacts if j['name'] == name]
            if matching_jobs:
                log.info(f"Auto-detected documentation job: {name}")
                return name

        # Fallback: use first successful job with artifacts
        fallback_job = jobs_with_artifacts[0]['name']
        log.info(
            f"Using first available job with artifacts: {fallback_job}. "
            f"Other jobs: {', '.join(j['name'] for j in jobs_with_artifacts[1:])}"
        )
        return fallback_job

    except Exception as e:
        log.warning(f"Error finding docs job for project {project_id}: {e}")
        return None


def download_job_artifact(
    gitlab_host: str,
    project_id: int,
    ref: str,
    job_name: str,
    token: Optional[str]
) -> Optional[bytes]:
    """
    Download artifact from a GitLab CI/CD job.

    Args:
        gitlab_host: GitLab instance URL
        project_id: GitLab project ID
        ref: Git ref (branch, tag, or commit SHA)
        job_name: CI job name that produces the artifact
        token: GitLab access token

    Returns:
        Artifact ZIP file as bytes, or None if download fails

    Raises:
        GitLabArtifactNotFoundException: If the artifact is not found
        GitLabAuthException: If authentication fails
        GitLabAPIException: If the API returns an error
    """
    if requests is None:
        raise GitLabAPIException(
            "The 'requests' library is required for GitLab artifacts support. "
            "Install it with: pip install requests"
        )

    headers = {}
    if token:
        headers['PRIVATE-TOKEN'] = token

    # Download artifact using the artifacts API
    url = f"{gitlab_host}/api/v4/projects/{project_id}/jobs/artifacts/{ref}/download"
    params = {'job': job_name}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=60)

        if response.status_code == 404:
            raise GitLabArtifactNotFoundException(
                f"Artifact not found for job '{job_name}' on ref '{ref}' in project {project_id}. "
                f"Make sure the job exists and has artifacts."
            )
        elif response.status_code == 401:
            raise GitLabAuthException(
                "GitLab authentication failed when downloading artifact. "
                "Make sure you have set the GitlabAccessToken or GitlabCIJobToken environment variable."
            )
        elif response.status_code != 200:
            raise GitLabAPIException(
                f"GitLab API error (status {response.status_code}): {response.text}"
            )

        return response.content

    except (GitLabArtifactNotFoundException, GitLabAuthException, GitLabAPIException):
        # Re-raise our custom exceptions
        raise
    except Exception as e:
        raise GitLabAPIException(f"Failed to download artifact: {str(e)}")


def extract_artifact_paths(
    artifact_zip: bytes,
    glob_patterns: List[str],
    dest_dir: Path
) -> List[Path]:
    """
    Extract files from artifact ZIP that match the given glob patterns.

    Args:
        artifact_zip: Artifact ZIP file as bytes
        glob_patterns: List of glob patterns (e.g., ['docs/**', 'public/**'])
        dest_dir: Destination directory for extracted files

    Returns:
        List of extracted file paths
    """
    extracted_files = []

    try:
        with zipfile.ZipFile(io.BytesIO(artifact_zip)) as zf:
            # Get all file names in the ZIP
            all_files = zf.namelist()

            # Match files against glob patterns
            matched_files = set()
            for pattern in glob_patterns:
                for file_name in all_files:
                    # Support both '**' glob and simple patterns
                    if _match_glob_pattern(file_name, pattern):
                        matched_files.add(file_name)

            if not matched_files:
                log.warning(
                    f"No files matched patterns {glob_patterns} in artifact. "
                    f"Available files: {', '.join(all_files[:10])}"
                    + (f" (and {len(all_files) - 10} more)" if len(all_files) > 10 else "")
                )
                return []

            log.info(f"Extracting {len(matched_files)} files from artifact")

            # Extract matched files
            for file_name in matched_files:
                # Skip directories
                if file_name.endswith('/'):
                    continue

                # Extract the file
                file_path = dest_dir / file_name
                file_path.parent.mkdir(parents=True, exist_ok=True)

                with zf.open(file_name) as source, open(file_path, 'wb') as target:
                    target.write(source.read())

                extracted_files.append(file_path)

    except zipfile.BadZipFile:
        log.error("Downloaded artifact is not a valid ZIP file")
        return []
    except Exception as e:
        log.error(f"Error extracting artifact: {e}")
        return []

    return extracted_files


def _match_glob_pattern(file_name: str, pattern: str) -> bool:
    """
    Match a file name against a glob pattern.

    Supports:
    - Simple patterns: 'docs/*' matches 'docs/index.md'
    - Recursive patterns: 'docs/**' matches 'docs/foo/bar/baz.md'
    - Exact matches: 'docs/index.md'
    """
    # Handle '**' recursive pattern
    if '**' in pattern:
        # Convert '**' to match any number of path segments
        parts = pattern.split('**')
        if len(parts) == 2:
            prefix, suffix = parts
            # Remove trailing/leading slashes
            prefix = prefix.rstrip('/')
            suffix = suffix.lstrip('/')

            # Check prefix
            if prefix and not file_name.startswith(prefix):
                return False

            # Check suffix
            if suffix and not file_name.endswith(suffix):
                # If suffix doesn't end with specific file, check path contains it
                if '/' in suffix or '.' in suffix:
                    return suffix in file_name
                return False

            return True

    # Use fnmatch for simple glob patterns
    return fnmatch(file_name, pattern)


def fetch_artifact_group_repos(
    gitlab_group: str,
    branch: Optional[str] = None,
    job_name: Optional[str] = None,
    artifact_path: str = "public/**",
    name_pattern: Optional[str] = None,
    exclude_pattern: Optional[str] = None,
    include_archived: bool = False,
    include_subgroups: bool = True,
    exclude_subgroups: Optional[List[str]] = None,
    temp_dir: Optional[Path] = None
) -> Dict[str, Path]:
    """
    Fetch artifacts from all projects in a GitLab group.

    Args:
        gitlab_group: GitLab group URL
        branch: Branch to fetch artifacts from (default: project's default branch)
        job_name: CI job name (optional, will auto-detect if not specified)
        artifact_path: Glob pattern for files to extract from artifact
        name_pattern: Regex pattern to filter project names
        exclude_pattern: Regex pattern to exclude project names
        include_archived: Include archived projects
        include_subgroups: Recursively include subgroups
        exclude_subgroups: List of subgroup paths to exclude
        temp_dir: Temporary directory for extracted artifacts

    Returns:
        Dictionary mapping project names to their extracted artifact directories
    """
    log.info(f"Fetching artifacts from GitLab group: {gitlab_group}")

    # Parse the group URL
    gitlab_host, group_path = parse_gitlab_group_url(gitlab_group)

    # Get access token
    token = get_gitlab_token()
    if not token:
        log.warning(
            "No GitLab access token found. Artifact download will likely fail. "
            "Set GitlabAccessToken or GitlabCIJobToken environment variable."
        )

    # Get group ID
    group_id = _get_group_id(gitlab_host, group_path, token)

    # Fetch all projects
    projects = _fetch_group_projects(gitlab_host, group_id, token, include_subgroups)

    log.info(f"Found {len(projects)} total projects in group")

    # Apply filters
    filtered_projects = _apply_filters(
        projects,
        None,  # Don't filter by branch here - we use it for artifact download
        name_pattern,
        exclude_pattern,
        include_archived,
        exclude_subgroups
    )

    if len(filtered_projects) < len(projects):
        log.info(f"After filtering: {len(filtered_projects)} projects")

    if not filtered_projects:
        log.warning(f"No projects found matching the specified filters in group: {gitlab_group}")
        return {}

    # Parse artifact path patterns
    artifact_patterns = artifact_path.split(',') if ',' in artifact_path else [artifact_path]
    artifact_patterns = [p.strip() for p in artifact_patterns]

    # Download artifacts from each project
    artifact_dirs = {}
    successful_downloads = 0
    failed_downloads = 0

    for project in filtered_projects:
        project_id = project['id']
        project_name = project['path']
        ref = branch or project.get('default_branch', 'main')

        log.info(f"Processing project: {project_name} (ref: {ref})")

        try:
            # Find the documentation job
            detected_job_name = find_docs_job(gitlab_host, project_id, ref, token, job_name)

            if not detected_job_name:
                log.warning(f"No suitable job found for project {project_name}, skipping")
                failed_downloads += 1
                continue

            # Download artifact
            artifact_data = download_job_artifact(
                gitlab_host, project_id, ref, detected_job_name, token
            )

            if not artifact_data:
                log.warning(f"Failed to download artifact for project {project_name}, skipping")
                failed_downloads += 1
                continue

            # Create temporary directory for this project
            project_temp_dir = temp_dir / project_name
            project_temp_dir.mkdir(parents=True, exist_ok=True)

            # Extract artifact files
            extracted_files = extract_artifact_paths(
                artifact_data, artifact_patterns, project_temp_dir
            )

            if extracted_files:
                artifact_dirs[project_name] = project_temp_dir
                successful_downloads += 1
                log.info(
                    f"Successfully extracted {len(extracted_files)} files from {project_name}"
                )
            else:
                log.warning(f"No files extracted from artifact for project {project_name}")
                failed_downloads += 1

        except GitLabArtifactNotFoundException as e:
            log.warning(f"Artifact not found for project {project_name}: {e}")
            failed_downloads += 1
            continue
        except (GitLabAuthException, GitLabAPIException) as e:
            log.error(f"GitLab API error for project {project_name}: {e}")
            failed_downloads += 1
            continue
        except Exception as e:
            log.error(f"Unexpected error processing project {project_name}: {e}")
            failed_downloads += 1
            continue

    log.info(
        f"Artifact download complete: {successful_downloads} successful, {failed_downloads} failed"
    )

    return artifact_dirs
