"""
ini_utils.py - Custom INI parser for NFS mod config files

NFS mod INIs (ThirteenAG Widescreen Fix, Extra Options, XtendedInput,
XenonEffects) use a format that Python's configparser can't handle:

  - Comments use ; and // (not #)
  - Inline comments after values: "value  ; comment" or "value  // comment"
  - Values can be strings, ints, floats, or hex (0x10DE)
  - Formatting uses aligned comments that users may hand-edit later

This module provides read/write/patch operations that preserve all
comments, blank lines, and formatting. patch_ini() is the main interface
used by all mod installer modules and game_config.py.

Usage:
    from ini_utils import read_ini, patch_ini

    # Check what's currently set
    data = read_ini("/path/to/config.ini")
    print(data["MISC"]["SkipIntro"])  # "1"

    # Patch specific keys without touching anything else
    patch_ini("/path/to/config.ini", {
        "MISC": {"SkipIntro": "1", "ImproveGamepadSupport": "0"},
        "MAIN": {"AutoFitFE": "1"},
    })
"""

import os
import re

from log import get_logger

_log = get_logger(__name__)

# Matches a [SECTION] header, allowing optional whitespace
_SECTION_RE = re.compile(r'^\s*\[([^\]]+)\]\s*$')

# Matches key = value lines. Captures key and everything after the =.
# Allows optional whitespace around the =.
_KV_RE = re.compile(r'^(\s*)([A-Za-z_]\w*)\s*=\s*(.*)')


def _split_value_comment(raw_value):
    """
    Split a raw value string into (value, comment_with_separator).

    Handles both ; and // inline comments. The comment portion includes
    the leading whitespace and separator so it can be glued back on
    during write without losing alignment.

    Examples:
        "1                               ; Corrects HUD aspect ratio."
        -> ("1", "                               ; Corrects HUD aspect ratio.")

        "0.5                  // rain scale"
        -> ("0.5", "                  // rain scale")

        "Auto"
        -> ("Auto", "")
    """
    # Look for ; comment first - but not inside a value like "0x10DE"
    # The pattern: whitespace followed by ; or //
    # We search for the earliest comment marker that has at least one
    # space before it (to avoid matching hex values or URLs)
    best_pos = -1
    best_sep = ""

    # Check for ;  - must have whitespace before it
    idx = 0
    while idx < len(raw_value):
        pos = raw_value.find(';', idx)
        if pos == -1:
            break
        # Valid comment if at start or preceded by whitespace
        if pos == 0 or raw_value[pos - 1] in (' ', '\t'):
            if best_pos == -1 or pos < best_pos:
                best_pos = pos
                # Walk back to find where the whitespace before ; starts
                ws_start = pos
                while ws_start > 0 and raw_value[ws_start - 1] in (' ', '\t'):
                    ws_start -= 1
                best_pos = ws_start
                best_sep = ";"
            break
        idx = pos + 1

    # Check for // - must have whitespace before it
    idx = 0
    while idx < len(raw_value):
        pos = raw_value.find('//', idx)
        if pos == -1:
            break
        if pos == 0 or raw_value[pos - 1] in (' ', '\t'):
            # Only use this if it comes before the ; comment (or no ; found)
            ws_start = pos
            while ws_start > 0 and raw_value[ws_start - 1] in (' ', '\t'):
                ws_start -= 1
            if best_pos == -1 or ws_start < best_pos:
                best_pos = ws_start
                best_sep = "//"
            break
        idx = pos + 1

    if best_pos == -1:
        return raw_value.rstrip(), ""

    value = raw_value[:best_pos].rstrip()
    comment = raw_value[best_pos:]
    return value, comment


def read_ini(path):
    """
    Read an INI file and return a dict of {section: {key: value}}.

    Sections are stored with their original casing. Keys are stored
    with original casing. Values have inline comments stripped and
    whitespace trimmed.

    Keys that appear before any section header are stored under the
    empty string key "".

    Returns an empty dict if the file doesn't exist or can't be read.
    """
    if not os.path.exists(path):
        _log.debug("read_ini: file not found: %s", path)
        return {}

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError:
        _log.error("read_ini: failed to read %s", path, exc_info=True)
        return {}

    result = {}
    current_section = ""

    for line in lines:
        stripped = line.strip()

        # Skip blank lines and comment-only lines
        if not stripped or stripped.startswith(';') or stripped.startswith('//'):
            continue

        # Section header
        m = _SECTION_RE.match(stripped)
        if m:
            current_section = m.group(1)
            continue

        # Key = value
        m = _KV_RE.match(line)
        if m:
            key = m.group(2)
            raw_value = m.group(3)
            value, _ = _split_value_comment(raw_value)
            if current_section not in result:
                result[current_section] = {}
            result[current_section][key] = value
            continue

    _log.debug("read_ini: %s - %d sections", path, len(result))
    return result


def patch_ini(path, patches):
    """
    Apply key=value patches to an INI file, preserving all comments,
    blank lines, and formatting.

    patches is a dict of {section_name: {key: value}}. Only the
    specified keys are changed - everything else passes through
    untouched. If a key exists in the file, its value is replaced
    in-place (preserving inline comments and alignment). If a key
    doesn't exist in the section, it's appended at the end of that
    section. If a section doesn't exist, it's appended at the end
    of the file.

    Key matching is case-insensitive (INI convention), but the
    original key casing is preserved in the output.

    Returns True on success, False on error.
    """
    if not os.path.exists(path):
        _log.error("patch_ini: file not found: %s", path)
        return False

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError:
        _log.error("patch_ini: failed to read %s", path, exc_info=True)
        return False

    # Track which patches we've applied so we know what to append
    # Build a lowercase lookup: {section_lower: {key_lower: new_value}}
    pending = {}
    for section, keys in patches.items():
        sec_lower = section.lower()
        pending[sec_lower] = {}
        for key, value in keys.items():
            pending[sec_lower][key.lower()] = str(value)

    # Also keep original casing for appended keys
    original_case = {}
    for section, keys in patches.items():
        sec_lower = section.lower()
        original_case[sec_lower] = {"_section": section}
        for key, value in keys.items():
            original_case[sec_lower][key.lower()] = key

    current_section = ""
    current_section_lower = ""
    # Track the last line index that belongs to each section
    # (for appending new keys at the end of a section)
    section_last_line = {}
    output = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Section header
        m = _SECTION_RE.match(stripped)
        if m:
            current_section = m.group(1)
            current_section_lower = current_section.lower()
            output.append(line)
            section_last_line[current_section_lower] = len(output) - 1
            continue

        # Key = value - check if this key needs patching
        m = _KV_RE.match(line)
        if m:
            indent = m.group(1)
            key = m.group(2)
            raw_value = m.group(3)
            key_lower = key.lower()

            section_last_line[current_section_lower] = len(output)

            if (current_section_lower in pending and
                    key_lower in pending[current_section_lower]):
                # This key needs patching - replace value, keep comment
                new_value = pending[current_section_lower][key_lower]
                _, comment = _split_value_comment(raw_value)

                if comment:
                    # Rebuild with aligned comment
                    # Try to preserve the original column alignment
                    # Find where the comment started in the original line
                    old_value, _ = _split_value_comment(raw_value)
                    # The raw_value starts after "key = ", so we need
                    # to figure out the spacing. Just reconstruct with
                    # the same total width as the original raw_value
                    # before the comment.
                    value_field_len = len(raw_value) - len(comment)
                    # If new value is shorter or same, pad to same width
                    if len(new_value) < value_field_len:
                        padded = new_value + ' ' * (value_field_len - len(new_value))
                    else:
                        # New value is longer - just add two spaces before comment
                        padded = new_value + '  '
                    new_line = f"{indent}{key} = {padded}{comment}\n"
                else:
                    new_line = f"{indent}{key} = {new_value}\n"

                output.append(new_line)

                # Mark this key as done
                del pending[current_section_lower][key_lower]
                if not pending[current_section_lower]:
                    del pending[current_section_lower]
            else:
                # Not a patched key, pass through unchanged
                output.append(line)
            continue

        # Anything else (blank lines, comments, etc) - pass through
        output.append(line)
        # Don't update section_last_line for trailing blank lines/comments
        # after the last key - we want to insert before them. Actually,
        # we do want to track content lines so appended keys go after
        # existing keys but before the next section.
        if stripped and current_section_lower:
            section_last_line[current_section_lower] = len(output) - 1

    # Append any remaining keys to existing sections
    sections_to_append_to_file = []

    for sec_lower, keys in list(pending.items()):
        if sec_lower in section_last_line:
            # Section exists but these keys weren't found - insert after
            # the last content line of that section
            insert_at = section_last_line[sec_lower] + 1
            new_lines = []
            for key_lower, value in keys.items():
                key_name = original_case[sec_lower].get(key_lower, key_lower)
                new_lines.append(f"{key_name} = {value}\n")

            for j, nl in enumerate(new_lines):
                output.insert(insert_at + j, nl)

            # Adjust all later section_last_line indices
            for s in section_last_line:
                if section_last_line[s] >= insert_at:
                    section_last_line[s] += len(new_lines)

            _log.debug("patch_ini: appended %d key(s) to [%s]",
                       len(new_lines), original_case[sec_lower]["_section"])
        else:
            # Section doesn't exist at all - append to file
            sections_to_append_to_file.append(sec_lower)

    # Append entirely new sections at end of file
    for sec_lower in sections_to_append_to_file:
        keys = pending[sec_lower]
        sec_name = original_case[sec_lower]["_section"]

        # Ensure there's a blank line before new section
        if output and output[-1].strip():
            output.append("\n")
        output.append(f"[{sec_name}]\n")
        for key_lower, value in keys.items():
            key_name = original_case[sec_lower].get(key_lower, key_lower)
            output.append(f"{key_name} = {value}\n")

        _log.debug("patch_ini: created new section [%s] with %d key(s)",
                   sec_name, len(keys))

    # Write back
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(output)
    except OSError:
        _log.error("patch_ini: failed to write %s", path, exc_info=True)
        return False

    _log.info("patch_ini: patched %s", path)
    return True


def write_ini(path, lines):
    """
    Write a list of raw line strings to an INI file.

    This is a simple file I/O wrapper. Each entry in lines should
    be a complete line (including newline character). Used when a
    module needs to write a file from scratch rather than patching.

    Returns True on success, False on error.
    """
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
    except OSError:
        _log.error("write_ini: failed to write %s", path, exc_info=True)
        return False

    _log.info("write_ini: wrote %s", path)
    return True
