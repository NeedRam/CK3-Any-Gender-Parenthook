# AGP Native Parent Test

This is a disposable CK3 test mod for validating the AGP Native Hook. It is not the future AGP script mod and should not be treated as release gameplay content.

The test mod is intentionally divided into two namespaces and two interaction files:

- `agp_native_father_test` - female-father tests
- `agp_native_mother_test` - male-mother and male-carrier tests

The two suites use separate events, flags, scopes, interaction IDs, and localization files. No male-mother fixture belongs to the female-father event suite.

## Prerequisites

1. Build and install the matching AGP Native Hook DLL and DXCompiler loader.
2. Enable this test mod in the CK3 launcher.
3. Start a fresh game in debug mode.

The Native Hook DLLs belong beside `ck3.exe` in the game `binaries` directory. The test mod belongs in the normal CK3 mod location and is loaded separately.

For local development, use `AGP Native Parent Test.mod` or `descriptor.mod` as appropriate for your launcher setup. The external `.mod` descriptor contains a maintainer-specific development path and must be adjusted when the test mod is installed somewhere else.

## Female-father suite

Namespace: `agp_native_father_test`

All family members created by these fixtures are female. The suite tests female characters occupying native father or real-father roles while keeping the ordinary mother role available for comparison.

Run these events while playing a normal landed ruler:

```text
event agp_native_father_test.0001  # set_father with a female character
event agp_native_father_test.0002  # set_real_father with a female character
event agp_native_father_test.0003  # create_character with two female parents
event agp_native_father_test.0004  # make_pregnant with a female father
event agp_native_father_test.0005  # father and real_father scope resolution
event agp_native_father_test.0006  # two parents plus four female grandparents
event agp_native_father_test.0007  # father-first dynasty inheritance
event agp_native_father_test.0008  # distinct female mother/father/real-father scopes
```

The female-father interaction file is:

```text
common/character_interactions/agp_native_father_test_interactions.txt
```

It contains the two female-father pregnancy interactions and the mother, father, and real-father scope checks for fixture `.0008`.

## Male-mother suite

Namespace: `agp_native_mother_test`

All family members created by these fixtures are male. The suite tests male characters occupying native mother or real-mother roles, including reconstruction through save/load.

Run these events while playing a normal landed ruler:

```text
event agp_native_mother_test.0001  # set_mother with a male character
event agp_native_mother_test.0002  # set_real_mother with a male character
event agp_native_mother_test.0003  # create_character with a male mother
event agp_native_mother_test.0004  # four-grandparent traversal and persistence
event agp_native_mother_test.0005  # create the mother-scope interaction fixture
event agp_native_mother_test.0006  # report mother-scope interaction results
event agp_native_mother_test.0007  # set_father and set_mother with two male parents
event agp_native_mother_test.0008  # create_character with male parents and set_real_mother
```

The male-mother interaction file is:

```text
common/character_interactions/agp_native_mother_test_interactions.txt
```

It contains the male mother and male real-mother scope checks, plus the male-carrier pregnancy interactions. The male-carrier tests belong to this suite because the carrier occupies CK3's native pregnancy/mother path; the biological father in those interactions remains male.

## Pregnancy interactions

The female-father suite adds:

- **Make Pregnant (Native Female Father Test):** the recipient carries; the actor is recorded as the female father.
- **Become Pregnant (Native Female Father Test):** the actor carries; the recipient is recorded as the female father.

The male-mother suite adds:

- **Make Pregnant (Native Male Carrier Test):** the male recipient carries; the male actor is the biological father.
- **Become Pregnant (Native Male Carrier Test):** the male actor carries; the male recipient is the biological father.

These interactions call native `make_pregnant` directly.

## What to inspect

For every fixture that creates a child:

1. Inspect the child's character window after the event.
2. Verify the expected native parent and real-parent scopes.
3. Check the parent and Grandparents tabs where applicable.
4. Save, exit to the main menu, reload, and repeat the relevant checks.

For fixture `.0008` in the female-father suite, play as the child and verify that the Mother Scope Test, Father Scope Test, and Real Father Scope Test appear only on their matching targets.

For fixtures `.0005` and `.0006` in the male-mother suite, play as the child, use both dedicated mother-scope interactions on their matching parents, and then run `.0006` to report the results.

## History smoke tests

The history fixtures are rebuilt from the installed CK3 base-game files. They do not use AWOW history overrides or AWOW scripted effects. Only the character genders and the same-sex spouse entries needed to keep those fixtures valid are changed.

### Female-father history smoke test

`history/characters/irish.txt` changes `83355`, `902`, `900`, `83357`, `6207`, and `83356` to female.

`900` is `902`'s father, and `902` is `83355`'s father. `83357` is `83355`'s child, while `6207` and `83356` are `83355`'s siblings.

The file also preserves `900`'s historical spouses as same-sex spouse entries after changing `900` to female. Start a fresh 1066 game and inspect the family tree for the living descendants. Verify that the native father and grandparent links load even though the father-side characters are female.

### Male-mother history smoke test

The male-facing fixture spans these base-game files:

- `history/characters/czech.txt`: `517`, `212881`, `8502`, and `522`'s spouse links
- `history/characters/hungarian.txt`: `477`
- `history/characters/franconian.txt`: `1437` and `7666`
- `history/characters/polish.txt`: `765`

These changes use `522` as the family anchor and make his parent-side characters, spouses `477` and `765`, and daughters `212881` and `8502` male. The historical spouse entries are converted to same-sex spouse entries where required.

Start a fresh 1066 game and inspect `522` and the surviving descendants. Verify that the native mother, real-mother, and grandparent links load correctly after history initialization.

### Shared history validation

Start a fresh game with only this test mod and the Native Hook enabled. After reaching the main menu or starting the game, inspect:

- CK3 `error.log`
- CK3 `database_conflicts.log`
- `agp_dxcompiler_loader.log`
- `agp_parenthook.log`

For both smoke tests, save, exit to the main menu, reload, and repeat the family-window checks. A successful game start alone does not prove that the native parent roles persisted correctly.

## Failure handling

A successful event panel is not sufficient proof of native persistence. Treat the following as failures requiring investigation:

- A parent appears in the wrong native slot.
- A scope works before saving but not after reload.
- A parent or grandparent disappears from the UI.
- The loader or payload log reports a signature mismatch or write failure.
- CK3 logs report a wrong-gender or parent-assignment error.

Record the CK3 executable version, exact event ID, save/reload result, relevant UI result, and log output before changing the DLL or test fixture.
