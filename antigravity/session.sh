#!/bin/bash
export PATH="/data/home/.local/bin:$PATH"
printf '\nAntigravity Remote — experimental HAOS host\n'
printf 'Complete Google sign-in below. Use the account with your AI Pro plan.\n'
printf 'After sign-in, open https://antigravity.google.com on your iPhone.\n\n'
flock -s /data/home/.gemini/antigravity-cli/history.lock agy --remote-control
status=$?
printf '\nAntigravity exited (status %s). Restart the add-on to start the CLI again.\n' "$status"
printf 'If no sign-in URL appears, consult DOCS.md before continuing.\n'
exec bash --noprofile --norc
