# Execution ledger

Plan: ../docs/superpowers/plans/2026-10-19-bc2-launcher-and-site.md
User approved native execution, no subagents, 19.10.2026.

Ruling: new project has its own Git repository at the approved community/ path,
branch codex/bc2-launcher; no worktree of the unrelated monorepo is created.
Ruling: user explicitly requested no additional agents; final review will be
performed as a separate self-review, without delegation.
Pre-flight: Task 1 Release/Asset -> Tasks 2/3 agree; Task 3 check/prepare_launch
-> Task 4 model agree; Task 5 publishes exact assets used by Task 1.
External publishing: local gh credential is invalid. GitHub connector can edit
existing repositories but exposes no repository/release creation operation.
Continue local implementation; resolve publication after a reviewable build.

Task 1: RED missing manifest module -> GREEN 14 tests.
Task 2: RED missing transaction module -> GREEN filesystem tests. Temp-directory
permission failures were sandbox-specific; elevated runs use only disposable test data.
Task 3: RED missing service/release modules -> GREEN signed package round-trip,
mandatory gate, cancellation, old-policy rejection after rollback, and safe fallback.
Task 4: pure UI-state tests pass; manual GUI/game tests remain with the user.
Ruling: add raw.githubusercontent.com as a signed-policy fallback so initial testing
does not depend on website DNS readiness. TLS, signature and revision checks are
unchanged; invalid signatures never trigger fallback. Cost: GitHub remains a dependency.
Ruling: core installation API is install_bytes rather than apply_release; downloaded
files are verified by service, and the transaction accepts exactly two byte buffers.
Ruling: native execution instruction overrides skill's fresh-agent review; perform
a separate security self-review without spawning any agents.
GitHub CLI login restored by user; repository RinatBy/bc2-community created.
Initial Windows build succeeded; packaging test does not start Qt or a game.

Final self-review: reviewed five Review Focus classes. Added explicit Windows
reparse-attribute test without requiring junction privileges. Existing symlink
creation test is skipped only when Windows denies symlink creation.
All 38 tests ran: 37 passed, 1 environment skip; Python compile and JS syntax pass.
Final: fixed public-key binary handling through .gitattributes so Git cannot alter
raw Ed25519 public bytes with line-ending conversion. No game or GUI was launched.

Task 1: complete; 14/14 tests passed (manifest and network). Task 2: implemented; 23 tests passed, one symlink test skipped because Windows privilege is unavailable. Ruling: run filesystem tests outside sandbox because Python tempfile directories deny access inside it; tests still use only temporary fake files. Dependencies installed in project .venv; lock file generated. Task 3: tests written, expected missing-module RED observed.

Publication update: automatic review rejected public release of supplied DLL/INI/client ZIP. No release or binary assets were uploaded. User requested launcher-only closed distribution instead. Public source repository contains no supplied DLL or game INI, only public signed metadata pointing to unavailable assets. Real authorization backend is a new requirement; invitation-code vs unlisted-download choice requested. Website download links reverted to placeholders to avoid broken/public client-file links. GitHub Pages workflow succeeded; domain is associated, but DNS bc2.uplay2.ru still points to 87.249.43.129, not GitHub Pages.

User explicitly approved public access after discussing closed distribution; DLL/INI/ZIP publication authorized. Release 0.1.0 assets uploaded; GitHub server digests match local files. Final fix pass: unsupported-new-version replay guard, parallel launch/update lock, and changed-INI protection reproduced RED then passed GREEN. Suite: 41 tests, 40 pass, one Windows symlink privilege skip. New binary 0.1.1 compiled; packaged self-test validates resources without GUI. Website DNS deferred by user. Public source and test releases are authorized.

Task 5: Windows 0.1.1 ZIP uploaded; GitHub computed digest matches local SHA-256. Site deployment succeeded; custom-domain DNS is explicitly deferred by user. Live HTTPS smoke passed against public revision 1: signature, downloads, installation, settings preservation and rollback verified on a temporary fake game; no GUI/game executed. Policy revision 2 now requires launcher 0.1.1 and references unchanged already uploaded client assets. Full suite: 42 tests run, 41 passed, 1 skipped (symlink creation privilege); explicit reparse-attribute test passed. Final review is self-review per user's no-agent instruction. No unresolved critical/important findings. Signed-channel fallback and standalone Git workspace rulings retained above.
