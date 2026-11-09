#!/bin/bash
# 用本机 Microsoft Word / PowerPoint 把 docx / pptx 导出为 PDF。
# 用法: bash 英迈云/scripts/to_pdf.sh <file.docx|file.pptx> [more files...]
set -euo pipefail
for f in "$@"; do
  abs="$(cd "$(dirname "$f")" && pwd)/$(basename "$f")"
  out="${abs%.*}.pdf"
  case "$abs" in
    *.docx)
      osascript <<APPLESCRIPT
tell application "Microsoft Word"
  activate
  open POSIX file "$abs"
  set d to active document
  save as d file name "$out" file format format PDF
  close d saving no
end tell
APPLESCRIPT
      ;;
    *.pptx)
      osascript <<APPLESCRIPT
tell application "Microsoft PowerPoint"
  activate
  open POSIX file "$abs"
  set p to active presentation
  save p in POSIX file "$out" as save as PDF
  close p saving no
end tell
APPLESCRIPT
      ;;
    *) echo "skip (unsupported): $f" >&2; continue;;
  esac
  echo "pdf: $out"
done
