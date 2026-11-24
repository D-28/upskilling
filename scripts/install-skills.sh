#!/usr/bin/env bash
# Cross-machine, idempotent installer for skills/*/ into agent tool directories.
# Compatible with macOS (Bash 3.2+) and Linux (no GNU-only flags).

set -euo pipefail

readonly MARKER_FILE=".upskilling-managed"

# Defaults
MODE="symlink"          # symlink | copy | uninstall
SCOPE="user"            # user | repo
DRY_RUN=0
FORCE=0
REPO_ROOT=""
TOOLS_EXPLICIT=0
SELECTED_TOOLS=()
CUSTOM_TARGETS=()

# Counters for final summary
COUNT_INSTALLED=0
COUNT_UPDATED=0
COUNT_UNCHANGED=0
COUNT_REMOVED=0
COUNT_SKIPPED=0

usage() {
  cat <<'EOF'
Usage: scripts/install-skills.sh [OPTIONS]

Idempotently install (symlink or copy) all skills under skills/*/ into your
agent tool directories.

Options:
  --tool <name>        Target tool: antigravity | copilot | claude | all
                       (repeatable; default: all unless --target is given)
  --scope <scope>      Installation scope: user | repo (default: user)
  --repo-root <path>   Repository root for --scope repo (default: current dir)
  --target <path>      Explicit destination skills directory (e.g. for Codex)
  --dir <path>         Alias for --target
  --copy               Copy skill directories instead of symlinking
  --uninstall          Remove symlinks and managed copies created by this repo
  --force              Overwrite foreign symlinks or existing unmanaged dirs
  --dry-run            Print planned actions without modifying the filesystem
  -h, --help           Show this help message and exit

Tool destination paths:
  antigravity   user: ~/.gemini/jetski/skills    repo: <repo>/.agent/skills
  copilot       user: ~/.copilot/skills          repo: <repo>/.github/skills
  claude        user: ~/.claude/skills           repo: <repo>/.claude/skills
  Codex/other   use --target <dir> (or --dir <dir>)

Examples:
  ./scripts/install-skills.sh
  ./scripts/install-skills.sh --dry-run
  ./scripts/install-skills.sh --tool copilot --tool claude --scope repo
  ./scripts/install-skills.sh --copy --target ~/.codex/skills
  ./scripts/install-skills.sh --uninstall
EOF
}

log_info() {
  printf '%s\n' "$*"
}

log_warn() {
  printf 'WARN: %s\n' "$*" >&2
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# Portable canonical directory path without GNU readlink -f / realpath.
canonical_dir() {
  local dir="$1"
  (cd "$dir" 2>/dev/null && pwd -P)
}

# Resolve the directory containing this script, following symlinks portably.
resolve_script_dir() {
  local source_path="$0"
  local dir_path=""
  local link_target=""

  while [ -L "$source_path" ]; do
    dir_path="$(cd "$(dirname "$source_path")" && pwd -P)"
    link_target="$(readlink "$source_path")"
    case "$link_target" in
      /*) source_path="$link_target" ;;
      *)  source_path="$dir_path/$link_target" ;;
    esac
  done
  cd "$(dirname "$source_path")" && pwd -P
}

# Resolve a symlink's target to a canonical path if the target exists.
resolve_link_target() {
  local link_path="$1"
  local raw_target=""
  local link_dir=""
  local combined=""

  raw_target="$(readlink "$link_path")"
  case "$raw_target" in
    /*) combined="$raw_target" ;;
    *)
      link_dir="$(canonical_dir "$(dirname "$link_path")")"
      combined="$link_dir/$raw_target"
      ;;
  esac

  if [ -d "$combined" ]; then
    canonical_dir "$combined"
  else
    printf '%s\n' "$combined"
  fi
}

# Check if a value is already present in an array of arguments.
array_contains() {
  local needle="$1"
  shift
  local item=""
  for item in "$@"; do
    if [ "$item" = "$needle" ]; then
      return 0
    fi
  done
  return 1
}

add_tool() {
  local raw_tool="$1"
  local tool=""
  tool="$(printf '%s' "$raw_tool" | tr '[:upper:]' '[:lower:]')"
  case "$tool" in
    antigravity|copilot|claude)
      if ! array_contains "$tool" ${SELECTED_TOOLS[@]+"${SELECTED_TOOLS[@]}"}; then
        SELECTED_TOOLS+=("$tool")
      fi
      ;;
    all)
      add_tool "antigravity"
      add_tool "copilot"
      add_tool "claude"
      ;;
    *)
      die "Unsupported --tool value '$raw_tool'. Expected: antigravity, copilot, claude, or all."
      ;;
  esac
}

require_arg_value() {
  local flag="$1"
  local remaining="$2"
  if [ "$remaining" -lt 2 ]; then
    die "Missing value for $flag"
  fi
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --tool)
        require_arg_value "$1" "$#"
        TOOLS_EXPLICIT=1
        add_tool "$2"
        shift 2
        ;;
      --tool=*)
        TOOLS_EXPLICIT=1
        add_tool "${1#--tool=}"
        shift
        ;;
      --scope)
        require_arg_value "$1" "$#"
        SCOPE="$2"
        shift 2
        ;;
      --scope=*)
        SCOPE="${1#--scope=}"
        shift
        ;;
      --repo-root)
        require_arg_value "$1" "$#"
        REPO_ROOT="$2"
        shift 2
        ;;
      --repo-root=*)
        REPO_ROOT="${1#--repo-root=}"
        shift
        ;;
      --target|--dir)
        require_arg_value "$1" "$#"
        CUSTOM_TARGETS+=("$2")
        shift 2
        ;;
      --target=*)
        CUSTOM_TARGETS+=("${1#--target=}")
        shift
        ;;
      --dir=*)
        CUSTOM_TARGETS+=("${1#--dir=}")
        shift
        ;;
      --copy)
        if [ "$MODE" = "uninstall" ]; then
          die "Cannot combine --copy and --uninstall."
        fi
        MODE="copy"
        shift
        ;;
      --uninstall)
        if [ "$MODE" = "copy" ]; then
          die "Cannot combine --copy and --uninstall."
        fi
        MODE="uninstall"
        shift
        ;;
      --force)
        FORCE=1
        shift
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1 (run with --help for usage)"
        ;;
    esac
  done

  case "$SCOPE" in
    user|repo) ;;
    *) die "Unsupported --scope value '$SCOPE'. Expected: user or repo." ;;
  esac

  if [ "$TOOLS_EXPLICIT" -eq 0 ] && [ "${#CUSTOM_TARGETS[@]}" -eq 0 ]; then
    add_tool "all"
  fi
}

resolve_tool_dir() {
  local tool="$1"
  local base_root="$2"

  if [ "$SCOPE" = "user" ]; then
    case "$tool" in
      antigravity) printf '%s\n' "$HOME/.gemini/jetski/skills" ;;
      copilot)     printf '%s\n' "$HOME/.copilot/skills" ;;
      claude)      printf '%s\n' "$HOME/.claude/skills" ;;
      *)           die "Internal error: unknown tool '$tool'" ;;
    esac
  else
    case "$tool" in
      antigravity) printf '%s\n' "$base_root/.agent/skills" ;;
      copilot)     printf '%s\n' "$base_root/.github/skills" ;;
      claude)      printf '%s\n' "$base_root/.claude/skills" ;;
      *)           die "Internal error: unknown tool '$tool'" ;;
    esac
  fi
}

ensure_parent_dir() {
  local dir="$1"
  if [ "$DRY_RUN" -eq 1 ]; then
    return 0
  fi
  if [ ! -d "$dir" ]; then
    mkdir -p "$dir"
  fi
}

write_managed_copy() {
  local src_dir="$1"
  local dest_path="$2"

  cp -R "$src_dir" "$dest_path"
  printf 'source=%s\n' "$src_dir" > "$dest_path/$MARKER_FILE"
}

install_symlink_one() {
  local skill_name="$1"
  local src_dir="$2"
  local dest_root="$3"
  local dest_path="$dest_root/$skill_name"
  local existing_target=""

  if [ -L "$dest_path" ]; then
    existing_target="$(resolve_link_target "$dest_path")"
    if [ "$existing_target" = "$src_dir" ]; then
      log_info "  [UNCHANGED] $dest_path -> $src_dir"
      COUNT_UNCHANGED=$((COUNT_UNCHANGED + 1))
      return 0
    fi
    if [ "$FORCE" -eq 1 ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        log_info "  [DRY-RUN] WOULD RELINK $dest_path -> $src_dir (was -> $existing_target)"
      else
        rm -f "$dest_path"
        ln -s "$src_dir" "$dest_path"
        log_info "  [UPDATED]   $dest_path -> $src_dir (replaced symlink)"
      fi
      COUNT_UPDATED=$((COUNT_UPDATED + 1))
      return 0
    fi
    log_warn "Skipping foreign symlink $dest_path -> $existing_target (re-run with --force to replace)"
    COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
    return 0
  fi

  if [ -e "$dest_path" ]; then
    if [ "$FORCE" -eq 1 ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        log_info "  [DRY-RUN] WOULD REPLACE $dest_path -> $src_dir"
      else
        rm -rf "$dest_path"
        ln -s "$src_dir" "$dest_path"
        log_info "  [UPDATED]   $dest_path -> $src_dir (replaced existing path)"
      fi
      COUNT_UPDATED=$((COUNT_UPDATED + 1))
      return 0
    fi
    log_warn "Skipping existing non-symlink path $dest_path (re-run with --force to replace)"
    COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
    return 0
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    log_info "  [DRY-RUN] WOULD LINK $dest_path -> $src_dir"
  else
    ensure_parent_dir "$dest_root"
    ln -s "$src_dir" "$dest_path"
    log_info "  [LINKED]    $dest_path -> $src_dir"
  fi
  COUNT_INSTALLED=$((COUNT_INSTALLED + 1))
}

install_copy_one() {
  local skill_name="$1"
  local src_dir="$2"
  local dest_root="$3"
  local dest_path="$dest_root/$skill_name"
  local existing_target=""

  if [ -L "$dest_path" ]; then
    existing_target="$(resolve_link_target "$dest_path")"
    if [ "$existing_target" = "$src_dir" ] || [ "$FORCE" -eq 1 ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        log_info "  [DRY-RUN] WOULD REPLACE SYMLINK WITH COPY $dest_path <- $src_dir"
      else
        rm -f "$dest_path"
        write_managed_copy "$src_dir" "$dest_path"
        log_info "  [UPDATED]   $dest_path <- $src_dir (converted symlink to managed copy)"
      fi
      COUNT_UPDATED=$((COUNT_UPDATED + 1))
      return 0
    fi
    log_warn "Skipping foreign symlink $dest_path -> $existing_target (re-run with --force to replace)"
    COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
    return 0
  fi

  if [ -d "$dest_path" ]; then
    if [ -f "$dest_path/$MARKER_FILE" ] || [ "$FORCE" -eq 1 ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        log_info "  [DRY-RUN] WOULD REFRESH COPY $dest_path <- $src_dir"
      else
        rm -rf "$dest_path"
        write_managed_copy "$src_dir" "$dest_path"
        log_info "  [UPDATED]   $dest_path <- $src_dir (refreshed copy)"
      fi
      COUNT_UPDATED=$((COUNT_UPDATED + 1))
      return 0
    fi
    log_warn "Skipping existing unmanaged directory $dest_path (re-run with --force to overwrite)"
    COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
    return 0
  fi

  if [ -e "$dest_path" ]; then
    if [ "$FORCE" -eq 1 ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        log_info "  [DRY-RUN] WOULD REPLACE FILE WITH COPY $dest_path <- $src_dir"
      else
        rm -rf "$dest_path"
        write_managed_copy "$src_dir" "$dest_path"
        log_info "  [UPDATED]   $dest_path <- $src_dir (replaced existing file)"
      fi
      COUNT_UPDATED=$((COUNT_UPDATED + 1))
      return 0
    fi
    log_warn "Skipping existing non-directory path $dest_path (re-run with --force to overwrite)"
    COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
    return 0
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    log_info "  [DRY-RUN] WOULD COPY $dest_path <- $src_dir"
  else
    ensure_parent_dir "$dest_root"
    write_managed_copy "$src_dir" "$dest_path"
    log_info "  [COPIED]    $dest_path <- $src_dir"
  fi
  COUNT_INSTALLED=$((COUNT_INSTALLED + 1))
}

uninstall_one() {
  local skill_name="$1"
  local src_dir="$2"
  local dest_root="$3"
  local dest_path="$dest_root/$skill_name"
  local existing_target=""

  if [ -L "$dest_path" ]; then
    existing_target="$(resolve_link_target "$dest_path")"
    if [ "$existing_target" = "$src_dir" ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        log_info "  [DRY-RUN] WOULD REMOVE SYMLINK $dest_path"
      else
        rm -f "$dest_path"
        log_info "  [REMOVED]   $dest_path (symlink)"
      fi
      COUNT_REMOVED=$((COUNT_REMOVED + 1))
      return 0
    fi
    log_warn "Skipping foreign symlink $dest_path -> $existing_target"
    COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
    return 0
  fi

  if [ -d "$dest_path" ]; then
    if [ -f "$dest_path/$MARKER_FILE" ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        log_info "  [DRY-RUN] WOULD REMOVE MANAGED COPY $dest_path"
      else
        rm -rf "$dest_path"
        log_info "  [REMOVED]   $dest_path (managed copy)"
      fi
      COUNT_REMOVED=$((COUNT_REMOVED + 1))
      return 0
    fi
    log_warn "Skipping unmanaged directory $dest_path"
    COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
    return 0
  fi

  if [ -e "$dest_path" ]; then
    log_warn "Skipping unmanaged file $dest_path"
    COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
    return 0
  fi

  log_info "  [ABSENT]    $dest_path"
  COUNT_UNCHANGED=$((COUNT_UNCHANGED + 1))
}

main() {
  parse_args "$@"

  local script_dir=""
  local repo_dir=""
  local skills_src_dir=""
  script_dir="$(resolve_script_dir)"
  repo_dir="$(canonical_dir "$script_dir/..")"
  skills_src_dir="$repo_dir/skills"

  if [ ! -d "$skills_src_dir" ]; then
    die "Skills source directory not found: $skills_src_dir"
  fi

  # Collect skill directories that contain SKILL.md
  local skill_dirs=()
  local candidate=""
  for candidate in "$skills_src_dir"/*; do
    if [ -d "$candidate" ] && [ -f "$candidate/SKILL.md" ]; then
      skill_dirs+=("$(canonical_dir "$candidate")")
    fi
  done

  if [ "${#skill_dirs[@]}" -eq 0 ]; then
    die "No skills (directories with SKILL.md) found under $skills_src_dir"
  fi

  # Resolve base repo root when --scope repo is active
  local effective_repo_root=""
  if [ "$SCOPE" = "repo" ]; then
    if [ -n "$REPO_ROOT" ]; then
      if [ ! -d "$REPO_ROOT" ]; then
        die "Repository root does not exist: $REPO_ROOT"
      fi
      effective_repo_root="$(canonical_dir "$REPO_ROOT")"
    else
      effective_repo_root="$(pwd -P)"
    fi
  fi

  # Build deduplicated list of destination directories
  local dest_dirs=()
  local tool=""
  local resolved_dir=""
  for tool in ${SELECTED_TOOLS[@]+"${SELECTED_TOOLS[@]}"}; do
    resolved_dir="$(resolve_tool_dir "$tool" "$effective_repo_root")"
    if ! array_contains "$resolved_dir" ${dest_dirs[@]+"${dest_dirs[@]}"}; then
      dest_dirs+=("$resolved_dir")
    fi
  done

  local custom=""
  for custom in ${CUSTOM_TARGETS[@]+"${CUSTOM_TARGETS[@]}"}; do
    if [ -z "$custom" ]; then
      die "Empty --target/--dir path is not allowed."
    fi
    if ! array_contains "$custom" ${dest_dirs[@]+"${dest_dirs[@]}"}; then
      dest_dirs+=("$custom")
    fi
  done

  local dry_label=""
  if [ "$DRY_RUN" -eq 1 ]; then
    dry_label=" (dry-run)"
  fi
  log_info "Skills source: $skills_src_dir (${#skill_dirs[@]} skills)"
  log_info "Mode: $MODE$dry_label | Scope: $SCOPE"

  local dest_root=""
  local src_dir=""
  local skill_name=""
  for dest_root in "${dest_dirs[@]}"; do
    log_info "Target: $dest_root"
    for src_dir in "${skill_dirs[@]}"; do
      skill_name="$(basename "$src_dir")"
      case "$MODE" in
        symlink)   install_symlink_one "$skill_name" "$src_dir" "$dest_root" ;;
        copy)      install_copy_one "$skill_name" "$src_dir" "$dest_root" ;;
        uninstall) uninstall_one "$skill_name" "$src_dir" "$dest_root" ;;
      esac
    done
  done

  log_info "Summary: installed=$COUNT_INSTALLED updated=$COUNT_UPDATED unchanged=$COUNT_UNCHANGED removed=$COUNT_REMOVED skipped=$COUNT_SKIPPED"
}

main "$@"
