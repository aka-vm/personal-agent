#!/bin/bash
# Re-establish every personal app's Tailscale HTTPS serve.
# Single source of truth for app -> port. Run on a fresh Pi / rebuild.
# (tailscale serve --bg config persists across reboots, so you normally
#  only need this once per machine. Needs sudo — tailscale serve wants root.)
#
# To add an app: clone its repo to /home/vineet/<dir>, add a line below,
# re-run this, then add it to the dashboard APPS array.
set -e

# port  ->  directory to serve (each its own GitHub repo, cloned locally)
serve() { echo "→ :$1  $2"; sudo tailscale serve --bg --https="$1" "$2"; }

serve 8443 /home/vineet/stfu              # STFU            (external repo)
serve 8444 /home/vineet/encoder-decoder   # Encoder·Decoder (aka-vm/encoder-decoder)

echo; echo "current serve config:"; tailscale serve status
