# Code signing policy

The Windows installer is not code-signed yet. Signing through the [SignPath Foundation](https://signpath.org), which signs open-source projects for free, is planned.

- **Builds:** only files built by this repository's public [GitHub Actions workflow](.github/workflows/desktop.yml) from its own source get signed. Nothing built on a personal computer is signed.
- **Authors and reviewers:** the repository owner, [Namache](https://github.com/Namache). Every outside contribution (pull request) is reviewed by the owner before it is merged.
- **Approvers:** the repository owner approves every signing request.
- **Privacy:** this program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.
