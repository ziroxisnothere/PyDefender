<!-- Thank you for contributing to PyDefender! Please fill out this template. -->

## Description

<!-- What does this pull request change, and why? Link related issues here, e.g. "Fixes #12". -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would break existing functionality)
- [ ] Documentation update
- [ ] Build / CI / packaging change
- [ ] Refactor (no functional changes)

## How was it tested?

<!-- Describe how you verified your change. Example:
     python -m pytest tests/ -v
     pydefender obfuscate app.py --level 3 && python app_protected.py -->

## Checklist

- [ ] My code follows the existing style of the project (standard library only, no new dependencies)
- [ ] I added or updated tests that prove my fix or feature works
- [ ] All tests pass locally: `python -m pytest tests/ -v`
- [ ] The CLI still works: `pydefender --help`
- [ ] Obfuscated output stays behavior-identical (protected files run like the originals)
- [ ] If packaging metadata changed: `python -m build` and `python -m twine check dist/*` pass
- [ ] I updated the README and docstrings where needed
- [ ] I did NOT commit secrets, tokens, credentials, build artifacts (`dist/`, `build/`) or `.venv/`

## Additional notes

<!-- Anything reviewers should pay special attention to. -->
