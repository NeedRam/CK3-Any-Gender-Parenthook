# AGP v1.1.1

This compatibility patch keeps the published AGP v1.1.0 native DLL bytes and updates only installer/package state to 1.1.1.

This release migrates the Windows x64 native hook to CK3 **1.21.0.3 only**.
AGP v1.0.2 remains the separate release for CK3 1.19.0.6.

## Native runtime

- Replaced old executable signatures and character offsets with a versioned
  profile for the locally installed GOG-marked 1.21.0.3 executable.
- Updated parent and real-parent setters, character creation, pregnancy
  carrier checks, history validation, role reconstruction, and close-family
  parent/grandparent recognition.
- Resolve reconstruction setters from validated call instructions instead of
  retaining obsolete fixed function addresses.
- Reject unknown or ambiguous executable hashes before changing game code.
- Validate unique original instruction contexts and reconstruction continuation
  bytes before allocating and staging every patch.
- Commit staged writes together; stop and restore verified original bytes on
  failure, with explicit rollback-failure logging.
- Preserve a distinct real-parent override when assigning an ordinary parent;
  cover missing-old-parent cases in executable machine-code tests.
- Serialize ordinary father/mother IDs separately through the game's persistent
  reader/writer so distinct real-parent overrides do not consume role markers.

## Installation and maintenance

- Added exact executable-hash build selection to both installer engines, using
  explicit game-directory or executable paths for GOG installations.
- Added schema-v2 manifests, journals, and install state while retaining
  read-only schema-v1 recognition and transactional upgrade migration.
- Preserve existing AGP/UFG recognition, lossless quarantine, rollback, and
  cross-engine uninstall behavior.
- Refreshed disposable history fixtures from 1.21.0.3 vanilla files and
  updated fixture and Dynastic Priority compatibility descriptors.
- Added binary audits, native stub/rollback tests, installer profile tests,
  and a disposable startup acceptance runner.
- Keep manual, batch, and EXE downloads separate, with hashes and provenance.

## Verification and limits

Native gameplay acceptance passed for the executable hash recorded in the
canonical profile. This includes parent and real-parent setters, distinct
roles after text and compressed-binary save/load, main-menu reload and process
restart, history, character creation, close-family positives and negatives,
seven accelerated pregnancy/birth cases, four make_pregnant_no_checks birth
cases, and the tested parent/real-parent and close-family interaction actions.
User-operated interaction results agree with the archived acceptance flags.
See `release/validation.json` for scenario status and evidence paths.

Compatibility follows exact executable and original compiler hashes. The
profile's GOG label records installation provenance; identical Steam/GOG game
files use the same profile. Different hashes require separate verification.

Normal-mode exit autosave and debug-mode main-menu save/load passed. The tested
debug-mode exit-to-desktop path failed to write an autosave both with AGP enabled
and with the original compiler restored. Its cause remains unresolved; the
administrator compatibility setting was not established as a fix. Birth tests
used acceleration and do not establish a full nine-month gestation run.

Dynastic Priority is excluded from all three native ZIPs and this release does
not update the published add-on. Its complete rule matrix remains unverified.
Support is limited to the exact recorded game-file hashes.

Canonical release artifacts are built by GitHub Actions. Local packages carry
local build provenance and are not automatically published by this work.
