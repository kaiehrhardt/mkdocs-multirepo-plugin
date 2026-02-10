# GitLab Groups Example

This is an example of using the `mkdocs-multirepo-plugin` with GitLab groups support.

## What is GitLab Groups Support?

The GitLab groups feature allows you to automatically import all repositories from a GitLab group (and optionally its subgroups) into your MkDocs documentation site.

Instead of listing each repository individually, you can simply specify the group URL and let the plugin discover and import all repositories automatically.

## How to Use

1. **Configure your mkdocs.yml**

   See the `mkdocs.yml` file in this directory for various configuration examples.

2. **Set up authentication (for private groups)**

   ```bash
   export GitlabAccessToken="your-personal-access-token"
   ```

3. **Build or serve your documentation**

   ```bash
   mkdocs serve
   # or
   mkdocs build
   ```

## Features

- 🔍 **Automatic Discovery**: Automatically finds all repositories in a GitLab group
- 🌳 **Subgroups Support**: Recursively includes repositories from subgroups
- 🎯 **Filtering**: Filter repositories by branch, name pattern, or archive status
- 🏢 **Self-Hosted GitLab**: Works with both gitlab.com and self-hosted instances
- 🔐 **Authentication**: Supports both personal access tokens and CI job tokens
- 📁 **Organization**: Organize imported repos under custom navigation paths

## Benefits

- **Less Maintenance**: No need to update configuration when new repos are added to the group
- **Consistency**: All documentation follows the same structure and organization
- **Scalability**: Perfect for organizations with many documentation repositories
- **Flexibility**: Combine group imports with individual repository imports

## Filter Examples

### By Branch
Only include repositories with a specific default branch:
```yaml
groups:
  - gitlab_group: 'https://gitlab.com/my-org/docs'
    branch: 'main'
```

### By Name Pattern
Only include repositories matching a regex pattern:
```yaml
groups:
  - gitlab_group: 'https://gitlab.com/my-org/docs'
    name_pattern: '^docs-.*'
```

### Include Archived
By default, archived repositories are excluded. Enable them with:
```yaml
groups:
  - gitlab_group: 'https://gitlab.com/my-org/docs'
    include_archived: true
```

### Exclude Subgroups
Only import repositories directly in the group, not from subgroups:
```yaml
groups:
  - gitlab_group: 'https://gitlab.com/my-org/docs'
    include_subgroups: false
```

## Learn More

See the main README.md for complete documentation on all available options.
