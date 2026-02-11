"""Tests for GitLab API integration."""

import os
import unittest
from unittest import mock

from mkdocs_multirepo_plugin import gitlab_api


class TestGitLabURLParsing(unittest.TestCase):
    """Test GitLab group URL parsing."""

    def test_parse_gitlab_com_url(self):
        """Test parsing gitlab.com URLs."""
        host, path = gitlab_api.parse_gitlab_group_url("https://gitlab.com/my-group")
        self.assertEqual(host, "https://gitlab.com")
        self.assertEqual(path, "my-group")

    def test_parse_gitlab_com_url_with_subgroup(self):
        """Test parsing gitlab.com URLs with subgroups."""
        host, path = gitlab_api.parse_gitlab_group_url(
            "https://gitlab.com/my-group/subgroup"
        )
        self.assertEqual(host, "https://gitlab.com")
        self.assertEqual(path, "my-group/subgroup")

    def test_parse_self_hosted_gitlab(self):
        """Test parsing self-hosted GitLab URLs."""
        host, path = gitlab_api.parse_gitlab_group_url(
            "https://gitlab.example.com/organization/team"
        )
        self.assertEqual(host, "https://gitlab.example.com")
        self.assertEqual(path, "organization/team")

    def test_parse_url_without_scheme(self):
        """Test parsing URLs without https:// scheme."""
        host, path = gitlab_api.parse_gitlab_group_url("gitlab.com/my-group")
        self.assertEqual(host, "https://gitlab.com")
        self.assertEqual(path, "my-group")

    def test_parse_url_with_trailing_slash(self):
        """Test parsing URLs with trailing slashes."""
        host, path = gitlab_api.parse_gitlab_group_url("https://gitlab.com/my-group/")
        self.assertEqual(host, "https://gitlab.com")
        self.assertEqual(path, "my-group")

    def test_parse_invalid_url_no_path(self):
        """Test that URLs without group path raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            gitlab_api.parse_gitlab_group_url("https://gitlab.com")
        self.assertIn("must contain a group path", str(cm.exception))

    def test_parse_invalid_url_no_host(self):
        """Test that invalid URLs raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            gitlab_api.parse_gitlab_group_url("/my-group")
        self.assertIn("Invalid GitLab group URL", str(cm.exception))


class TestGitLabToken(unittest.TestCase):
    """Test GitLab token retrieval from environment."""

    def setUp(self):
        """Clear environment variables before each test."""
        if "GitlabAccessToken" in os.environ:
            del os.environ["GitlabAccessToken"]
        if "GitlabCIJobToken" in os.environ:
            del os.environ["GitlabCIJobToken"]

    def test_get_token_from_access_token(self):
        """Test getting token from GitlabAccessToken."""
        os.environ["GitlabAccessToken"] = "test-access-token"
        token = gitlab_api.get_gitlab_token()
        self.assertEqual(token, "test-access-token")

    def test_get_token_from_ci_job_token(self):
        """Test getting token from GitlabCIJobToken."""
        os.environ["GitlabCIJobToken"] = "test-ci-token"
        token = gitlab_api.get_gitlab_token()
        self.assertEqual(token, "test-ci-token")

    def test_get_token_access_token_takes_precedence(self):
        """Test that GitlabAccessToken takes precedence over GitlabCIJobToken."""
        os.environ["GitlabAccessToken"] = "access-token"
        os.environ["GitlabCIJobToken"] = "ci-token"
        token = gitlab_api.get_gitlab_token()
        self.assertEqual(token, "access-token")

    def test_get_token_no_token_set(self):
        """Test that None is returned when no token is set."""
        token = gitlab_api.get_gitlab_token()
        self.assertIsNone(token)


class TestApplyFilters(unittest.TestCase):
    """Test project filtering logic."""

    def setUp(self):
        """Set up test projects."""
        self.projects = [
            {
                "id": 1,
                "name": "docs-frontend",
                "path": "docs-frontend",
                "http_url_to_repo": "https://gitlab.com/group/docs-frontend.git",
                "default_branch": "main",
                "archived": False,
            },
            {
                "id": 2,
                "name": "docs-backend",
                "path": "docs-backend",
                "http_url_to_repo": "https://gitlab.com/group/docs-backend.git",
                "default_branch": "main",
                "archived": False,
            },
            {
                "id": 3,
                "name": "legacy-project",
                "path": "legacy-project",
                "http_url_to_repo": "https://gitlab.com/group/legacy-project.git",
                "default_branch": "master",
                "archived": True,
            },
            {
                "id": 4,
                "name": "api-service",
                "path": "api-service",
                "http_url_to_repo": "https://gitlab.com/group/api-service.git",
                "default_branch": "develop",
                "archived": False,
            },
        ]

    def test_filter_no_filters(self):
        """Test that no filters returns all non-archived projects."""
        filtered = gitlab_api._apply_filters(self.projects)
        self.assertEqual(len(filtered), 3)  # All except archived

    def test_filter_include_archived(self):
        """Test including archived projects."""
        filtered = gitlab_api._apply_filters(self.projects, include_archived=True)
        self.assertEqual(len(filtered), 4)  # All projects

    def test_filter_by_branch(self):
        """Test filtering by branch name."""
        filtered = gitlab_api._apply_filters(self.projects, branch_filter="main")
        self.assertEqual(len(filtered), 2)
        for project in filtered:
            self.assertEqual(project["default_branch"], "main")

    def test_filter_by_name_pattern(self):
        """Test filtering by name pattern (regex)."""
        filtered = gitlab_api._apply_filters(self.projects, name_pattern="^docs-.*")
        self.assertEqual(len(filtered), 2)
        for project in filtered:
            self.assertTrue(project["name"].startswith("docs-"))

    def test_filter_combined(self):
        """Test combining multiple filters."""
        filtered = gitlab_api._apply_filters(
            self.projects, branch_filter="main", name_pattern="^docs-.*"
        )
        self.assertEqual(len(filtered), 2)
        for project in filtered:
            self.assertEqual(project["default_branch"], "main")
            self.assertTrue(project["name"].startswith("docs-"))

    def test_filter_invalid_regex(self):
        """Test that invalid regex patterns are handled gracefully."""
        # Should not raise exception, just log warning and ignore pattern
        filtered = gitlab_api._apply_filters(self.projects, name_pattern="[invalid")
        self.assertEqual(len(filtered), 3)  # Returns all non-archived

    def test_filter_exclude_pattern(self):
        """Test filtering with exclude pattern."""
        filtered = gitlab_api._apply_filters(self.projects, exclude_pattern="^legacy-.*")
        self.assertEqual(len(filtered), 3)
        for project in filtered:
            self.assertFalse(project["name"].startswith("legacy-"))

    def test_filter_exclude_multiple_matches(self):
        """Test exclude pattern matching multiple projects."""
        filtered = gitlab_api._apply_filters(self.projects, exclude_pattern="^docs-.*")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "api-service")

    def test_filter_include_and_exclude(self):
        """Test combining include and exclude patterns."""
        # Include docs-* projects but exclude docs-backend
        filtered = gitlab_api._apply_filters(
            self.projects, name_pattern="^docs-.*", exclude_pattern=".*-backend$"
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "docs-frontend")

    def test_filter_exclude_invalid_regex(self):
        """Test that invalid exclude regex patterns are handled gracefully."""
        # Should not raise exception, just log warning and ignore pattern
        filtered = gitlab_api._apply_filters(self.projects, exclude_pattern="[invalid")
        self.assertEqual(len(filtered), 3)  # Returns all non-archived


class TestGitLabAPIIntegration(unittest.TestCase):
    """Test GitLab API integration with mocked responses."""

    @mock.patch("mkdocs_multirepo_plugin.gitlab_api.requests")
    def test_get_group_id_success(self, mock_requests):
        """Test successful group ID retrieval."""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 12345, "name": "my-group"}
        mock_requests.get.return_value = mock_response

        group_id = gitlab_api._get_group_id(
            "https://gitlab.com", "my-group", "test-token"
        )
        self.assertEqual(group_id, 12345)

        # Verify API call
        mock_requests.get.assert_called_once()
        call_args = mock_requests.get.call_args
        self.assertIn("my-group", call_args[0][0])
        self.assertEqual(call_args[1]["headers"]["PRIVATE-TOKEN"], "test-token")

    @mock.patch("mkdocs_multirepo_plugin.gitlab_api.requests")
    def test_get_group_id_not_found(self, mock_requests):
        """Test group not found error."""
        mock_response = mock.Mock()
        mock_response.status_code = 404
        mock_requests.get.return_value = mock_response

        with self.assertRaises(gitlab_api.GitLabGroupNotFoundException):
            gitlab_api._get_group_id("https://gitlab.com", "nonexistent", None)

    @mock.patch("mkdocs_multirepo_plugin.gitlab_api.requests")
    def test_get_group_id_auth_failed(self, mock_requests):
        """Test authentication failure."""
        mock_response = mock.Mock()
        mock_response.status_code = 401
        mock_requests.get.return_value = mock_response

        with self.assertRaises(gitlab_api.GitLabAuthException):
            gitlab_api._get_group_id("https://gitlab.com", "private-group", None)

    @mock.patch("mkdocs_multirepo_plugin.gitlab_api.requests")
    def test_fetch_group_projects_success(self, mock_requests):
        """Test successful project fetching."""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 1,
                "name": "project1",
                "path": "project1",
                "http_url_to_repo": "https://gitlab.com/group/project1.git",
                "default_branch": "main",
                "archived": False,
            },
            {
                "id": 2,
                "name": "project2",
                "path": "project2",
                "http_url_to_repo": "https://gitlab.com/group/project2.git",
                "default_branch": "main",
                "archived": False,
            },
        ]
        mock_response.headers = {}
        mock_requests.get.return_value = mock_response

        projects = gitlab_api._fetch_group_projects(
            "https://gitlab.com", 12345, "test-token"
        )
        self.assertEqual(len(projects), 2)
        self.assertEqual(projects[0]["name"], "project1")
        self.assertEqual(projects[1]["name"], "project2")

    @mock.patch("mkdocs_multirepo_plugin.gitlab_api.requests")
    def test_fetch_group_projects_pagination(self, mock_requests):
        """Test project fetching with pagination."""
        # First page
        mock_response1 = mock.Mock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = [
            {
                "id": 1,
                "name": "project1",
                "path": "project1",
                "http_url_to_repo": "https://gitlab.com/group/project1.git",
                "default_branch": "main",
                "archived": False,
            }
        ]
        mock_response1.headers = {"x-next-page": "2"}

        # Second page
        mock_response2 = mock.Mock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = [
            {
                "id": 2,
                "name": "project2",
                "path": "project2",
                "http_url_to_repo": "https://gitlab.com/group/project2.git",
                "default_branch": "main",
                "archived": False,
            }
        ]
        mock_response2.headers = {}

        mock_requests.get.side_effect = [mock_response1, mock_response2]

        projects = gitlab_api._fetch_group_projects(
            "https://gitlab.com", 12345, "test-token"
        )
        self.assertEqual(len(projects), 2)
        self.assertEqual(mock_requests.get.call_count, 2)

    @mock.patch("mkdocs_multirepo_plugin.gitlab_api.requests")
    @mock.patch("mkdocs_multirepo_plugin.gitlab_api.get_gitlab_token")
    @mock.patch("mkdocs_multirepo_plugin.gitlab_api._get_group_id")
    @mock.patch("mkdocs_multirepo_plugin.gitlab_api._fetch_group_projects")
    def test_fetch_gitlab_group_repos_full_flow(
        self,
        mock_fetch_projects,
        mock_get_group_id,
        mock_get_token,
        mock_requests,
    ):
        """Test the full flow of fetching group repos."""
        # Mock token
        mock_get_token.return_value = "test-token"

        # Mock group ID
        mock_get_group_id.return_value = 12345

        # Mock projects
        mock_fetch_projects.return_value = [
            {
                "id": 1,
                "name": "docs-project",
                "path": "docs-project",
                "http_url_to_repo": "https://gitlab.com/group/docs-project.git",
                "default_branch": "main",
                "archived": False,
            }
        ]

        repos = gitlab_api.fetch_gitlab_group_repos(
            "https://gitlab.com/my-group", branch_filter="main", name_pattern="^docs-.*"
        )

        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0]["name"], "docs-project")
        self.assertEqual(
            repos[0]["url"], "https://gitlab.com/group/docs-project.git"
        )
        self.assertEqual(repos[0]["default_branch"], "main")

        # Verify calls
        mock_get_group_id.assert_called_once_with(
            "https://gitlab.com", "my-group", "test-token"
        )
        mock_fetch_projects.assert_called_once()


if __name__ == "__main__":
    unittest.main()
