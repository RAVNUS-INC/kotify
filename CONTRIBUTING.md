# Contributing to kotify

Thanks for your interest in contributing!

## Setup

```bash
git clone https://github.com/RAVNUS-INC/kotify.git
cd kotify
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## Code Style

- Python 3.12+ syntax
- Type hints required
- `ruff check` + `ruff format` before committing
- Korean and English comments both welcome

## Testing

- All new features must include tests
- Run `pytest` before submitting PR
- Test coverage should not regress

## Pull Request Process

1. Fork the repo
2. Create a feature branch
3. Make your changes with tests
4. Ensure tests pass
5. Open a PR with clear description

## Reporting Issues

Use GitHub Issues. Include:
- Steps to reproduce
- Expected vs actual behavior
- Environment (OS, Python version)
- Relevant logs (sanitized)

## Security

For security vulnerabilities, please email security@example.com instead of opening a public issue.
