#!/usr/bin/env bash
# Prints a screen full of terminal features; rendered by `cathode run` into examples/showcase.*
printf '\e[1;38;5;81m ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\e[0m\n'
printf '\e[1;38;5;81m ┃\e[0m  \e[1mCathode\e[0m — a terminal emulator, from scratch  \e[1;38;5;81m┃\e[0m\n'
printf '\e[1;38;5;81m ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\e[0m\n\n'
printf ' \e[1mbold\e[0m \e[2mdim\e[0m \e[3mitalic\e[0m \e[4munderline\e[0m \e[4:3;58;2;255;80;80mcurly\e[0m \e[9mstrike\e[0m \e[7minverse\e[0m \e[53moverline\e[0m\n\n'
printf ' 16 colours  '; for i in 0 1 2 3 4 5 6 7; do printf '\e[4%dm  \e[0m' $i; done; printf ' '; for i in 0 1 2 3 4 5 6 7; do printf '\e[10%dm  \e[0m' $i; done; echo
printf ' 256 colours '; for i in $(seq 16 2 87); do printf '\e[48;5;%dm \e[0m' $i; done; echo
printf ' truecolour  '; for i in $(seq 0 5 235); do printf '\e[48;2;%d;%d;%dm \e[0m' $i $((255-i)) 160; done; echo; echo
printf ' wide  \e[38;5;215m日本語のテキスト\e[0m  \e[38;5;120m한국어\e[0m  \e[38;5;183m中文\e[0m   combining: é ä ñ\n'
printf ' line drawing  \e(0\e[38;5;215mlqqqqqqqqqqqk\e(B\n'
printf '               \e(0\e[38;5;215mx\e(B  \e[1mACS box\e(0\e[38;5;215m  x\e(B\n'
printf '               \e(0\e[38;5;215mmqqqqqqqqqqqj\e(B\e[0m\n\n'
printf ' link: \e]8;;https://example.com\e\\example.com\e]8;;\e\\ (OSC 8)\n'
