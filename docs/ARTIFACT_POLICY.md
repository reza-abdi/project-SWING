# Source artifacts and binary handling

The supplied archive is the reference for original application files. Curated datasets and pretrained models are required for source-equivalent inference; do not replace them with production mocks or omit them silently. Record each imported file's source path, size, and SHA-256 digest, and compare the destination copy with the archive before commit. Document any transformation or exclusion in `docs/PRESERVATION_MATRIX.md`.

The current archive has no individual application file larger than 10 MiB. Git LFS is not installed in the local environment, so the initial import uses ordinary Git objects and no LFS pointer files. Reassess this choice before adding a file near GitHub's object limit or growing the repository substantially; any later LFS use requires a working local client, configured repository, and verified CI clone. The `.gitattributes` rules keep binary and curated CSV bytes unchanged by line-ending conversion.

Do not execute, unpickle, or deserialize model checkpoints, `training_dataset.pkl`, or the supplied FAISS pickle/index while inventorying the archive. Treat them as untrusted until their hashes and provenance are reviewed. Prefer rebuilding derived indexes from the authorized PDF; if a verified binary artifact must be loaded, restrict it to a controlled inference environment. A matching hash proves preservation of supplied bytes, not that their contents are safe.

The archive's `.git/`, `node_modules/`, runtime databases, caches, temporary reports, and credentials are outside the preservation set. User confirmation permits public redistribution of the supplied materials in this repository; retain identifiable source attributions and any applicable third-party notices.
