# Contributing to Project Moah

Thanks for helping. Contributions of every size are welcome: bug reports, ideas, documentation, translations and code.

## Report a bug

1. Search the [existing issues](https://github.com/Namache/project-moah/issues) first. If one matches, add what you know there instead of opening a new one.
2. Open a [bug report](https://github.com/Namache/project-moah/issues/new?template=bug_report.yml) with the steps that cause it, what you expected, and your diagnostic report (**Settings → Diagnostics → Copy diagnostic report**).
3. Remove anything personal before you post: names in folder paths, project content, tokens.

## Suggest an idea

Open a [feature request](https://github.com/Namache/project-moah/issues/new?template=feature_request.yml). Start with the problem you want solved, then the solution you have in mind.

Moah stays on the user's computer. Ideas that need an account, a cloud service, a remote model or sending data online will be declined.

## Report a security problem

Please don't open a public issue. Report it privately from the repository's **Security** tab with **Report a vulnerability**.

## Send a pull request

1. **Open an issue first** for anything bigger than a small fix, so we agree on the approach before you spend time on it.
2. **Fork** the repository and create a branch from `main`.
3. **Set up** the app with the [development guide](docs/DEVELOPMENT.md).
4. **Keep it focused:** one fix or feature per pull request, with tests for what you changed.
5. **Double-check before you open it:**
   - `./scripts/check.sh` passes (backend tests and lint, frontend types, tests and build).
   - You tried the change in the running app.
   - You read your whole diff and understand every line, including code an AI assistant wrote for you.
   - No secrets, personal data or unrelated files are included.
6. **Open the pull request** against `main`. Say what changed and why, and link the issue it closes (`Fixes #12`).

Every pull request is reviewed before it is merged, and the automatic checks must pass.

## Ground rules

- **Local only.** The app makes no network calls: no telemetry, no update checks, no cloud services, no remote models.
- **Both languages.** Interface text goes through `t()` and needs a Russian entry in `frontend/src/locales/ru.ts`; the tests list anything missing. If you don't speak Russian, add your best attempt and say so in the pull request.
- **Code rules.** Follow the [rules for changes](docs/DEVELOPMENT.md#rules-for-changes): project isolation, migrations with a downgrade, locks respected everywhere.
- **Be kind.** Assume good intent and keep feedback about the work, not the person.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
