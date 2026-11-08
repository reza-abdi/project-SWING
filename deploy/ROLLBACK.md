# Backup and rollback

Project SWING is a simulator. These steps only restore software and simulation state; they do not interact with grid equipment.

## Before an upgrade

1. Record the running image tag and source revision.
2. Quiesce writes by placing the authenticated gateway in maintenance mode and stopping the `agent` and `twin` services.
3. Make a consistent SQLite backup from the `swing-state` volume. With the stack stopped, mount the volume into a trusted SQLite tools container and run `sqlite3 /state/events.sqlite '.backup /backup/events.sqlite'`. Keep the backup outside the Compose volume and restrict access.
4. Record the backup checksum and verify it with `sqlite3 /backup/events.sqlite 'PRAGMA integrity_check;'` (expect `ok`). Back up the protected `.env` and TLS material through the secret manager, not into the repository.

## Roll back

Set `SWING_IMAGE_TAG` to the prior immutable tag and redeploy with `docker compose up -d --no-build`. Check both health endpoints, authenticated API behavior, browser assets, and event-store readability before reopening writes. Keep the failed image and logs for diagnosis.

If the schema or simulation state must also be restored, stop all services, preserve the current volume as a separate forensic copy, restore the verified SQLite backup into `swing-state`, then start the pinned prior release. Never restore a database while a service has it open. Do not delete a named volume as a routine rollback step.

## Recovery limits

The SQLite design is for co-located single-host services. Do not mount this database over NFS or share it across hosts; use a deliberately designed network database before multi-host operation. The current stack does not include an automated backup job or a tested live rollback. Record the actual drill date, revision, and integrity result in the deployment report after exercising this procedure in an authorized staging environment.
