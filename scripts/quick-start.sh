#!/usr/bin/env bash
# Install the local web version without replacing an existing installation.
set -euo pipefail

repo_url='https://github.com/xiaoyoumi9924/handwritten-notes.git'
install_dir="${MIAOBI_INSTALL_DIR:-$HOME/.miaobi/app}"
bin_dir="${MIAOBI_BIN_DIR:-$HOME/.local/bin}"
launcher="$bin_dir/miaobi"

for cmd in git python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "缺少 $cmd，请先安装后重试。" >&2
    exit 1
  fi
done
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  echo '需要 Python 3.10 或更高版本。' >&2
  exit 1
fi
if [ -e "$launcher" ] && ! grep -q '^# Managed by Miaobi quick-start$' "$launcher"; then
  echo "已存在 $launcher，不会覆盖。请先处理该文件后重试。" >&2
  exit 1
fi
if [ -e "$install_dir" ] && [ ! -f "$install_dir/requirements.txt" ]; then
  echo "安装目录已存在且不是妙笔工坊：$install_dir" >&2
  exit 1
fi
if [ ! -d "$install_dir" ]; then
  mkdir -p "$(dirname "$install_dir")"
  stage=$(mktemp -d "$(dirname "$install_dir")/.miaobi-install.XXXXXXXX")
  trap 'if [ -n "${stage:-}" ] && [ -d "$stage" ]; then rm -r "$stage"; fi' EXIT
  echo '正在下载妙笔工坊…'
  git clone --depth 1 "$repo_url" "$stage/source"
  test -f "$stage/source/requirements.txt"
  mv "$stage/source" "$install_dir"
fi
if [ ! -x "$install_dir/.venv/bin/python" ]; then
  python3 -m venv "$install_dir/.venv"
fi
echo '正在安装依赖…'
"$install_dir/.venv/bin/python" -m pip install -r "$install_dir/requirements.txt"
mkdir -p "$bin_dir"
cat > "$launcher" <<'LAUNCHER'
#!/usr/bin/env bash
# Managed by Miaobi quick-start
set -euo pipefail
app="${MIAOBI_INSTALL_DIR:-$HOME/.miaobi/app}"
cd "$app"
export PYTHONPATH="$app/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$app/.venv/bin/python" -m markdown_to_handwrite.quickstart "$@"
LAUNCHER
chmod +x "$launcher"
case ":$PATH:" in
  *":$bin_dir:"*) ;;
  *)
    if [ "$bin_dir" = "$HOME/.local/bin" ]; then
      case "${SHELL:-}" in
        */zsh) profile="$HOME/.zshrc" ;;
        *) profile="$HOME/.bashrc" ;;
      esac
      if ! grep -Fq '# Miaobi command path' "$profile" 2>/dev/null; then
        printf '\n# Miaobi command path\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$profile"
      fi
      echo '已添加命令路径；下次请重新打开终端后运行 miaobi。'
    else
      echo "请将 $bin_dir 加入 PATH，以便下次运行 miaobi。"
    fi
    ;;
esac
echo '部署完成，正在打开妙笔工坊。按 Ctrl+C 停止。'
exec "$launcher"
