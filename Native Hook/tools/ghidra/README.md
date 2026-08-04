# AGP Ghidra helpers

These scripts support reverse-engineering the CK3 executable. They are read-only: they do not modify `ck3.exe`, the Ghidra database, or the DLL.

## Configuration

The runners use these defaults:

- `AGP_GHIDRA_HOME`: `%LOCALAPPDATA%\Temp\ghidra_12.1.2_PUBLIC\ghidra_12.1.2_PUBLIC`
- `AGP_CK3_EXE`: `C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\binaries\ck3.exe`

Set either environment variable before running a command if the installation differs.

## Helpers

- `FindParentValidation.java` locates CK3's parent-sex validation error string and reports its cross-references.
- `FindGenderChecks.java` reports `CMP` instructions that reference the character gender field offset. It defaults to `0x199`; pass a different offset when analyzing another executable.
- `InspectFunction.java` prints a bounded disassembly for a candidate function address.
- `ConfigureAnalysis.java` disables expensive Ghidra analyses that are not needed for these reports.

## Runners

```text
run_parent_validation_analysis.cmd
run_find_gender_checks_analysis.cmd
run_inspect_function_analysis.cmd 0x140123456 200
```

The generic `run_ghidra_analysis.cmd` runner accepts a post-script name followed by that script's arguments. It imports the executable, runs the focused analysis, and removes the temporary project afterward.

These reports identify candidates. They do not prove that a function is safe to patch; confirm the surrounding assembly, call targets, uniqueness, and behavior before updating a DLL signature.
