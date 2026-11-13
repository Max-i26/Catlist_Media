"""MeetingOS command-line interface."""
from __future__ import annotations

import sys
from pathlib import Path
import click

from meetingos.config import (
    CHUNK_STRIDE,
    DB_PATH,
    DEFAULT_CHUNK_WINDOW,
    FAISS_DIR,
    OUTPUTS_DIR,
    TRANSCRIPTS_DIR,
)
from meetingos.ingestion.manifest import IngestionManifest
from meetingos.ingestion.pipeline import run_ingestion_pipeline
from meetingos.ingestion.validator import Gate1Validator
from meetingos.memory.schema import get_connection
from meetingos.memory.source import SourceMemory


@click.group()
def main() -> None:
    """MeetingOS — Evidence-Grounded Agentic Meeting Intelligence."""
    pass


@main.command("ingest")
@click.option(
    "--transcripts-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=TRANSCRIPTS_DIR,
    help="Path to transcripts directory.",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=DB_PATH,
    help="Target SQLite database path.",
)
@click.option(
    "--manifest-path",
    type=click.Path(path_type=Path),
    default=OUTPUTS_DIR / "ingestion_manifest.json",
    help="Target manifest JSON path.",
)
def ingest_cmd(
    transcripts_dir: Path,
    db_path: Path,
    manifest_path: Path,
) -> None:
    """Run deterministic ingestion (Gate 1)."""
    click.echo(f"Starting Gate 1 ingestion from: {transcripts_dir}")
    try:
        _, manifest, report = run_ingestion_pipeline(
            transcripts_dir=transcripts_dir,
            db_path=db_path,
            manifest_path=manifest_path,
            raise_on_failure=False,
        )
        click.echo(report.summary())
        if not report.passed:
            click.echo("Gate 1: FAILED", err=True)
            sys.exit(1)
        click.echo("Gate 1: PASSED")
    except Exception as exc:
        click.echo(f"Ingestion failed with exception: {exc}", err=True)
        sys.exit(1)


@main.command("validate-gate1")
@click.option(
    "--db-path",
    type=click.Path(exists=True, path_type=Path),
    default=DB_PATH,
    help="Path to SQLite database.",
)
@click.option(
    "--manifest-path",
    type=click.Path(exists=True, path_type=Path),
    default=OUTPUTS_DIR / "ingestion_manifest.json",
    help="Path to manifest JSON.",
)
def validate_gate1_cmd(db_path: Path, manifest_path: Path) -> None:
    """Validate existing SQLite DB and manifest against Gate 1 criteria."""
    click.echo(f"Validating Gate 1 on: {db_path} and {manifest_path}")
    conn = get_connection(db_path, readonly=True)
    memory = SourceMemory(conn)
    manifest = IngestionManifest.from_json_file(manifest_path)

    validator = Gate1Validator(memory, manifest)
    report = validator.validate()
    click.echo(report.summary())
    if not report.passed:
        click.echo("Gate 1: FAILED", err=True)
        sys.exit(1)
    click.echo("Gate 1: PASSED")


@main.command("process")
@click.option(
    "--db-path",
    type=click.Path(exists=True, path_type=Path),
    default=DB_PATH,
    help="Target SQLite database path.",
)
@click.option(
    "--faiss-dir",
    type=click.Path(path_type=Path),
    default=FAISS_DIR,
    help="Target FAISS directory.",
)
@click.option(
    "--window-size",
    type=int,
    default=DEFAULT_CHUNK_WINDOW,
    help="Turns per sliding window.",
)
@click.option(
    "--stride",
    type=int,
    default=CHUNK_STRIDE,
    help="Turn advance stride.",
)
@click.option(
    "--use-mock",
    is_flag=True,
    default=False,
    help="Use fast mock embedder for testing.",
)
def process_cmd(
    db_path: Path,
    faiss_dir: Path,
    window_size: int,
    stride: int,
    use_mock: bool,
) -> None:
    """Run conversation chunking and indexing (Milestone 2 / Gate 2)."""
    from meetingos.processing.pipeline import run_processing_pipeline
    click.echo(f"Processing conversation chunks (window={window_size}, stride={stride})...")
    try:
        chunks_count, vectors_count, report = run_processing_pipeline(
            db_path=db_path,
            faiss_dir=faiss_dir,
            window_size=window_size,
            stride=stride,
            use_mock_embedder=use_mock,
            raise_on_failure=False,
        )
        click.echo(f"Chunks generated: {chunks_count}")
        click.echo(f"Vectors indexed:  {vectors_count}")
        click.echo(report.summary())
        if not report.passed:
            click.echo("Gate 2: FAILED", err=True)
            sys.exit(1)
        click.echo("Gate 2: PASSED")
    except Exception as exc:
        click.echo(f"Processing failed with exception: {exc}", err=True)
        sys.exit(1)


@main.command("validate-gate2")
@click.option(
    "--db-path",
    type=click.Path(exists=True, path_type=Path),
    default=DB_PATH,
    help="Path to SQLite database.",
)
@click.option(
    "--faiss-dir",
    type=click.Path(exists=True, path_type=Path),
    default=FAISS_DIR,
    help="Path to FAISS directory.",
)
def validate_gate2_cmd(db_path: Path, faiss_dir: Path) -> None:
    """Validate Gate 2 conversation processing and indexing."""
    from meetingos.processing.validator import Gate2Validator
    conn = get_connection(db_path, readonly=False)
    validator = Gate2Validator(conn, faiss_dir=faiss_dir)
    report = validator.validate()
    conn.close()
    click.echo(report.summary())
    if not report.passed:
        click.echo("Gate 2: FAILED", err=True)
        sys.exit(1)
    click.echo("Gate 2: PASSED")


@main.command("validate-gate3")
@click.option(
    "--db-path",
    type=click.Path(exists=True, path_type=Path),
    default=DB_PATH,
    help="Path to SQLite database.",
)
def validate_gate3_cmd(db_path: Path) -> None:
    """Validate Gate 3 persistent memory and derived states."""
    from meetingos.processing.validator import Gate3Validator
    conn = get_connection(db_path, readonly=True)
    validator = Gate3Validator(conn)
    report = validator.validate()
    conn.close()
    click.echo(report.summary())
    if not report.passed:
        click.echo("Gate 3: FAILED", err=True)
        sys.exit(1)
    click.echo("Gate 3: PASSED")


@main.command("info")
@click.option(
    "--db-path",
    type=click.Path(exists=True, path_type=Path),
    default=DB_PATH,
    help="Path to SQLite database.",
)
def info_cmd(db_path: Path) -> None:
    """Display statistics about stored meeting memory."""
    conn = get_connection(db_path, readonly=True)
    memory = SourceMemory(conn)
    click.echo(f"Database: {db_path}")
    click.echo(f"Total Turns:    {memory.count_turns()}")
    click.echo(f"Total Meetings: {memory.count_meetings()}")
    click.echo(f"Total Teams:    {memory.count_teams()}")

    coverage = memory.list_all_coverage()
    complete = sum(1 for c in coverage.values() if c.is_complete)
    partial = sum(1 for c in coverage.values() if not c.is_complete)
    click.echo(f"Coverage:       {complete} complete teams, {partial} partial teams")
    for team_id, c in coverage.items():
        if not c.is_complete:
            click.echo(f"  * {team_id}: available={c.available_sequences}, missing={c.missing_sequences}")


@main.command("generate-answers")
@click.option(
    "--questions-file",
    type=click.Path(exists=True, path_type=Path),
    default=OUTPUTS_DIR.parent.parent / "Catalist_AI_Intern_Build_Test_Data" / "questions.json",
    help="Path to questions.json file.",
)
@click.option(
    "--output-path",
    type=click.Path(path_type=Path),
    default=OUTPUTS_DIR / "answers.json",
    help="Path to output answers.json.",
)
@click.option(
    "--use-mock",
    is_flag=True,
    default=False,
    help="Use mock embedder for rapid testing.",
)
def generate_answers_cmd(questions_file: Path, output_path: Path, use_mock: bool) -> None:
    """Run agent orchestrator to solve 25 questions and generate brief."""
    from meetingos.runner import generate_answers_and_brief
    click.echo(f"Solving questions from: {questions_file}")
    click.echo(f"Writing answers to:     {output_path}")
    try:
        answers_file = generate_answers_and_brief(
            questions_file=questions_file,
            output_path=output_path,
            use_mock_embedder=use_mock,
        )
        click.echo(f"Generated answers for {len(answers_file.answers)} questions.")
        click.echo("Pre-meeting brief generated successfully.")
        click.echo(f"Output saved to: {output_path}")
    except Exception as exc:
        click.echo(f"Generation failed: {exc}", err=True)
        sys.exit(1)


@main.command("evaluate")
@click.option(
    "--output-path",
    type=click.Path(path_type=Path),
    default=OUTPUTS_DIR / "evaluation_report.md",
    help="Path to output evaluation_report.md.",
)
@click.option(
    "--use-mock",
    is_flag=True,
    default=False,
    help="Use mock embedder for rapid testing.",
)
def evaluate_cmd(output_path: Path, use_mock: bool) -> None:
    """Run independent benchmark evaluation, scaling model, and generate report."""
    from meetingos.evaluation.evaluator import run_benchmark_and_generate_report
    click.echo("Running independent benchmark evaluation...")
    try:
        report = run_benchmark_and_generate_report(
            output_path=output_path,
            use_mock_embedder=use_mock,
        )
        click.echo("Benchmark evaluation completed.")
        click.echo(f"Report saved to: {output_path}")
    except Exception as exc:
        click.echo(f"Evaluation failed: {exc}", err=True)
        sys.exit(1)


@main.command("extract")
@click.option(
    "--db-path",
    type=click.Path(exists=True, path_type=Path),
    default=DB_PATH,
    help="Target SQLite database path.",
)
def extract_cmd(db_path: Path) -> None:
    """Run Stage 1 meeting extraction and Stage 2 temporal reconciliation."""
    from meetingos.extraction.pipeline import run_corpus_extraction
    click.echo(f"Running two-stage event extraction on {db_path}...")
    try:
        summary = run_corpus_extraction(db_path=db_path)
        click.echo(f"Teams Processed:  {summary['teams_processed']}")
        click.echo(f"Decisions Saved:  {summary['total_decisions']}")
        click.echo(f"Actions Saved:    {summary['total_actions']}")
        click.echo(f"Numerics Saved:   {summary['total_numerics']}")
        click.echo("Extraction and temporal reconciliation complete.")
    except Exception as exc:
        click.echo(f"Extraction failed: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
