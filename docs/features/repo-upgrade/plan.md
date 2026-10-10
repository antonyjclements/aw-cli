# Safe migration implementation plan

1. Replace global copying with the selected source's reviewed fingerprint migrator;
   retain CLI options and add explicit skill-only rollback. Verify custom skill,
   retirement, collision, dry-run and rollback cases using the real helper.
2. Separate noninteractive repository upgrades from interactive initialization.
   Prepare config migration in a disposable repository, verify artifact ownership,
   back up changed files, then apply atomically per file with failure restoration.
3. Preserve the same prepared local/archive source through all migration operations.
   Update the AW shell-to-CLI handoff independently so it cannot refetch a different
   version or recurse through the shell installer.
4. Run focused tests, complete suites, independent safety review, and disposable
   current-AW install/upgrade tests. Record skipped checks and recovery boundaries.

Scope and safety plan reviewed before repository implementation. The user
authorized commits and draft PRs for both repositories on 2026-10-10 after
reviewing the test results and traceability limitation. Merging, release,
deployment, and installation on the user's device remain outside this task.
This plan intentionally changes unsafe overwrite behavior rather than pinning
equivalence to it.
