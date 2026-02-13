"""CLI entry point for the Kmoe manga downloader (Typer + Rich)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Optional

if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.progress import TaskID

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from kmoe.auth import check_session, load_session, login
from kmoe.client import KmoeClient
from kmoe.comic import get_comic_detail
from kmoe.config import get_or_create_config, save_config
from kmoe.constants import DownloadFormat
from kmoe.download import DownloadResult, download_volume, resolve_format
from kmoe.exceptions import KmoeError, QuotaExhaustedError
from kmoe.library import (
    detect_title_from_directory,
    find_stale_volumes,
    import_directory,
    list_library,
    load_index,
    match_files_to_volumes,
    rebuild_index,
    refresh_entry_from_detail,
    save_entry,
    scan_book_files,
    update_root_index,
)
from kmoe.models import AppConfig, ComicDetail, LibraryEntry, UserStatus
from kmoe.search import search, sort_by_language_and_score
from kmoe.utils import format_size, get_data_dir, setup_logging

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        from kmoe import __version__

        console.print(f"kmoe {__version__}")
        raise typer.Exit


def _verbose_callback(
    _ctx: typer.Context,
    value: bool,
) -> None:
    if value:
        setup_logging(verbose=True)


app = typer.Typer(
    help="Kmoe manga downloader CLI.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro: object) -> object:
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)  # type: ignore[arg-type]


def _apply_session(client: KmoeClient) -> None:
    """Load saved session cookies and apply them to the client."""
    cookies = load_session()
    if cookies:
        for name, value in cookies.items():
            client._client.cookies.set(name, value)


def _add_user_rows(table: Table, user: UserStatus) -> None:
    """Add user status rows to a Rich table."""
    table.add_row("Username", user.username or user.uin)
    table.add_row("Level", str(user.level))
    table.add_row("VIP", "Yes" if user.is_vip else "No")
    if user.quota_free_month > 0:
        used = user.quota_remaining + user.quota_extra
        table.add_row(
            "Quota",
            f"{used:.1f} / {user.quota_free_month:.1f} MB "
            f"(remaining: {user.quota_remaining:.1f} + extra: {user.quota_extra:.1f} MB)",
        )
    else:
        table.add_row("Quota", f"{user.quota_now:.1f} GB")


# Reusable verbose option annotation (Typer requires it as a parameter,
# but the callback handles the actual work, so the value is unused in the body).
_VerboseAnnotation = Annotated[
    bool,
    typer.Option("--verbose", "-v", help="Enable debug logging.", callback=_verbose_callback),
]


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@app.command("login")
def login_cmd(
    username: Annotated[str, typer.Option("-u", "--username", help="Email address")],
    password: Annotated[
        str, typer.Option("-p", "--password", help="Password (prompted if omitted)")
    ] = "",
    *,
    verbose: _VerboseAnnotation = False,  # noqa: ARG001
) -> None:
    """Login to Kmoe."""
    _run(_login(username, password))


def _configure_interactively(config: AppConfig) -> None:
    """交互式配置核心参数."""
    console.print("\n[bold]Configuration[/bold]")

    # download_dir - 使用纯 ASCII 默认值避免 typer 中文字符问题
    download_dir_str = typer.prompt(
        "Download directory",
        default="~/kmoe-library",
        type=str,
    )
    config.download_dir = Path(download_dir_str).expanduser()

    # default_format
    default_format = typer.prompt(
        "Default format (epub/mobi)",
        default=config.default_format,
        type=str,
    )
    config.default_format = default_format.lower()

    # preferred_language
    preferred_language = typer.prompt(
        "Preferred language (all/ch/jp/en/oth)",
        default=config.preferred_language,
        type=str,
    )
    config.preferred_language = preferred_language.lower()

    # max_download_workers
    max_workers_str = typer.prompt(
        "Max download workers (1-10)",
        default=str(config.max_download_workers),
        type=str,
    )
    try:
        config.max_download_workers = max(1, min(10, int(max_workers_str)))
    except ValueError:
        config.max_download_workers = 2

    save_config(config)
    console.print("[green]Configuration saved.[/green]")


async def _login(username: str, password: str) -> None:
    if not password:
        password = typer.prompt("Password", hide_input=True)

    config = get_or_create_config()
    try:
        async with KmoeClient(config) as client:
            user_status = await login(client, username, password)
    except KmoeError as exc:
        console.print(Panel(f"[red]{exc.message}[/red]", title="Error"))
        raise typer.Exit(1) from None

    table = Table(title="Login Successful", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    _add_user_rows(table, user_status)
    console.print(table)

    console.print()
    _configure_interactively(config)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    *,
    verbose: _VerboseAnnotation = False,  # noqa: ARG001
) -> None:
    """Check current session status."""
    _run(_status())


async def _status() -> None:
    config = get_or_create_config()
    try:
        async with KmoeClient(config) as client:
            user = await check_session(client)
    except KmoeError as exc:
        console.print(Panel(f"[red]{exc.message}[/red]", title="Error"))
        raise typer.Exit(1) from None

    # Session status table
    if user is not None:
        table = Table(title="Session Status", show_header=False)
        table.add_column("Field", style="bold")
        table.add_column("Value")
        _add_user_rows(table, user)
        console.print(table)
    else:
        console.print("[yellow]Not logged in.[/yellow]")

    console.print()

    # Config info
    config_path = get_data_dir() / "config.toml"
    console.print(f"[bold]Config:[/bold] {config_path}")

    config_table = Table(title="Configuration", show_header=False)
    config_table.add_column("Field", style="bold")
    config_table.add_column("Value")

    # Option hints for fields with limited choices
    option_hints: dict[str, str] = {
        "default_format": "epub/mobi",
        "preferred_mirror": "kxx.moe/kzz.moe/koz.moe",
        "preferred_language": "all/ch/jp/en/oth",
        "max_download_workers": "1-10",
    }

    # Dynamically iterate over all config fields
    for field_name in config.__dataclass_fields__:
        if field_name.startswith("_"):
            continue
        value = getattr(config, field_name)

        # Format the field name for display
        display_name = field_name.replace("_", " ").title()

        # Format the value
        if isinstance(value, bool):
            formatted_value = "Yes" if value else "No"
        elif isinstance(value, float):
            formatted_value = f"{value}s" if field_name == "rate_limit_delay" else str(value)
        else:
            formatted_value = str(value)

        # Add option hint if exists (append to value with brackets)
        if field_name in option_hints:
            display_name = f"{display_name} ({option_hints[field_name]})"

        config_table.add_row(display_name, formatted_value)

    console.print(config_table)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@app.command("search")
def search_cmd(
    keyword: Annotated[str, typer.Argument(help="Search keyword")],
    page: Annotated[int, typer.Option("--page", help="Page number")] = 1,
    language: Annotated[
        Optional[str],  # noqa: UP045
        typer.Option("--lang", help="Language filter (all/ch/jp/en/oth)"),
    ] = None,
    *,
    verbose: _VerboseAnnotation = False,  # noqa: ARG001
) -> None:
    """Search for comics."""
    _run(_search(keyword, page, language))


async def _search(keyword: str, page: int, language: str | None) -> None:
    config = get_or_create_config()
    lang_filter = language or config.preferred_language
    try:
        async with KmoeClient(config) as client:
            _apply_session(client)
            response = await search(client, keyword, page=page, language=lang_filter)
    except KmoeError as exc:
        console.print(Panel(f"[red]{exc.message}[/red]", title="Error"))
        raise typer.Exit(1) from None

    if not response.results:
        console.print("[yellow]No results found.[/yellow]")
        return

    sorted_results = sort_by_language_and_score(response.results, lang_filter)

    table = Table(title=f"Search Results for '{keyword}'")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="bold")
    table.add_column("Authors")
    table.add_column("Update")
    table.add_column("Score")
    table.add_column("Status")
    table.add_column("Language")

    for r in sorted_results:
        score_str = f"{r.score:.1f}" if r.score else "N/A"
        table.add_row(
            r.comic_id,
            r.title,
            ", ".join(r.authors),
            r.last_update,
            score_str,
            r.status,
            r.language,
        )

    console.print(table)
    console.print(f"Page {response.current_page} of {response.total_pages}")


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


@app.command()
def info(
    comic_id: Annotated[str, typer.Argument(help="Comic ID")],
    *,
    verbose: _VerboseAnnotation = False,  # noqa: ARG001
) -> None:
    """Show comic details."""
    _run(_info(comic_id))


async def _info(comic_id: str) -> None:
    config = get_or_create_config()
    try:
        async with KmoeClient(config) as client:
            _apply_session(client)
            detail = await get_comic_detail(client, comic_id)
    except KmoeError as exc:
        console.print(Panel(f"[red]{exc.message}[/red]", title="Error"))
        raise typer.Exit(1) from None

    meta = detail.meta
    info_lines = [
        f"[bold]Title:[/bold] {meta.title}",
        f"[bold]Authors:[/bold] {', '.join(meta.authors) or 'N/A'}",
        f"[bold]Status:[/bold] {meta.status or 'N/A'}",
        f"[bold]Region:[/bold] {meta.region or 'N/A'}",
        f"[bold]Language:[/bold] {meta.language or 'N/A'}",
        f"[bold]Categories:[/bold] {', '.join(meta.categories) or 'N/A'}",
    ]
    if meta.score is not None:
        info_lines.append(f"[bold]Score:[/bold] {meta.score}")
    if meta.description:
        info_lines.append(f"\n{meta.description}")

    console.print(Panel("\n".join(info_lines), title=f"Comic {meta.comic_id or meta.book_id}"))

    if detail.volumes:
        vol_table = Table(title="Volumes")
        vol_table.add_column("#", style="dim")
        vol_table.add_column("Vol ID", style="cyan")
        vol_table.add_column("Title")
        vol_table.add_column("MOBI", justify="right")
        vol_table.add_column("EPUB", justify="right")

        total_mobi = 0.0
        total_epub = 0.0
        for idx, vol in enumerate(detail.volumes, 1):
            total_mobi += vol.size_mobi_mb
            total_epub += vol.size_epub_mb
            mobi_str = f"{vol.size_mobi_mb:.1f} MB" if vol.size_mobi_mb else "-"
            epub_str = f"{vol.size_epub_mb:.1f} MB" if vol.size_epub_mb else "-"
            vol_table.add_row(str(idx), vol.vol_id, vol.title, mobi_str, epub_str)

        console.print(vol_table)
        console.print(
            f"Total: {len(detail.volumes)} volumes, "
            f"MOBI {total_mobi:.1f} MB, EPUB {total_epub:.1f} MB"
        )
    else:
        console.print("[yellow]No volumes available.[/yellow]")


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


@app.command()
def download(
    comic_id: Annotated[str, typer.Argument(help="Comic ID")],
    volumes: Annotated[
        Optional[str],  # noqa: UP045
        typer.Option("-V", "--volumes", help="Comma-separated volume IDs (all if omitted)"),
    ] = None,
    fmt: Annotated[
        Optional[str],  # noqa: UP045
        typer.Option("-f", "--format", help="Download format (mobi/epub)"),
    ] = None,
    *,
    verbose: _VerboseAnnotation = False,  # noqa: ARG001
) -> None:
    """Download volumes of a comic."""
    _run(_download(comic_id, volumes, fmt))


async def _download_with_progress(
    client: KmoeClient,
    config: AppConfig,
    detail: ComicDetail,
    vol_ids: list[str],
    dl_format: DownloadFormat,
) -> tuple[list[DownloadResult], list[tuple[str, Exception]]]:
    """Download volumes with Rich progress bars.

    Returns (results, errors) lists.
    """
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )

    from kmoe.comic import find_volume

    results: list[DownloadResult] = []
    errors: list[tuple[str, Exception]] = []
    semaphore = asyncio.Semaphore(config.max_download_workers)
    cancel_event = asyncio.Event()

    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:

        def _make_callbacks(
            tid: TaskID,
        ) -> tuple[Callable[[int], None], Callable[[int], None]]:
            def on_total(total: int) -> None:
                progress.update(tid, total=total)

            def on_chunk(n: int) -> None:
                progress.advance(tid, n)

            return on_chunk, on_total

        async def _do_download(vid: str) -> DownloadResult | tuple[str, Exception]:
            vol = find_volume(detail, vid)
            task_id = progress.add_task(vol.title, total=None, start=False)

            async with semaphore:
                if cancel_event.is_set():
                    progress.update(
                        task_id,
                        description=f"[dim]{vol.title} (cancelled)[/dim]",
                    )
                    return (vid, QuotaExhaustedError("Cancelled: quota exhausted"))

                progress.start_task(task_id)
                chunk_cb, total_cb = _make_callbacks(task_id)
                try:
                    result = await download_volume(
                        client,
                        config,
                        detail,
                        vid,
                        dl_format,
                        update_index=False,
                        progress_callback=chunk_cb,
                        total_callback=total_cb,
                    )
                    if result.skipped:
                        progress.update(
                            task_id,
                            completed=result.size_bytes,
                            total=result.size_bytes,
                            description=f"[dim]{vol.title} (skipped)[/dim]",
                        )
                    else:
                        size = result.size_bytes
                        progress.update(task_id, completed=size, total=size)
                    return result
                except QuotaExhaustedError as exc:
                    cancel_event.set()
                    progress.update(
                        task_id,
                        description=f"[red]{vol.title} (quota exhausted)[/red]",
                    )
                    return (vid, exc)
                except Exception as exc:
                    progress.update(
                        task_id,
                        description=f"[red]{vol.title} (failed)[/red]",
                    )
                    return (vid, exc)

        outcomes = await asyncio.gather(*[_do_download(v) for v in vol_ids])

        for item in outcomes:
            if isinstance(item, tuple):
                errors.append(item)  # type: ignore[arg-type]
            else:
                results.append(item)

    return results, errors


def _print_download_summary(
    results: list[DownloadResult],
    errors: list[tuple[str, Exception]],
) -> None:
    """Print a download results summary table."""
    table = Table(title="Download Results")
    table.add_column("Volume", style="bold")
    table.add_column("Status")
    table.add_column("Size")

    for dr in results:
        status_str = "[dim]skipped[/dim]" if dr.skipped else "[green]downloaded[/green]"
        table.add_row(dr.volume.title, status_str, format_size(dr.size_bytes))

    for vol_id, err in errors:
        table.add_row(vol_id, f"[red]error: {err}[/red]", "")

    console.print(table)

    total_size = sum(dr.size_bytes for dr in results if not dr.skipped)
    downloaded_count = sum(1 for dr in results if not dr.skipped)
    skipped_count = sum(1 for dr in results if dr.skipped)

    parts = [f"[green]{downloaded_count} downloaded[/green]"]
    if skipped_count:
        parts.append(f"[dim]{skipped_count} skipped[/dim]")
    if errors:
        parts.append(f"[red]{len(errors)} failed[/red]")

    console.print(f"\nTotal: {', '.join(parts)} ({format_size(total_size)})")


async def _download(comic_id: str, volumes_str: str | None, fmt_str: str | None) -> None:
    config = get_or_create_config()
    dl_format = resolve_format(fmt_str or config.default_format)

    try:
        async with KmoeClient(config) as client:
            _apply_session(client)
            detail = await get_comic_detail(client, comic_id)

            if volumes_str:
                vol_ids = [v.strip() for v in volumes_str.split(",")]
            else:
                vol_ids = [v.vol_id for v in detail.volumes]

            if not vol_ids:
                console.print("[yellow]No volumes to download.[/yellow]")
                return

            # Show remaining quota before download
            user = await check_session(client)
            if user is not None:
                remaining = user.quota_remaining + user.quota_extra
                console.print(f"Quota: {remaining:.1f} / {user.quota_free_month:.1f} MB remaining")
                if remaining <= 0:
                    console.print("[yellow]Warning: quota may be exhausted[/yellow]")

            console.print(
                f"Downloading {len(vol_ids)} volume(s) of "
                f"[bold]{detail.meta.title}[/bold] as {dl_format.name} ..."
            )

            results, errors = await _download_with_progress(
                client, config, detail, vol_ids, dl_format
            )
            update_root_index(config)

    except KmoeError as exc:
        console.print(Panel(f"[red]{exc.message}[/red]", title="Error"))
        raise typer.Exit(1) from None

    _print_download_summary(results, errors)


# ---------------------------------------------------------------------------
# library
# ---------------------------------------------------------------------------


@app.command()
def library(
    *,
    verbose: _VerboseAnnotation = False,  # noqa: ARG001
) -> None:
    """List local library."""
    config = get_or_create_config()

    # Try the root index first for speed
    index = load_index(config)
    if index and index.comics:
        table = Table(title="Local Library")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="bold")
        table.add_column("Volumes")
        table.add_column("Complete")

        for c in index.comics:
            vol_str = (
                f"{c.downloaded_volumes}/{c.total_volumes}"
                if c.total_volumes > 0
                else str(c.downloaded_volumes)
            )
            complete_str = "[green]Yes[/green]" if c.is_complete else "[yellow]No[/yellow]"
            table.add_row(c.book_id, c.title, vol_str, complete_str)

        console.print(table)
        return

    # Fall back to scanning subdirectories
    entries = list_library(config)

    if not entries:
        console.print("[yellow]Library is empty.[/yellow]")
        return

    table = Table(title="Local Library")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="bold")
    table.add_column("Volumes")
    table.add_column("Complete")

    for entry in entries:
        dl_count = len(entry.downloaded_volumes)
        vol_str = f"{dl_count}/{entry.total_volumes}" if entry.total_volumes > 0 else str(dl_count)
        complete_str = "[green]Yes[/green]" if entry.is_complete else "[yellow]No[/yellow]"
        table.add_row(entry.book_id, entry.title, vol_str, complete_str)

    console.print(table)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@app.command()
def update(
    comic_id: Annotated[
        Optional[str],  # noqa: UP045
        typer.Argument(help="Comic ID to update (omit with --all for entire library)"),
    ] = None,
    fmt: Annotated[
        Optional[str],  # noqa: UP045
        typer.Option("-f", "--format", help="Download format (mobi/epub)"),
    ] = None,
    *,
    all_comics: Annotated[
        bool, typer.Option("--all", "-a", help="Update all comics in the library.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be downloaded without downloading.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
    verbose: _VerboseAnnotation = False,  # noqa: ARG001
) -> None:
    """Check for new volumes and download them."""
    if not comic_id and not all_comics:
        console.print("[red]Specify a COMIC_ID or use --all/-a.[/red]")
        raise typer.Exit(1)
    _run(_update(comic_id, fmt, all_comics=all_comics, dry_run=dry_run, yes=yes))


async def _update(
    comic_id: str | None,
    fmt_str: str | None,
    *,
    all_comics: bool,
    dry_run: bool,
    yes: bool,
) -> None:
    config = get_or_create_config()
    dl_format = resolve_format(fmt_str or config.default_format)

    entries = list_library(config)
    if not entries:
        console.print("[yellow]Library is empty. Nothing to update.[/yellow]")
        return

    # Filter to the requested comic(s)
    if not all_comics and comic_id:
        entries = [e for e in entries if e.comic_id == comic_id or e.book_id == comic_id]
        if not entries:
            console.print(f"[red]Comic {comic_id} not found in library.[/red]")
            raise typer.Exit(1) from None

    try:
        async with KmoeClient(config) as client:
            _apply_session(client)

            # Phase 1: check each entry for new volumes
            updates: list[tuple[LibraryEntry, ComicDetail, list[str]]] = []

            for entry in entries:
                cid = entry.comic_id or entry.book_id
                try:
                    detail = await get_comic_detail(client, cid)
                except KmoeError as exc:
                    console.print(f"[yellow]Skip {entry.title}: {exc.message}[/yellow]")
                    continue

                # Refresh metadata regardless
                refreshed = refresh_entry_from_detail(entry, detail)
                save_entry(config, refreshed, update_index=False)

                # Find missing or corrupt volumes
                stale = find_stale_volumes(config, refreshed, detail)

                if stale:
                    updates.append((refreshed, detail, stale))
                else:
                    console.print(
                        f"[dim]{entry.title}: up to date "
                        f"({len(refreshed.downloaded_volumes)}/{refreshed.total_volumes})[/dim]"
                    )

            if not updates:
                console.print("[green]Everything is up to date.[/green]")
                update_root_index(config)
                return

            # Phase 2: show summary
            console.print()
            summary_table = Table(title="Available Updates")
            summary_table.add_column("Title", style="bold")
            summary_table.add_column("Current")
            summary_table.add_column("New Volumes")

            total_new = 0
            for entry, _detail, missing in updates:
                summary_table.add_row(
                    entry.title,
                    f"{len(entry.downloaded_volumes)}/{entry.total_volumes}",
                    str(len(missing)),
                )
                total_new += len(missing)

            console.print(summary_table)
            console.print(f"\n{len(updates)} comic(s), {total_new} new volume(s)")

            if dry_run:
                console.print("[yellow]Dry run — no downloads performed.[/yellow]")
                update_root_index(config)
                return

            # Phase 3: confirm
            if not yes:
                proceed = typer.confirm("Download new volumes?")
                if not proceed:
                    console.print("[yellow]Cancelled.[/yellow]")
                    update_root_index(config)
                    return

            # Phase 4: download
            all_results: list[DownloadResult] = []
            all_errors: list[tuple[str, Exception]] = []

            for entry, detail, missing in updates:
                console.print(
                    f"\n[bold]{entry.title}[/bold]: downloading {len(missing)} volume(s) ..."
                )
                results, errors = await _download_with_progress(
                    client, config, detail, missing, dl_format
                )
                all_results.extend(results)
                all_errors.extend(errors)

            update_root_index(config)

    except KmoeError as exc:
        console.print(Panel(f"[red]{exc.message}[/red]", title="Error"))
        raise typer.Exit(1) from None

    _print_download_summary(all_results, all_errors)


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@app.command()
def scan(
    *,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview changes without modifying anything.")
    ] = False,
    verbose: _VerboseAnnotation = False,  # noqa: ARG001
) -> None:
    """Scan download directory, match comics to Kmoe, and create library metadata."""
    _run(_scan(dry_run))


async def _scan(dry_run: bool) -> None:
    from kmoe.library import get_comic_dir

    config = get_or_create_config()
    dl_dir = config.download_dir

    if not dl_dir.exists():
        console.print(f"[red]Download directory does not exist: {dl_dir}[/red]")
        raise typer.Exit(1) from None

    # Collect directories to process
    dirs_to_scan: list[tuple[Path, str]] = []

    for child in sorted(dl_dir.iterdir()):
        if not child.is_dir():
            continue

        # Skip if already has a library.json with a book_id
        lib_path = child / "library.json"
        if lib_path.exists():
            try:
                raw = lib_path.read_text(encoding="utf-8")
                entry = LibraryEntry.model_validate_json(raw)
                if entry.book_id:
                    console.print(
                        f"[dim]Skip {child.name} (already tracked: {entry.book_id})[/dim]"
                    )
                    continue
            except Exception:
                pass

        # Try to detect title from files
        title = detect_title_from_directory(child)
        if title is None:
            console.print(f"[yellow]Skip {child.name} (no recognizable files)[/yellow]")
            continue

        dirs_to_scan.append((child, title))

    if not dirs_to_scan:
        console.print("[green]All directories are already tracked.[/green]")
        if not dry_run:
            rebuild_index(config)
        return

    # Search Kmoe for each title
    console.print(f"\nFound {len(dirs_to_scan)} directory(ies) to scan:\n")

    try:
        async with KmoeClient(config) as client:
            _apply_session(client)

            for dir_path, title in dirs_to_scan:
                console.print(f"[bold]{dir_path.name}[/bold] -> title: [cyan]{title}[/cyan]")

                # Search for the comic
                try:
                    response = await search(
                        client, title, page=1, language=config.preferred_language
                    )
                except KmoeError as exc:
                    console.print(f"  [red]Search failed: {exc.message}[/red]")
                    continue

                if not response.results:
                    console.print("  [yellow]No search results[/yellow]")
                    continue

                # Find the best match (exact title match preferred)
                matched = None
                for r in response.results:
                    if r.title == title:
                        matched = r
                        break
                if matched is None:
                    matched = response.results[0]

                console.print(f"  Matched: [cyan]{matched.comic_id}[/cyan] - {matched.title}")

                if dry_run:
                    try:
                        detail = await get_comic_detail(client, matched.comic_id)
                    except KmoeError as exc:
                        console.print(f"  [red]Detail fetch failed: {exc.message}[/red]")
                        continue

                    files = scan_book_files(dir_path)
                    match_result = match_files_to_volumes(files, detail.volumes)
                    canonical = get_comic_dir(config, matched.comic_id, detail.meta.title)

                    console.print(
                        f"  Files: {len(files)}, Matched volumes: "
                        f"{len(match_result.matched)}/{len(detail.volumes)}"
                    )
                    if match_result.unmatched:
                        console.print(
                            f"  [yellow]Unmatched files: {len(match_result.unmatched)}[/yellow]"
                        )
                        for ufile in match_result.unmatched:
                            console.print(f"    - {ufile.name}")
                    if dir_path != canonical:
                        console.print(f"  Rename: {dir_path.name} -> {canonical.name}")
                    console.print()
                else:
                    try:
                        detail = await get_comic_detail(client, matched.comic_id)
                        entry, unmatched = import_directory(
                            config, dir_path, matched.comic_id, detail
                        )
                        console.print(
                            f"  [green]Imported: {len(entry.downloaded_volumes)} volumes"
                            f" (complete: {'Yes' if entry.is_complete else 'No'})[/green]"
                        )
                        if unmatched:
                            console.print(f"  [yellow]Unmatched files: {len(unmatched)}[/yellow]")
                            for ufile in unmatched:
                                console.print(f"    - {ufile.name}")
                    except KmoeError as exc:
                        console.print(f"  [red]Import failed: {exc.message}[/red]")
                    except Exception as exc:
                        console.print(f"  [red]Import failed: {exc}[/red]")

    except KmoeError as exc:
        console.print(Panel(f"[red]{exc.message}[/red]", title="Error"))
        raise typer.Exit(1) from None

    if not dry_run:
        rebuild_index(config)
        console.print("\n[green]Scan complete. Root index updated.[/green]")
    else:
        console.print("\n[yellow]Dry run complete. No changes made.[/yellow]")


# ---------------------------------------------------------------------------
# link
# ---------------------------------------------------------------------------


@app.command()
def link(
    directory: Annotated[str, typer.Argument(help="Directory path to link")],
    comic_id: Annotated[str, typer.Argument(help="Comic ID from Kmoe")],
    *,
    verbose: _VerboseAnnotation = False,  # noqa: ARG001
) -> None:
    """Manually link a local directory to a comic on Kmoe.

    Use this when scan fails to auto-detect a comic.

    Example: kmoe link /path/to/manga 12345
    """
    _run(_link(directory, comic_id))


async def _link(dir_path_str: str, comic_id: str) -> None:
    dir_path = Path(dir_path_str).expanduser()

    if not dir_path.exists() or not dir_path.is_dir():
        console.print(f"[red]Directory does not exist: {dir_path}[/red]")
        raise typer.Exit(1) from None

    config = get_or_create_config()

    try:
        async with KmoeClient(config) as client:
            _apply_session(client)
            detail = await get_comic_detail(client, comic_id)
    except KmoeError as exc:
        console.print(Panel(f"[red]{exc.message}[/red]", title="Error"))
        raise typer.Exit(1) from None

    try:
        entry, unmatched = import_directory(config, dir_path, comic_id, detail)
        console.print(f"[green]✓ Linked {dir_path.name}[/green]")
        console.print(f"  Book ID: {entry.book_id}")
        console.print(f"  Title: {entry.title}")
        console.print(f"  Matched volumes: {len(entry.downloaded_volumes)}")
        if unmatched:
            console.print(f"  [yellow]Unmatched files: {len(unmatched)}[/yellow]")
            for ufile in unmatched:
                console.print(f"    - {ufile.name}")
    except Exception as exc:
        console.print(f"[red]Link failed: {exc}[/red]")
        raise typer.Exit(1) from None
