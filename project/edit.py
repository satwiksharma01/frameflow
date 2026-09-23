#!/usr/bin/env python3
"""Change a project the creator already has.

Phase 7a: the loop the first cut could not close. Record, first cut, the
creator edits in Shotcut, asks for a change - and the change lands with their
edits intact.

    python -m project.edit <project.mlt> --prepare "<instruction>"    # agent mode
    (the agent follows change_request.md and writes operations.json)
    python -m project.edit <project.mlt> --apply [--open]

    python -m project.edit <project.mlt> "<instruction>"              # API mode

Every run reads the project from disk again, because the creator may have
saved in Shotcut between --prepare and --apply. Before anything is written:

  1. anything recompiling would lose - filters, titles, crossfades, muted
     tracks - stops the edit by name, unless --discard-unsupported;
  2. the creator's changes since Frameflow last wrote are reconciled, and an
     operation that would undo one is rejected unless it says why;
  3. the project and its sidecar are copied into history/, so every version
     the creator had can be recovered - including what --discard-unsupported
     discarded.
"""
import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from project.change_agent import build_agent_request, build_context, propose_operations
from project.compile_mlt import compile_file
from project.engine_check import EngineCheckError, check_with_melt
from project.first_cut import TIMING_FILE, _open_in_shotcut, _step, _write_json
from project.operations import apply, check, main_index, resolve
from project.parse_mlt import ParseError, parse_mlt, unsupported_content
from project.providers import ProviderError, get_provider
from project.reconcile import HumanChanges, reconcile, source_key
from project.sidecar import read_sidecar, sidecar_path
from project.transcribe import TranscriptionError, build_timing_map
from project.validate import ValidationError
from project.verify_cuts import VerificationError, verify_joins

REQUEST_FILE = "change_request.md"
OPERATIONS_FILE = "operations.json"
HISTORY_DIR = "history"
IR_FILE = "project.ir.json"


class EditError(Exception):
    pass


@dataclass
class Project:
    mlt: Path
    ir: dict
    changes: HumanChanges
    timing: dict
    discarded: list[str]

    @property
    def folder(self) -> Path:
        return self.mlt.parent

    def placement(self) -> tuple[dict, dict]:
        """Pauses and duration for the transcribed recording, keyed as operations expect."""
        key = source_key(self.timing["source"])
        return {key: self.timing["pauses"]}, {key: self.timing["duration_seconds"]}


def _timing(folder: Path, ir: dict, language: str) -> dict:
    """The word timing map for the main track's recording, made now if there is none."""
    track = ir["tracks"][main_index(ir)]
    recordings = {source_key(c["source"]): c["source"] for c in track["clips"]}
    path = folder / TIMING_FILE
    if path.exists():
        timing = json.loads(path.read_text(encoding="utf-8"))
        if source_key(timing["source"]) in recordings:
            return timing
        print(f"    {path.name} is for {Path(timing['source']).name}, which is not on the main track")
    if len(recordings) != 1:
        raise EditError(f"the main track uses {len(recordings)} recordings and there is no word "
                        f"timing map for them in {folder}")
    source = Path(next(iter(recordings.values())))
    _step(f"Mapping word timings for {source.name}")
    try:
        timing = build_timing_map(source, language=language)
    except TranscriptionError as e:
        raise EditError(f"could not transcribe {source.name}: {e}") from e
    _write_json(path, timing)
    return timing


def load(mlt: Path, discard_unsupported: bool = False, language: str = "auto") -> Project:
    if not mlt.exists():
        raise EditError(f"no such project: {mlt}")
    lost = unsupported_content(mlt)
    if lost and not discard_unsupported:
        raise EditError(
            "This project has things an edit would lose, because Frameflow rewrites the "
            "timeline from its clips alone:\n" + "\n".join(f"  - {item}" for item in lost) +
            "\nRemove them in Shotcut and save, or rerun with --discard-unsupported - the "
            f"current version is kept in {HISTORY_DIR}/ either way."
        )
    try:
        ir = parse_mlt(mlt)
    except (ParseError, ValidationError) as e:
        raise EditError(f"could not read {mlt.name}: {e}") from e
    changes = reconcile(read_sidecar(mlt), ir)
    return Project(mlt, ir, changes, _timing(mlt.parent, ir, language), lost)


def backup(mlt: Path) -> Path:
    """Copy the project and its sidecar into history/ before they are replaced."""
    history = mlt.parent / HISTORY_DIR
    history.mkdir(exist_ok=True)
    kept = history / f"{mlt.stem}.{datetime.now():%Y%m%d-%H%M%S}.mlt"
    shutil.copy2(mlt, kept)
    if sidecar_path(mlt).exists():
        shutil.copy2(sidecar_path(mlt), sidecar_path(kept))
    return kept


def _joins(ir: dict) -> set[tuple]:
    """Every clip-to-clip join on the main track, identified in recording terms."""
    fps = ir["project"]["fps"]
    clips = sorted(ir["tracks"][main_index(ir)]["clips"], key=lambda c: c["timeline_start"])
    return {(source_key(a["source"]), round(a["source_out"] * fps),
             source_key(b["source"]), round(b["source_in"] * fps))
            for a, b in zip(clips, clips[1:])}


def apply_change(project: Project, doc: dict, verify: bool = True) -> Path | None:
    """Apply accepted operations and rewrite the project. None if nothing changed."""
    pauses, durations = project.placement()
    operations, problems = resolve(doc, project.ir, project.changes, pauses, durations)
    new_ir, apply_problems = apply(project.ir, operations) if not problems else (None, [])
    problems += apply_problems
    if problems:
        raise EditError("the operations need fixing:\n" + "\n".join(f"  {p}" for p in problems))

    print(f"    {doc['summary']}")
    if not operations:
        print("    No changes made; the project is untouched.")
        return None

    kept = backup(project.mlt)
    ir_path = project.folder / IR_FILE
    _write_json(ir_path, new_ir)
    compile_file(ir_path, project.mlt)

    _step("Checking the project in the MLT engine")
    try:
        print("    loaded cleanly" if check_with_melt(project.mlt) else "    melt not found; skipped")
    except EngineCheckError:
        # Put the creator's version back: a project the engine rejects is worse than none.
        shutil.copy2(kept, project.mlt)
        if sidecar_path(kept).exists():
            shutil.copy2(sidecar_path(kept), sidecar_path(project.mlt))
        else:
            sidecar_path(project.mlt).unlink(missing_ok=True)
        raise

    _step("Changes")
    for op in operations:
        print(f"    {op.describe()}")
        for note in op.notes:
            print(f"      ! {note}")
    if project.discarded:
        print(f"    discarded, as asked (the previous version still has them): "
              f"{'; '.join(project.discarded)}")
    main = main_index(new_ir)
    others = sum(len(t["clips"]) for i, t in enumerate(new_ir["tracks"]) if i != main)
    if others:
        print(f"    ! {others} clip(s) on other tracks kept their positions; check they still "
              f"line up with the main track")
    print(f"    previous version: {kept}")

    if verify:
        _step("Listening to the new cuts")
        before = _joins(project.ir)
        fps = new_ir["project"]["fps"]
        try:
            checks = verify_joins(new_ir, project.timing, project.mlt, include=lambda a, b: (
                source_key(a["source"]), round(a["source_out"] * fps),
                source_key(b["source"]), round(b["source_in"] * fps)) not in before)
        except VerificationError as e:
            print(f"    skipped: {e}")
        else:
            suspect = [c for c in checks if not c.ok]
            print(f"    {len(checks) - len(suspect)} of {len(checks)} new joins sound clean")
            for c in suspect:
                print(f"    ! {c.summary}")
    return project.mlt


def load_operations(path: Path) -> dict:
    if not path.exists():
        raise EditError(f"no operations at {path}; run with --prepare first and have your "
                        f"agent write them")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise EditError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(doc, dict):
        raise EditError(f"{path} must contain a JSON object")
    return doc


def main() -> None:
    parser = argparse.ArgumentParser(description="Change a project the creator already has.")
    parser.add_argument("project", help="the .mlt to change")
    parser.add_argument("instruction", nargs="?", help="the change, in plain words")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true",
                      help="agent mode: write change_request.md for a coding agent")
    mode.add_argument("--apply", action="store_true",
                      help="agent mode: check operations.json and apply it")
    parser.add_argument("--provider", help="API mode: anthropic (default) or openai; or FRAMEFLOW_PROVIDER")
    parser.add_argument("--model", help="API mode: model id; or FRAMEFLOW_MODEL")
    parser.add_argument("--base-url", help="API mode: OpenAI-compatible endpoint; or FRAMEFLOW_BASE_URL")
    parser.add_argument("--language", default="auto", help="spoken language, if a transcript must be made")
    parser.add_argument("--discard-unsupported", action="store_true",
                        help="edit even though filters, titles or other effects would be lost")
    parser.add_argument("--open", action="store_true", help="open the result in Shotcut")
    parser.add_argument("--no-verify", action="store_true", help="skip listening to the new cuts")
    args = parser.parse_args()

    mlt = Path(args.project).resolve()
    if not args.apply and not args.instruction:
        parser.error("say what to change, e.g. \"cut the part about pricing\"")

    try:
        _step(f"Reading {mlt.name}")
        project = load(mlt, args.discard_unsupported, args.language)
        for line in project.changes.lines():
            print(f"    {line}")
        operations_path = project.folder / OPERATIONS_FILE

        if args.prepare:
            request = project.folder / REQUEST_FILE
            request.write_text(build_agent_request(
                build_context(args.instruction, project.ir, project.changes, project.timing),
                operations_path, f'python -m project.edit "{mlt}" --apply'), encoding="utf-8")
            print(f"\nChange request: {request}")
            print(f"Next: have your agent follow it and write {operations_path}, then run --apply.")
            return

        if args.apply:
            doc = load_operations(operations_path)
        else:
            provider = get_provider(args.provider, args.model, args.base_url)
            _step(f"Proposing the change with {provider.name} / {provider.model}")
            pauses, durations = project.placement()
            doc = propose_operations(
                build_context(args.instruction, project.ir, project.changes, project.timing),
                provider, lambda d: check(d, project.ir, project.changes, pauses, durations))
            _write_json(operations_path, doc)

        _step("Applying")
        result = apply_change(project, doc, verify=not args.no_verify)
    except (EditError, ProviderError, EngineCheckError) as e:
        sys.exit(f"\n{e}")

    if result:
        print(f"\nChanged: {result}")
        if args.open:
            _open_in_shotcut(result)


if __name__ == "__main__":
    main()
