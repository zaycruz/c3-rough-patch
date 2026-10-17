/**
 * c3-repro-runner: runs the C3 reproduce script from a fresh clone in a Cloudflare Sandbox.
 * Driven by ../scripts/repro-cloudflare.sh (short curl calls; nothing keeps running on the caller's machine).
 *   PUT  /data/<relative path>   upload one sponsor file (gzip body) -> gunzipped into /workspace/data/<path>
 *   POST /start                  {repo, ref, mode} -> clone, place data, run scripts/reproduce.sh in the background
 *   GET  /status                 tail of the job log, and the exit code once it is done
 *   GET  /file?path=<repo path>  read a file from the clone (the run log)
 *   POST /destroy                stop the container and drop its disk (data included)
 * Every route needs "authorization: Bearer <RUNNER_TOKEN>" (a wrangler secret).
 */
import { getSandbox, type Sandbox } from "@cloudflare/sandbox";

export { Sandbox } from "@cloudflare/sandbox";

interface Env {
  Sandbox: DurableObjectNamespace<Sandbox>;
  RUNNER_TOKEN: string;
}

const W = "/workspace";
const sh = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`;

function authorized(req: Request, env: Env): boolean {
  const got = new TextEncoder().encode(req.headers.get("authorization") || "");
  const want = new TextEncoder().encode(`Bearer ${env.RUNNER_TOKEN || ""}`);
  if (!env.RUNNER_TOKEN || got.length !== want.length) return false;
  let diff = 0;
  for (let i = 0; i < got.length; i++) diff |= got[i] ^ want[i];
  return diff === 0;
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    try {
      return await handle(req, env);
    } catch (e) {
      return new Response(`runner error: ${(e as Error).stack || e}`, { status: 500 });
    }
  },
};

async function handle(req: Request, env: Env): Promise<Response> {
  {
    if (!authorized(req, env)) return new Response("unauthorized", { status: 401 });
    const url = new URL(req.url);
    const box = getSandbox(env.Sandbox, "c3-repro", { keepAlive: true, transport: "rpc" });

    if (req.method === "PUT" && url.pathname.startsWith("/data/")) {
      const rel = decodeURIComponent(url.pathname.slice("/data/".length));
      if (!/^[A-Za-z0-9_./-]+$/.test(rel) || rel.includes("..")) return new Response("bad path", { status: 400 });
      const dst = `${W}/data/${rel}`;
      await box.mkdir(dst.slice(0, dst.lastIndexOf("/")), { recursive: true });
      await box.writeFile(`${dst}.gz`, req.body!);
      const r = await box.exec(`gunzip -f ${sh(dst + ".gz")} && sha256sum ${sh(dst)}`);
      return Response.json({ ok: r.success, out: r.stdout.trim(), err: r.stderr.trim() });
    }
    if (req.method === "POST" && url.pathname === "/start") {
      const { repo, ref, mode, where } = (await req.json()) as { repo: string; ref: string; mode?: string; where?: string };
      if (!/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+$/.test(repo) || !/^[0-9a-f]{7,40}$/.test(ref)) return new Response("bad repo/ref", { status: 400 });
      const job = [
        "set -euo pipefail",
        `cd ${W}`,
        "rm -rf repo job.exit",
        "export PATH=\"$HOME/.local/bin:/usr/local/bin:$PATH\"",
        "echo \">>> tools: $(command -v python3 git curl || true)\"",
        "command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq git >/dev/null; }",
        "python3 -m pip install --quiet uv==0.12.15 || python3 -m pip install --quiet --break-system-packages uv==0.12.15",
        "export PATH=\"$(dirname \"$(python3 -c 'import uv; print(uv.find_uv_bin())')\"):$PATH\"",
        "echo \">>> $(uv --version) $(git --version)\"",
        `git clone --quiet ${sh(repo)} repo`,
        "cd repo",
        `git checkout --quiet ${sh(ref)}`,
        "mkdir -p data && cp -r ../data data/Challenge3_Bad_Week_Radar",
        `REPRO_WHERE=${sh(where || "Cloudflare Sandbox")} scripts/reproduce.sh data/Challenge3_Bad_Week_Radar ${sh(mode || "full")}`,
      ].join("\n");
      await box.writeFile(`${W}/job.sh`, job);
      const p = await box.startProcess(`bash -c 'bash ${W}/job.sh > ${W}/job.log 2>&1; echo $? > ${W}/job.exit'`);
      return Response.json({ started: p.id });
    }
    if (req.method === "GET" && url.pathname === "/status") {
      const r = await box.exec(`tail -c 3000 ${W}/job.log 2>/dev/null; echo; echo "EXIT=$(cat ${W}/job.exit 2>/dev/null || echo running)"; nproc; free -g | head -2`);
      return new Response(r.stdout, { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    if (req.method === "GET" && url.pathname === "/file") {
      const path = url.searchParams.get("path") || "";
      if (!/^[A-Za-z0-9_./-]+$/.test(path) || path.includes("..")) return new Response("bad path", { status: 400 });
      const f = await box.readFile(`${W}/repo/${path}`);
      return new Response(f.content, { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    if (req.method === "POST" && url.pathname === "/destroy") {
      await box.destroy();
      return Response.json({ destroyed: true });
    }
    return new Response("not found", { status: 404 });
  }
}
