# AGP: Dynastic Priority

Optional flavour support for Any-Gender Parenthook.

## Existing house assignment

CK3's normal birth logic follows the pregnancy's mother/father roles rather
than the parents' actual genders:

- Same-sex female births go to the carrier, or birth mother's, house.
- Same-sex male births go to the non-carrier male parent's house.
- In a gender-swapped opposite-sex marriage with a male mother and female
  father, patrilinear births go to the female father's house and matrilinear
  births go to the male mother's house.
- Ordinary opposite-sex births are unaffected.

## What this addon does

This addon runs after the normal `on_birth_child` house assignment and lets
the player override those results for the supported AGP cases.

By default, same-sex children join the house of the parent with the higher
highest-held landed title tier. A ruler's house therefore takes precedence
over an unlanded parent's house, and a king's house takes precedence over a
count's house. Equal-rank parents retain the existing result.

Four game rules allow the player to choose between:

- The higher-ranking, carrier, or non-carrier parent's house for same-sex
  female births.
- The higher-ranking, carrier, or non-carrier parent's house for same-sex
  male births.
- The man's, woman's, or higher-ranking parent's house for gender-swapped
  opposite-sex patrilinear births.
- The man's, woman's, or higher-ranking parent's house for gender-swapped
  opposite-sex matrilinear births.

The addon does not create pregnancies or alter parent assignment. It only
applies the selected house-selection effect through `on_birth_child`.

## Installation

Copy this folder into the CK3 mod directory and enable **AGP: Dynastic
Priority** after Any-Gender Parenthook and the AGP script framework.
