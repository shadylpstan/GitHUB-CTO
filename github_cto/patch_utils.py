from __future__ import annotations

import re


class PatchApplyError(RuntimeError):
    pass


HUNK_RE = re.compile(r"@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


def apply_unified_diff(original: str, diff_text: str) -> str:
    original_lines = original.splitlines()
    diff_lines = diff_text.splitlines()
    output: list[str] = []
    original_index = 0
    cursor = 0

    while cursor < len(diff_lines):
        line = diff_lines[cursor]
        if not line.startswith("@@"):
            cursor += 1
            continue

        match = HUNK_RE.match(line)
        if not match:
            raise PatchApplyError(f"Invalid unified diff hunk header: {line}")

        old_start = int(match.group("old_start"))
        target_index = max(old_start - 1, 0)
        if target_index < original_index:
            raise PatchApplyError("Overlapping or out-of-order diff hunks.")

        output.extend(original_lines[original_index:target_index])
        original_index = target_index
        cursor += 1

        while cursor < len(diff_lines) and not diff_lines[cursor].startswith("@@"):
            hunk_line = diff_lines[cursor]
            if hunk_line.startswith("--- ") or hunk_line.startswith("+++ "):
                cursor += 1
                continue
            if hunk_line.startswith(" "):
                expected = hunk_line[1:]
                if original_index >= len(original_lines) or original_lines[original_index] != expected:
                    raise PatchApplyError("Diff context did not match the original file.")
                output.append(original_lines[original_index])
                original_index += 1
            elif hunk_line.startswith("-"):
                expected = hunk_line[1:]
                if original_index >= len(original_lines) or original_lines[original_index] != expected:
                    raise PatchApplyError("Diff removal did not match the original file.")
                original_index += 1
            elif hunk_line.startswith("+"):
                output.append(hunk_line[1:])
            elif hunk_line == r"\ No newline at end of file":
                pass
            else:
                raise PatchApplyError(f"Unsupported diff line: {hunk_line}")
            cursor += 1

    output.extend(original_lines[original_index:])
    result = "\n".join(output)
    if original.endswith("\n") or diff_text.endswith("\n"):
        result += "\n"
    return result
