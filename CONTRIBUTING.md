# Contributing to VERA

First off, thank you for considering contributing to VERA! 

VERA is the secure, observable kernel for production-grade AI agents. Whether you're fixing a bug, writing documentation, adding a core plugin, or improving performance, your contributions are highly welcome.

## Getting Started

We use [`uv`](https://github.com/astral-sh/uv) to manage our Python environment and dependencies. This ensures fast, reliable, and deterministic project setups.

### Environment Setup

1. **Fork and clone** the repository:
   ```bash
   git clone https://github.com/<your-username>/vera.git
   cd vera
   ```

2. **Setup your environment** using `uv`:
   ```bash
   # Sync dependencies and create a virtual environment
   uv sync
   
   # Activate the environment
   source .venv/bin/activate
   ```

3. **Verify the installation** by running the tests or invoking the CLI:
   ```bash
   vera --help
   ```

## Development Workflow

### Core vs. External Plugins

VERA relies structurally on a flexible plugin system:
- **Core Plugins**: The plugins found in `vera/plugins/` are maintained as part of this main repository. These are vital or widely-applicable tools. You're welcome to submit bug fixes or new features for these core plugins.
- **External Plugins**: If you've built an external, custom, or specialized plugin, it must be located and maintained in its own independent repository. Please do not submit PRs for entirely new domain-specific tools into this core repository. 

### Code Quality & Types

Currently, we do not strictly enforce automated code formatters or linters as blocking steps in CI. However, we expect contributors to:
- Follow the style of the surrounding code for consistency.
- Use explicit type hinting wherever possible. We use `pyright` for type definitions and checking.

### Testing

Our test suite is built on `pytest` and heavily employs `pytest-asyncio` for asynchronous functionality.

- **Test Coverage**: We value stability strongly. When adding a new feature or fixing a bug, please write unit tests to maintain or improve test coverage where possible.
- **Running Tests**: You can easily run the suite using `uv`:

  ```bash
  uv run pytest
  ```

## Branching & Commit Guidelines (Recommended)

To keep the project history clear, comprehensible, and easy to review, please consider following these conventions.

### Branch Naming

Try to name your branches by their intent:
- `feature/<short-description>`: New features or architecture changes.
- `fix/<short-description>`: Bug fixes.
- `docs/<short-description>`: Documentation improvements.
- `chore/<short-description>`: Minor maintenance tasks.

### Commit Messages

We encourage the use of [Conventional Commits](https://www.conventionalcommits.org/). This means starting your commit message with the type of work it includes:
- `feat:` for new capabilities.
- `fix:` for fixing a bug.
- `docs:` for documentation updates.
- `test:` for modifying test files.
- `refactor:` for rearranging code without changing behavior.

*Example*: `feat: add caching mechanism to llm plugin`

## Submitting a Pull Request

1. Prior to submitting the PR, execute the test suite to ensure tests still pass.
2. Give your PR a clear, descriptive title.
3. Include a summary in your PR body explaining *why* the change is necessary and *how* you implemented it.
4. A maintainer will review your code. We value constructive communication, so stay tuned for potential feedback.

Thank you for helping us make the edge of AI reasoning visible, secure, and controllable!
