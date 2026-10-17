#!/usr/bin/env bash
# Fresh-clone reproduce proof on Cloudflare (Sandbox container), driven by short curl calls.
#   scripts/repro-cloudflare.sh <DATA_DIR> <git sha pushed to origin> [full|quick]
# 1. deploys runner/ as the Worker c3-repro-runner with a one-off random RUNNER_TOKEN secret
# 2. uploads the three sponsor files (gzip, over HTTPS, token-gated) into the container's disk
# 3. the container clones github.com/zaycruz/c3-rough-patch at <sha> into an empty dir and runs scripts/reproduce.sh
# 4. polls until done, saves the run log to runs/, then destroys the container and deletes the Worker
set -euo pipefail
cd "$(dirname "$0")/.."
DATA="$1"; REF="$2"; MODE="${3:-full}"
REPO=https://github.com/zaycruz/c3-rough-patch
TOK="$(openssl rand -hex 24)"
cd runner
npx wrangler deploy 2>&1 | grep -E "https://|Uploaded|error" || true
URL="${RUNNER_URL:-https://c3-repro-runner.zay-259.workers.dev}"   # your workers.dev subdomain
printf '%s' "$TOK" | npx wrangler secret put RUNNER_TOKEN >/dev/null
cd ..
H=(-sS --fail-with-body --max-time 300 -H "authorization: Bearer $TOK")
echo "runner: $URL"
cleanup() {  # always: drop the container (and the sponsor data on its disk), then delete the Worker
  curl "${H[@]}" -X POST "$URL/destroy" || true; echo
  (cd runner && npx wrangler delete --name c3-repro-runner --force 2>&1 | tail -1) || true
  # deleting the Worker leaves its container application behind (a redeploy then fails); delete only this runner's app
  (cd runner && for id in $(npx wrangler containers list 2>/dev/null | awk -F'│' '$3 ~ /^ *c3-repro-runner-sandbox *$/ {gsub(/ /,"",$2); print $2}'); do
    npx wrangler containers delete "$id" 2>&1 | tail -1; done) || true
}
trap cleanup EXIT
for i in $(seq 1 40); do curl "${H[@]}" -o /dev/null "$URL/status" 2>/dev/null && break; sleep 15; done   # first container start (up to 10 min)
for f in synthetic_data/synthetic_daily.csv synthetic_data/synthetic_patients.csv fatigue_study_daily.csv; do
  want="$(shasum -a 256 "$DATA/$f" | cut -d' ' -f1)"
  r="$(gzip -c "$DATA/$f" | curl "${H[@]}" -X PUT --data-binary @- "$URL/data/$f")"
  echo "$r" | grep -q "$want" || { echo "upload of $f did not verify: $r"; exit 3; }
  echo "uploaded $f ($want)"
done
curl "${H[@]}" -X POST -H 'content-type: application/json' \
  -d "{\"repo\":\"$REPO\",\"ref\":\"$REF\",\"mode\":\"$MODE\",\"where\":\"Cloudflare Sandbox (container), instance standard-4, image docker.io/cloudflare/sandbox:0.12.10-python\"}" "$URL/start"; echo
while :; do
  s="$(curl "${H[@]}" "$URL/status" 2>/dev/null || true)"
  echo "$s" | grep -E '^>>>|EXIT=' | tail -2
  echo "$s" | grep -qE '^EXIT=[0-9]+$' && break   # only a real exit code ends the wait; a failed poll just retries
  sleep 60
done
mkdir -p runs
echo "$s" > runs/repro-cloudflare-last-status.txt
LOGF="$(echo "$s" | grep -o 'runs/reproduce-[0-9TZ-]*\.md' | tail -1 || true)"
if [ -n "$LOGF" ]; then curl "${H[@]}" "$URL/file?path=$LOGF" > "$LOGF" && echo "saved $LOGF"; else echo "$s" | tail -25; fi
exit "$(echo "$s" | grep -oE '^EXIT=[0-9]+$' | tail -1 | cut -d= -f2)"
