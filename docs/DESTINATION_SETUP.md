# Destination and source boundary

- Destination: `reza-abdi/project-SWING`, public GitHub repository, `main` branch.
- The checked out `main` branch and GitHub `main` both began at commit `1d4a74918ac42b08384c93ae2cda38ddc5f3a24b` before reconstruction.
- The destination initially contained only `LICENSE` and `README.md`, and its working tree was clean.
- The supplied `Project_SWING.zip` remains outside this repository and is reference material. Its entries were checked for absolute paths, parent traversal, and symlinks before extraction; none were found.
- Import only reviewed application files. Exclude the archive's `.git/`, `node_modules/`, caches, generated databases, and local secrets. Never overwrite unrelated destination work.
- Preserve the destination's existing history. Make ordinary, verified commits in dependency order without synthetic timestamps or empty changes. Do not force push.
- The repository owner confirmed that the supplied code, data, images, regulatory PDF, and model files may be published in this public repository. Retain applicable third-party notices and provenance during import.

GitHub's connected repository metadata confirmed the remote identity, public visibility, `main` branch, and write permission. Direct shell access to `github.com` was unavailable during initial verification, so remote synchronization must use an authorized connected path or wait until Git transport is available. Local commits must never be described as pushed unless the remote branch is verified at the same commit.
