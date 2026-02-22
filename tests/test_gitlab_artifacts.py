"""Tests for GitLab Artifacts integration."""

import io
import os
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from mkdocs_multirepo_plugin import gitlab_artifacts


class TestGlobPatternMatching(unittest.TestCase):
    """Test glob pattern matching for artifact extraction."""

    def test_match_simple_pattern(self):
        """Test simple glob pattern matching."""
        self.assertTrue(gitlab_artifacts._match_glob_pattern("docs/index.md", "docs/*"))
        self.assertFalse(gitlab_artifacts._match_glob_pattern("src/main.py", "docs/*"))

    def test_match_recursive_pattern(self):
        """Test recursive ** glob pattern."""
        self.assertTrue(
            gitlab_artifacts._match_glob_pattern("public/docs/guide/intro.md", "public/**")
        )
        self.assertTrue(
            gitlab_artifacts._match_glob_pattern("public/index.html", "public/**")
        )
        self.assertFalse(
            gitlab_artifacts._match_glob_pattern("src/main.py", "public/**")
        )

    def test_match_recursive_with_prefix_and_suffix(self):
        """Test ** pattern with prefix and suffix."""
        pattern = "docs/**/*.md"
        self.assertTrue(
            gitlab_artifacts._match_glob_pattern("docs/guide/intro.md", pattern)
        )
        self.assertTrue(
            gitlab_artifacts._match_glob_pattern("docs/api/readme.md", pattern)
        )
        self.assertFalse(
            gitlab_artifacts._match_glob_pattern("docs/index.html", pattern)
        )

    def test_match_exact_file(self):
        """Test exact file matching."""
        self.assertTrue(
            gitlab_artifacts._match_glob_pattern("README.md", "README.md")
        )
        self.assertFalse(
            gitlab_artifacts._match_glob_pattern("docs/README.md", "README.md")
        )


class TestArtifactExtraction(unittest.TestCase):
    """Test artifact ZIP extraction."""

    def create_test_zip(self):
        """Create a test ZIP file in memory."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr("public/index.html", "<html>Test</html>")
            zipf.writestr("public/docs/intro.md", "# Introduction")
            zipf.writestr("public/docs/guide/tutorial.md", "# Tutorial")
            zipf.writestr("public/assets/style.css", "body { margin: 0; }")
            zipf.writestr("build/output.log", "Build log")
        zip_buffer.seek(0)
        return zip_buffer.read()

    def test_extract_all_files_from_directory(self):
        """Test extracting all files from a directory."""
        import tempfile
        zip_data = self.create_test_zip()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir)
            extracted = gitlab_artifacts.extract_artifact_paths(
                zip_data, ["public/**"], dest
            )
            
            # Should extract all files in public/
            self.assertEqual(len(extracted), 4)
            
            # Verify files exist
            self.assertTrue((dest / "public" / "index.html").exists())
            self.assertTrue((dest / "public" / "docs" / "intro.md").exists())

    def test_extract_specific_pattern(self):
        """Test extracting files matching specific pattern."""
        import tempfile
        zip_data = self.create_test_zip()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir)
            extracted = gitlab_artifacts.extract_artifact_paths(
                zip_data, ["public/**/*.md"], dest
            )
            
            # Should only extract markdown files
            self.assertEqual(len(extracted), 2)

    def test_extract_no_matches(self):
        """Test extraction with no matching files."""
        import tempfile
        zip_data = self.create_test_zip()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir)
            extracted = gitlab_artifacts.extract_artifact_paths(
                zip_data, ["nonexistent/**"], dest
            )
            
            # Should return empty list
            self.assertEqual(len(extracted), 0)

    def test_extract_multiple_patterns(self):
        """Test extraction with multiple patterns."""
        import tempfile
        zip_data = self.create_test_zip()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir)
            extracted = gitlab_artifacts.extract_artifact_paths(
                zip_data, ["public/**/*.md", "public/**/*.css"], dest
            )
            
            # Should extract markdown and CSS files
            self.assertEqual(len(extracted), 3)


class TestFindDocsJob(unittest.TestCase):
    """Test automatic documentation job detection."""

    @mock.patch("mkdocs_multirepo_plugin.gitlab_artifacts.requests")
    def test_find_pages_job(self, mock_requests):
        """Test finding 'pages' job."""
        # Mock pipeline response
        pipeline_response = mock.Mock()
        pipeline_response.status_code = 200
        pipeline_response.json.return_value = [{"id": 123}]
        
        # Mock jobs response with 'pages' job
        jobs_response = mock.Mock()
        jobs_response.status_code = 200
        jobs_response.json.return_value = [
            {
                "name": "build",
                "status": "success",
                "artifacts_file": None,
            },
            {
                "name": "pages",
                "status": "success",
                "artifacts_file": {"filename": "artifacts.zip"},
            },
        ]
        
        mock_requests.get.side_effect = [pipeline_response, jobs_response]
        
        job_name = gitlab_artifacts.find_docs_job(
            "https://gitlab.com", 456, "main", "token"
        )
        
        self.assertEqual(job_name, "pages")

    @mock.patch("mkdocs_multirepo_plugin.gitlab_artifacts.requests")
    def test_find_specific_job(self, mock_requests):
        """Test finding a specific job by name."""
        # Mock pipeline response
        pipeline_response = mock.Mock()
        pipeline_response.status_code = 200
        pipeline_response.json.return_value = [{"id": 123}]
        
        # Mock jobs response
        jobs_response = mock.Mock()
        jobs_response.status_code = 200
        jobs_response.json.return_value = [
            {
                "name": "build_docs",
                "status": "success",
                "artifacts_file": {"filename": "artifacts.zip"},
            },
            {
                "name": "pages",
                "status": "success",
                "artifacts_file": {"filename": "artifacts.zip"},
            },
        ]
        
        mock_requests.get.side_effect = [pipeline_response, jobs_response]
        
        job_name = gitlab_artifacts.find_docs_job(
            "https://gitlab.com", 456, "main", "token", job_name="build_docs"
        )
        
        self.assertEqual(job_name, "build_docs")

    @mock.patch("mkdocs_multirepo_plugin.gitlab_artifacts.requests")
    def test_job_not_found(self, mock_requests):
        """Test when no suitable job is found."""
        # Mock pipeline response
        pipeline_response = mock.Mock()
        pipeline_response.status_code = 200
        pipeline_response.json.return_value = [{"id": 123}]
        
        # Mock jobs response with no jobs with artifacts
        jobs_response = mock.Mock()
        jobs_response.status_code = 200
        jobs_response.json.return_value = [
            {
                "name": "build",
                "status": "success",
                "artifacts_file": None,
            },
        ]
        
        mock_requests.get.side_effect = [pipeline_response, jobs_response]
        
        job_name = gitlab_artifacts.find_docs_job(
            "https://gitlab.com", 456, "main", "token"
        )
        
        self.assertIsNone(job_name)


class TestDownloadArtifact(unittest.TestCase):
    """Test artifact download functionality."""

    @mock.patch("mkdocs_multirepo_plugin.gitlab_artifacts.requests")
    def test_download_success(self, mock_requests):
        """Test successful artifact download."""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.content = b"ZIP_DATA"
        mock_requests.get.return_value = mock_response
        
        artifact_data = gitlab_artifacts.download_job_artifact(
            "https://gitlab.com", 123, "main", "pages", "token"
        )
        
        self.assertEqual(artifact_data, b"ZIP_DATA")
        
        # Verify API call
        mock_requests.get.assert_called_once()
        call_args = mock_requests.get.call_args
        self.assertIn("/jobs/artifacts/main/download", call_args[0][0])
        self.assertEqual(call_args[1]["params"]["job"], "pages")

    @mock.patch("mkdocs_multirepo_plugin.gitlab_artifacts.requests")
    def test_download_not_found(self, mock_requests):
        """Test artifact not found error."""
        mock_response = mock.Mock()
        mock_response.status_code = 404
        mock_requests.get.return_value = mock_response
        
        with self.assertRaises(gitlab_artifacts.GitLabArtifactNotFoundException):
            gitlab_artifacts.download_job_artifact(
                "https://gitlab.com", 123, "main", "nonexistent", "token"
            )

    @mock.patch("mkdocs_multirepo_plugin.gitlab_artifacts.requests")
    def test_download_auth_failed(self, mock_requests):
        """Test authentication failure."""
        mock_response = mock.Mock()
        mock_response.status_code = 401
        mock_requests.get.return_value = mock_response
        
        with self.assertRaises(gitlab_artifacts.GitLabAuthException):
            gitlab_artifacts.download_job_artifact(
                "https://gitlab.com", 123, "main", "pages", None
            )


if __name__ == "__main__":
    unittest.main()
