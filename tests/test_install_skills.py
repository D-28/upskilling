"""Tests for scripts/install-skills.sh (cross-machine, macOS/Linux-safe skills installer)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "scripts" / "install-skills.sh"
SKILLS_DIR = REPO_ROOT / "skills"
EXPECTED_SKILLS = sorted(
    p.name for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
)


def run_installer(
    *args: str,
    home: Path,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        cwd=str(cwd or REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_bash_syntax_check() -> None:
    result = subprocess.run(
        ["bash", "-n", str(INSTALLER)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_no_gnu_only_or_bash4_constructs() -> None:
    """Keep the script compatible with macOS default Bash 3.2 and BSD coreutils."""
    code_lines = [
        line
        for line in INSTALLER.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)
    banned_patterns = [
        r"\breadlink\s+-f\b",
        r"\brealpath\b",
        r"\bln\s+-[a-zA-Z]*[fTn][a-zA-Z]*\b",
        r"\bcp\s+-[a-zA-Z]*[aT][a-zA-Z]*\b",
        r"\bdeclare\s+-A\b",
        r"\bmapfile\b",
        r"\breadarray\b",
    ]
    for pattern in banned_patterns:
        assert not re.search(pattern, code), f"Found non-macOS-safe pattern: {pattern}"


def test_dry_run_makes_no_changes(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    res = run_installer("--dry-run", home=fake_home)
    assert res.returncode == 0, res.stderr
    assert "[DRY-RUN]" in res.stdout
    assert list(fake_home.iterdir()) == []


def test_default_user_scope_all_tools_and_idempotent_rerun(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    first = run_installer(home=fake_home)
    assert first.returncode == 0, first.stderr
    expected_total = len(EXPECTED_SKILLS) * 3
    assert f"installed={expected_total}" in first.stdout

    expected_roots = [
        fake_home / ".gemini" / "jetski" / "skills",
        fake_home / ".copilot" / "skills",
        fake_home / ".claude" / "skills",
    ]
    for root in expected_roots:
        for skill in EXPECTED_SKILLS:
            link_path = root / skill
            assert link_path.is_symlink()
            assert link_path.resolve() == (SKILLS_DIR / skill).resolve()

    second = run_installer(home=fake_home)
    assert second.returncode == 0, second.stderr
    assert f"installed=0 updated=0 unchanged={expected_total} removed=0 skipped=0" in second.stdout


def test_repo_scope_explicit_and_cwd(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    project_a = tmp_path / "project-a"
    project_a.mkdir()
    project_b = tmp_path / "project-b"
    project_b.mkdir()

    # Explicit --repo-root
    res_a = run_installer(
        "--scope",
        "repo",
        "--repo-root",
        str(project_a),
        "--tool",
        "all",
        home=fake_home,
    )
    assert res_a.returncode == 0, res_a.stderr
    for rel in (".agent/skills", ".github/skills", ".claude/skills"):
        for skill in EXPECTED_SKILLS:
            link_path = project_a / rel / skill
            assert link_path.is_symlink()
            assert link_path.resolve() == (SKILLS_DIR / skill).resolve()

    # Implicit $PWD when --repo-root is omitted
    res_b = run_installer("--scope", "repo", "--tool", "copilot", home=fake_home, cwd=project_b)
    assert res_b.returncode == 0, res_b.stderr
    for skill in EXPECTED_SKILLS:
        assert (project_b / ".github" / "skills" / skill).is_symlink()
    assert not (project_b / ".claude").exists()
    assert not (project_b / ".agent").exists()


def test_custom_target_does_not_touch_default_tools(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    codex_dir = tmp_path / "codex-skills"
    extra_dir = tmp_path / "extra-skills"

    res = run_installer("--target", str(codex_dir), "--dir", str(extra_dir), home=fake_home)
    assert res.returncode == 0, res.stderr

    for root in (codex_dir, extra_dir):
        for skill in EXPECTED_SKILLS:
            assert (root / skill).is_symlink()

    # Default user tool directories should remain untouched
    assert list(fake_home.iterdir()) == []


def test_copy_mode_and_idempotent_refresh(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    first = run_installer("--copy", "--tool", "copilot", home=fake_home)
    assert first.returncode == 0, first.stderr

    copilot_skills = fake_home / ".copilot" / "skills"
    for skill in EXPECTED_SKILLS:
        dest = copilot_skills / skill
        assert dest.is_dir() and not dest.is_symlink()
        assert (dest / "SKILL.md").read_text(encoding="utf-8") == (
            SKILLS_DIR / skill / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert (dest / ".upskilling-managed").is_file()

    # Plant a stale file inside a managed copy and re-run --copy
    stale_file = copilot_skills / EXPECTED_SKILLS[0] / "stale.txt"
    stale_file.write_text("old", encoding="utf-8")

    second = run_installer("--copy", "--tool", "copilot", home=fake_home)
    assert second.returncode == 0, second.stderr
    assert f"updated={len(EXPECTED_SKILLS)}" in second.stdout
    assert not stale_file.exists()


def test_preserves_unmanaged_directory_unless_force(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    target_skill = EXPECTED_SKILLS[0]
    user_dir = fake_home / ".claude" / "skills" / target_skill
    user_dir.mkdir(parents=True)
    custom_file = user_dir / "CUSTOM.txt"
    custom_file.write_text("do-not-overwrite", encoding="utf-8")

    # Symlink mode skips unmanaged dir cleanly
    res_sym = run_installer("--tool", "claude", home=fake_home)
    assert res_sym.returncode == 0
    assert "Skipping existing non-symlink path" in res_sym.stderr
    assert "skipped=1" in res_sym.stdout
    assert custom_file.read_text(encoding="utf-8") == "do-not-overwrite"

    # Copy mode also skips unmanaged dir cleanly
    res_copy = run_installer("--copy", "--tool", "claude", home=fake_home)
    assert res_copy.returncode == 0
    assert "Skipping existing unmanaged directory" in res_copy.stderr
    assert custom_file.read_text(encoding="utf-8") == "do-not-overwrite"

    # With --force, symlink mode replaces it
    res_force = run_installer("--force", "--tool", "claude", home=fake_home)
    assert res_force.returncode == 0, res_force.stderr
    assert user_dir.is_symlink()
    assert user_dir.resolve() == (SKILLS_DIR / target_skill).resolve()


def test_preserves_foreign_symlink_unless_force(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    foreign_src = tmp_path / "foreign-skill"
    foreign_src.mkdir()

    target_skill = EXPECTED_SKILLS[0]
    copilot_dir = fake_home / ".copilot" / "skills"
    copilot_dir.mkdir(parents=True)
    link_path = copilot_dir / target_skill
    link_path.symlink_to(foreign_src)

    res = run_installer("--tool", "copilot", home=fake_home)
    assert res.returncode == 0
    assert "Skipping foreign symlink" in res.stderr
    assert link_path.resolve() == foreign_src.resolve()

    res_force = run_installer("--force", "--tool", "copilot", home=fake_home)
    assert res_force.returncode == 0, res_force.stderr
    assert link_path.resolve() == (SKILLS_DIR / target_skill).resolve()


def test_converts_own_symlink_to_managed_copy(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    res_sym = run_installer("--tool", "antigravity", home=fake_home)
    assert res_sym.returncode == 0, res_sym.stderr

    res_copy = run_installer("--copy", "--tool", "antigravity", home=fake_home)
    assert res_copy.returncode == 0, res_copy.stderr
    assert f"updated={len(EXPECTED_SKILLS)}" in res_copy.stdout

    ag_skills = fake_home / ".gemini" / "jetski" / "skills"
    for skill in EXPECTED_SKILLS:
        dest = ag_skills / skill
        assert dest.is_dir() and not dest.is_symlink()
        assert (dest / ".upskilling-managed").is_file()


def test_uninstall_removes_only_managed_entries(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    foreign_src = tmp_path / "foreign-skill"
    foreign_src.mkdir()

    # Install symlinks to copilot and managed copies to claude
    assert run_installer("--tool", "copilot", home=fake_home).returncode == 0
    assert run_installer("--copy", "--tool", "claude", home=fake_home).returncode == 0

    # Replace one copilot skill with a foreign symlink, and one claude skill with an unmanaged dir
    protected_skill = EXPECTED_SKILLS[0]
    copilot_foreign = fake_home / ".copilot" / "skills" / protected_skill
    copilot_foreign.unlink()
    copilot_foreign.symlink_to(foreign_src)

    claude_unmanaged = fake_home / ".claude" / "skills" / protected_skill
    (claude_unmanaged / ".upskilling-managed").unlink()

    res = run_installer("--uninstall", "--tool", "copilot", "--tool", "claude", home=fake_home)
    assert res.returncode == 0
    assert "skipped=2" in res.stdout

    # Managed entries removed, protected entries untouched
    assert copilot_foreign.is_symlink() and copilot_foreign.resolve() == foreign_src.resolve()
    assert claude_unmanaged.is_dir() and (claude_unmanaged / "SKILL.md").is_file()
    for skill in EXPECTED_SKILLS[1:]:
        assert not (fake_home / ".copilot" / "skills" / skill).exists()
        assert not (fake_home / ".claude" / "skills" / skill).exists()


def test_paths_with_spaces(tmp_path: Path) -> None:
    fake_home = tmp_path / "home with spaces"
    fake_home.mkdir()
    custom_target = tmp_path / "my custom skills dir"

    res_sym = run_installer("--target", str(custom_target), home=fake_home)
    assert res_sym.returncode == 0, res_sym.stderr
    for skill in EXPECTED_SKILLS:
        assert (custom_target / skill).is_symlink()

    res_copy = run_installer("--copy", "--target", str(custom_target), home=fake_home)
    assert res_copy.returncode == 0, res_copy.stderr
    for skill in EXPECTED_SKILLS:
        dest = custom_target / skill
        assert dest.is_dir() and not dest.is_symlink()
        assert (dest / ".upskilling-managed").is_file()


@pytest.mark.parametrize(
    "bad_args",
    [
        ("--tool", "unknown-tool"),
        ("--scope", "global"),
        ("--copy", "--uninstall"),
        ("--unknown-flag",),
    ],
)
def test_invalid_arguments_fail_cleanly(tmp_path: Path, bad_args: tuple[str, ...]) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    res = run_installer(*bad_args, home=fake_home)
    assert res.returncode != 0
    assert "ERROR:" in res.stderr
