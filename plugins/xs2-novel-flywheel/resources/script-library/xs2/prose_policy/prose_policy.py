"""File-based capability and JSON CLI for a book's prose preferences."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

# Script libraries may be loaded by filesystem spec under arbitrary host names.
# A package spec permits relative imports without modifying host sys.path.
_directory = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    __name__ + "_implementation", _directory / "__init__.py",
    submodule_search_locations=[str(_directory)],
)
_implementation = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _implementation
_spec.loader.exec_module(_implementation)

read = _implementation.read
audit = _implementation.audit
preview_override = _implementation.preview_override
save = _implementation.save
effective_context = _implementation.effective_context
effective_text = _implementation.effective_text
prepare_runtime = _implementation.prepare_runtime
runtime_file = _implementation.runtime_file
runtime_alias = _implementation.runtime_alias
runtime_common = _implementation.runtime_common
voice_mirror = _implementation.voice_mirror


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("read", "audit", "preview-override", "save",
                                            "effective-context", "prepare-runtime"))
    parser.add_argument("--chapter", default="0001")
    parser.add_argument("--expected-revision")
    parser.add_argument("--task-id")
    args = parser.parse_args()
    root = Path.cwd()
    if args.command in {"preview-override", "save"}:
        if not args.expected_revision:
            parser.error("--expected-revision is required")
        action = preview_override if args.command == "preview-override" else save
        result = action(root, json.load(sys.stdin), args.expected_revision)
    elif args.command == "prepare-runtime":
        result = prepare_runtime(root, args.chapter, task_id=args.task_id)
    elif args.command == "read":
        result = read(root)
    else:
        result = (audit if args.command == "audit" else effective_context)(root, args.chapter)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
