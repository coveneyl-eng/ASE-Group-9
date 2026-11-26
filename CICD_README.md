# CI/CD pipeline for ASE-Group-9

```
.github/workflows/ci.yml     checks on every pull request and push to main
.github/workflows/cd.yml     publishes the thin-slice image after main changes
.github/dependabot.yml       weekly update pull requests for actions, pip and Docker
pyproject.toml               ruff and pytest settings
requirements-ci.txt          light dependencies for the tests
tests/test_smoke.py          imports every APIs module and checks load_all.py is valid Python
```

# What the checks do

- **Lint:** finds real code errors.
- **Tests:** runs `pytest`. No database or Kafka needed.
- **Docker:** checks that the thin-slice image still builds.
- **Secret scan:** looks for passwords or API keys in new commits.
- **Publish (main only):** pushes the image to GitHub Container Registry.

# Setup (once, needs repo admin)

1. On GitHub go to Settings, Branches, and add a rule for `main`. Require a pull request, the four checks above, and one review.
2. Go to Settings, Actions, General, and let workflows write packages.

Azure deployment is optional and off by default. We will set the repo variable `AZURE_DEPLOY=true` later, once we have an Azure setup.