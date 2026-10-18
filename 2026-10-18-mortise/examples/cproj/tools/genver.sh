#!/bin/sh
# Emit a header from VERSION, ignoring comment lines: editing a comment
# regenerates the same header, so Mortise's early cutoff skips every compile.
v=$(grep -v '^#' "$1" | head -n1)
printf '#define APP_VERSION "%s"\n' "$v"
