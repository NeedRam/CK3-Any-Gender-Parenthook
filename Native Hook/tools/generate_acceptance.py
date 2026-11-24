"""Generate a disposable startup runner from the canonical scripted tests.

This avoids invoking the console test runner inside a GUI lifecycle callback.
The generated files belong only in the isolated acceptance user directory.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re


def blocks(text: str):
    """Yield top-level key/block pairs, respecting strings and comments."""
    token = re.compile(r'#[^\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s={}]+|=')
    tokens = list(token.finditer(text))
    depth = 0
    start = None
    key = ""
    for i, match in enumerate(tokens):
        value = match.group()
        if value.startswith('#'):
            continue
        if value == '{':
            if depth == 0:
                key = tokens[i - 2].group()
                start = match.end()
            depth += 1
        elif value == '}':
            depth -= 1
            if depth == 0:
                yield key, text[start:match.start()]
            if depth < 0:
                raise ValueError('unbalanced script')
    if depth:
        raise ValueError('unbalanced script')


def generate(source: Path, output: Path, mode: str) -> None:
    prefix = {'setup':'agp_native_121', 'reload':'agp_reload_121',
              'birth_setup':'agp_birth_setup_121', 'birth_check':'agp_birth_check_121',
              'no_checks_setup':'agp_no_checks_setup_121', 'no_checks_check':'agp_no_checks_check_121'}[mode]
    effects = ['character:122 = { save_scope_as = agp_test_ruler']
    for name, body in blocks(source.read_text(encoding='utf-8-sig')):
        if not name.startswith(prefix):
            continue
        effects.append(f'debug_log = "AGP_ACCEPTANCE_BEGIN {name}"')
        effects.append('set_variable = { name = agp_acceptance_ok value = 1 }')
        for kind, content in blocks(body):
            content = re.sub(r'\broot\b', 'scope:agp_test_ruler', content)
            if kind == 'assert':
                effects.append(f'if = {{ limit = {{ NOT = {{ {content} }} }} set_variable = {{ name = agp_acceptance_ok value = 0 }} debug_log = "AGP_ACCEPTANCE_FAIL {name}" }}')
            elif kind == 'effect' and 'AGP_ACCEPTANCE_PASS' not in content:
                effects.append(f'if = {{ limit = {{ var:agp_acceptance_ok = 1 }} {content} }}')
        effects.append(f'if = {{ limit = {{ var:agp_acceptance_ok = 1 }} debug_log = "AGP_ACCEPTANCE_PASS {name}" }}')
        effects.append('remove_variable = agp_acceptance_ok')
    effects.append('}')
    body = '\n'.join(effects)
    destination = output / 'common/on_action/agp_acceptance.txt'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text('on_game_start_after_lobby = { on_actions = { agp_acceptance_startup } }\n'
                           'agp_acceptance_startup = { effect = {\n' + body + '\n} }\n', encoding='utf-8-sig')
    event = output / 'events/agp_acceptance.txt'
    event.parent.mkdir(parents=True, exist_ok=True)
    event.write_text('namespace = agp_acceptance_run\n'
                     'agp_acceptance_run.1 = { type = character_event hidden = yes orphan = yes immediate = {\n'
                     + body + '\n} }\n', encoding='utf-8-sig')
    gui = source.parents[1] / 'gui/agp_acceptance.gui'
    panel = gui.read_text(encoding='utf-8-sig')
    panel = panel.replace('scripted_tests agp_native_121', 'event agp_acceptance_run.1')
    panel = panel.replace('scripted_tests agp_reload_121', 'event agp_acceptance_run.1')
    (output / 'gui/agp_acceptance.gui').write_text(panel, encoding='utf-8-sig')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--mode', choices=('setup', 'reload', 'birth_setup', 'birth_check', 'no_checks_setup', 'no_checks_check'), default='setup')
    args = parser.parse_args()
    generate(args.source, args.output, args.mode)
