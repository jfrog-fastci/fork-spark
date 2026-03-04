#!/usr/bin/env python3
"""
Minimal, line-based inserter for FastCI that avoids YAML reformatting.

Behavior:
- Adds repo root fastci.config.json (if missing) should be created separately.
- For each file in .github/workflows/*.yml|*.yaml:
  - If there is no top-level 'permissions:' (a line starting at column 0), insert:
      permissions:
        issues: write
    after the initial comments and optional `name:` line (minimal insertion).
  - For every 'steps:' mapping, insert the FastCI step as the first list item
    by adding a line immediately after the 'steps:' line using the same indent:
      <steps_indent>  - uses: jfrog-fastci/fastci@v0
    but only if that repository action isn't already present in the next 30 lines.
  - For every 'container:' mapping (where container: is followed by an indented block),
    ensure there is a 'volumes:' key inside that block and add the mount:
      - /home/runner:/tmp/fastci/mounts/home/runner
    using consistent indentation. Does not attempt to convert scalar containers.

This is intentionally conservative and edits files with minimal line insertions.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FASTCI_STEP = "uses: jfrog-fastci/fastci@v0"
FASTCI_MOUNT = "/home/runner:/tmp/fastci/mounts/home/runner"

def find_insert_pos_for_permissions(lines):
    # Skip initial comments and blank lines
    i = 0
    while i < len(lines) and (lines[i].strip() == "" or lines[i].lstrip().startswith("#")):
        i += 1
    # If next line is name: place after it, else place at i
    if i < len(lines) and re.match(r'^\s*name\s*:', lines[i]):
        return i + 1
    return i

def has_top_level_permissions(lines):
    for ln in lines:
        if re.match(r'^permissions\s*:', ln):
            return True
    return False

def add_permissions_block(lines):
    if has_top_level_permissions(lines):
        return False
    pos = find_insert_pos_for_permissions(lines)
    block = ["permissions:\n", "  issues: write\n"]
    lines[pos:pos] = block
    return True

def add_fastci_step_after_steps(lines):
    changed = False
    i = 0
    while i < len(lines):
        m = re.match(r'^(\s*)steps\s*:\s*$', lines[i])
        if m:
            indent = m.group(1)
            # check next ~30 lines for existing fastci usage within this steps block
            block_end = min(len(lines), i + 200)  # generous scan
            found = False
            for j in range(i+1, block_end):
                if FASTCI_STEP in lines[j]:
                    found = True
                    break
                # break if another top-level mapping starts (simple heuristic)
                if re.match(r'^\S', lines[j]) and not lines[j].lstrip().startswith("-"):
                    break
            if not found:
                insert_line = indent + "  - " + FASTCI_STEP + "\n"
                lines.insert(i+1, insert_line)
                changed = True
                i += 1  # skip inserted line
        i += 1
    return changed

def ensure_container_volumes(lines):
    changed = False
    i = 0
    while i < len(lines):
        m = re.match(r'^(\s*)container\s*:\s*$', lines[i])
        if m:
            indent = m.group(1)
            # scan the mapping block under container
            j = i + 1
            container_block_lines = []
            while j < len(lines):
                if lines[j].strip() == "":
                    j += 1
                    continue
                # stop when we reach a line with indent less or equal to container indent
                if not lines[j].startswith(indent + "  ") and re.match(r'^\S', lines[j]):
                    break
                if not lines[j].startswith(indent + "  "):
                    break
                container_block_lines.append((j, lines[j]))
                j += 1
            # search for 'volumes:' inside container block
            vols_idx = None
            for idx, ln in container_block_lines:
                if re.match(r'^\s*volumes\s*:', ln):
                    vols_idx = idx
                    break
            if vols_idx is not None:
                # find where the list items end; insert mount if missing
                k = vols_idx + 1
                mount_present = False
                while k < j and (lines[k].startswith(re.match(r'^(\s*)', lines[vols_idx]).group(1) + "  ") or lines[k].strip() == ""):
                    if FASTCI_MOUNT in lines[k]:
                        mount_present = True
                        break
                    k += 1
                if not mount_present:
                    # insert as a list item under volumes
                    indent_vol = re.match(r'^(\s*)', lines[vols_idx]).group(1)
                    lines.insert(k, indent_vol + "  - " + FASTCI_MOUNT + "\n")
                    changed = True
            else:
                # add volumes: block after the last line of the container block header (i+1)
                insert_at = i + 1
                # Determine container indent for children
                child_indent = indent + "  "
                block = [child_indent + "volumes:\n", child_indent + "  - " + FASTCI_MOUNT + "\n"]
                lines[insert_at:insert_at] = block
                changed = True
                j += len(block)
            i = j
            continue
        i += 1
    return changed

def process_file(path: Path):
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    modified = False
    if add_permissions_block(lines):
        modified = True
    if add_fastci_step_after_steps(lines):
        modified = True
    if ensure_container_volumes(lines):
        modified = True
    if modified:
        path.write_text("".join(lines))
    return modified

def main():
    modified = []
    for p in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        try:
            if process_file(p):
                modified.append(p.name)
        except Exception as e:
            print(f"error processing {p.name}: {e}")
    if modified:
        print("Modified files:")
        for m in modified:
            print(" -", m)
    else:
        print("No changes made.")

if __name__ == "__main__":
    main()

