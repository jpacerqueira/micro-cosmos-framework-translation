#!/usr/bin/env bash
# Load a gcloud-run-setup*.txt deploy profile into the CURRENT shell.
#
# Every GCP deploy path in this repo is env-var driven — deployment/deploy.py,
# deploy_cloudrun-vllm-llms.py, deploy_cloudrun-lmstudio-llms.py and
# deploy_cloudrun-micro-cosmos-app.py read their whole config via os.environ.get().
# The gcloud-run-setup*.txt files hold those profiles; this script exports them
# so you don't hand-type an export block before deploying to GCP.
#
#   source ./deploy-vars-in-env.sh              # gcloud-run-setup-vllm.txt (default)
#   source ./deploy-vars-in-env.sh vllm-lite    # gcloud-run-setup-vllm-lite.txt
#   source ./deploy-vars-in-env.sh lmstudio     # gcloud-run-setup-lmstudio.txt
#   source ./deploy-vars-in-env.sh base         # gcloud-run-setup.txt
#   source ./deploy-vars-in-env.sh ./some/other.txt
#   source ./deploy-vars-in-env.sh -q vllm      # summary line only
#
# MUST be sourced, not executed — a child process cannot export into its parent.
#
# Deliberately NO `set -euo pipefail`: unlike deployment/*-entrypoint.sh (which
# are executed), this runs inside your live interactive shell, where those
# options would persist and a later unrelated non-zero exit would kill it.

# --- sourced, or executed by mistake? (bash and zsh) -------------------------
_dv_sourced=1
if [ -n "${ZSH_VERSION:-}" ]; then
  _dv_sourced=0
  case "${ZSH_EVAL_CONTEXT:-}" in *:file*) _dv_sourced=1 ;; esac
elif [ -n "${BASH_VERSION:-}" ]; then
  _dv_sourced=0
  if [ "${BASH_SOURCE[0]:-}" != "$0" ]; then _dv_sourced=1; fi
fi

if [ "$_dv_sourced" -ne 1 ]; then
  echo "deploy-vars-in-env.sh must be sourced, not executed — exported vars" >&2
  echo "would die with this subshell." >&2
  echo "" >&2
  echo "  usage: source ./deploy-vars-in-env.sh [-q] [profile|file]" >&2
  exit 1
fi

# Resolve profiles relative to this script, not $PWD. Must happen at top level:
# inside a zsh function $0 is the function name, not the sourced file.
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  _dv_self="${BASH_SOURCE[0]}"
else
  _dv_self="$0"          # zsh sets $0 to the sourced file
fi
_dv_dir=$(cd "$(dirname "$_dv_self")" 2>/dev/null && pwd)
[ -n "$_dv_dir" ] || _dv_dir="."

# Everything below runs in a function so its scratch variables are `local` and
# never leak into the caller's shell; `export` inside a function still exports
# to the shell's real environment, which is the whole point.
_dv_load() {
  local here="$1"; shift
  local quiet=0 want="" arg="" file="" rc=0
  local p b n line key val count=0 lineno=0

  for arg in "$@"; do
    case "$arg" in
      -q|--quiet) quiet=1 ;;
      -h|--help)
        echo "usage: source ./deploy-vars-in-env.sh [-q] [profile|file]"
        echo "  profile: vllm (default) | vllm-lite | lmstudio | base | any path"
        return 0 ;;
      -*) echo "[deploy-vars] unknown option: $arg" >&2; return 1 ;;
      *)  want="$arg" ;;
    esac
  done

  case "$want" in
    "")            file="$here/gcloud-run-setup-vllm.txt" ;;
    base|default)  file="$here/gcloud-run-setup.txt" ;;
    *)
      if [ -f "$want" ]; then
        file="$want"
      elif [ -f "$here/gcloud-run-setup-$want.txt" ]; then
        file="$here/gcloud-run-setup-$want.txt"
      elif [ -f "$here/$want" ]; then
        file="$here/$want"
      else
        file="$want"                   # reported as missing just below
      fi ;;
  esac

  if [ ! -f "$file" ]; then
    echo "[deploy-vars] no such profile or file: $want" >&2
    echo "available profiles in $here:" >&2
    for p in "$here"/gcloud-run-setup*.txt; do
      [ -f "$p" ] || continue
      b="${p##*/}"
      n="${b#gcloud-run-setup}"; n="${n%.txt}"; n="${n#-}"
      printf '  %-12s %s\n' "${n:-base}" "$b" >&2
    done
    return 1
  fi

  [ "$quiet" -eq 1 ] || echo "[deploy-vars] loading ${file##*/}"

  while IFS= read -r line || [ -n "$line" ]; do   # last line may lack a newline
    lineno=$((lineno + 1))
    line="${line%$'\r'}"                          # tolerate CRLF
    line=$(_dv_trim "$line")
    case "$line" in
      ''|'#'*) continue ;;                        # blank / comment
      export\ *|export$'\t'*) line=$(_dv_trim "${line#export}") ;;
    esac
    case "$line" in
      *=*) ;;
      *) echo "[deploy-vars] line $lineno: no '=', skipped: $line" >&2
         continue ;;
    esac

    key=$(_dv_trim "${line%%=*}")                 # split on the FIRST '=' only
    val=$(_dv_trim "${line#*=}")
    case "$val" in                                # one layer of matching quotes
      \"*\") val="${val#\"}"; val="${val%\"}" ;;
      \'*\') val="${val#\'}"; val="${val%\'}" ;;
    esac

    case "$key" in                                # valid shell identifier?
      ''|[!A-Za-z_]*|*[!A-Za-z0-9_]*)
        echo "[deploy-vars] line $lineno: invalid name '$key', skipped" >&2
        continue ;;
    esac

    # Quoted assignment — never `eval`, never `export $line`. Real values in
    # these files carry shell metacharacters (DEMO_USERNAME=demo<number>,
    # HF_TOKEN=<...>) that would otherwise be parsed as redirections.
    export "$key=$val"
    count=$((count + 1))

    if [ "$quiet" -eq 0 ]; then
      case "$key" in
        *TOKEN*|*KEY*|*PASSWORD*|*SECRET*) printf '  %s=***\n' "$key" ;;
        *) printf '  %s=%s\n' "$key" "$val" ;;
      esac
    fi
  done < "$file"

  echo "[deploy-vars] ${file##*/} → $count vars exported"
  return $rc
}

_dv_trim() {                                      # strip leading + trailing space
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

_dv_load "$_dv_dir" "$@"
_dv_rc=$?
unset -f _dv_load _dv_trim
unset _dv_sourced _dv_self _dv_dir
if [ "$_dv_rc" -eq 0 ]; then unset _dv_rc; return 0; fi
unset _dv_rc
return 1
