// Opt-in live acceptance: real synthesized speech -> WS full duplex on the running API.
// Covers: voice turn (VAD -> whisper -> Ollama -> say -> playback acks), barge-in,
// backchannel ignore, delegated work lifecycle QUEUED->COMPLETED->DELIVERING->DELIVERED.
// Usage: node scripts/acceptance_duplex.mjs   (requires macOS say + configured whisper + Ollama)
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.env.FAIRY_API_BASE || "http://127.0.0.1:8010";
const TOKEN = process.env.FAIRY_API_TOKEN
  || readFileSync(join(homedir(), "Library/Application Support/Fairy/api-token"), "utf8").trim();
const FRAME = 640; // 20ms PCM16LE mono @16k
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const t0 = Date.now();
const step = (name, extra = {}) =>
  console.log(JSON.stringify({ step: name, seconds: +((Date.now() - t0) / 1000).toFixed(2), ...extra }, null, 0));

async function api(path, method = "GET", body) {
  const r = await fetch(BASE + "/v2/" + path, {
    method,
    headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${await r.text()}`);
  return r.json();
}

function synth(text, dir) {
  const wav = join(dir, `say-${Math.random().toString(36).slice(2)}.wav`);
  const p = spawnSync("say", ["-v", "Tingting", "-o", wav, "--file-format=WAVE", "--data-format=LEI16@16000", text], { encoding: "utf8" });
  if (p.status !== 0) throw new Error(`say failed: ${p.stderr}`);
  const buf = readFileSync(wav);
  let off = 12;
  while (off + 8 <= buf.length) {
    const id = buf.toString("ascii", off, off + 4);
    const size = buf.readUInt32LE(off + 4);
    if (id === "data") return buf.subarray(off + 8, off + 8 + size);
    off += 8 + size + (size % 2);
  }
  throw new Error("no data chunk in wav");
}

const silence = (ms) => Buffer.alloc((ms / 20) * FRAME);
function tone(ms, amp = 3000, freq = 220) {
  const n = (ms / 20) * 320;
  const b = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) b.writeInt16LE(Math.round(amp * Math.sin((2 * Math.PI * freq * i) / 16000)), i * 2);
  return b;
}

class DuplexClient {
  constructor() {
    this.events = [];
    this.waiters = [];
    this.items = new Map();
    this.noAck = new Set();
    this.stopped = [];
  }
  async connect() {
    this.ws = new WebSocket(BASE.replace(/^http/, "ws") + "/v2/duplex/ws");
    this.ws.addEventListener("message", (e) => {
      if (typeof e.data !== "string") return;
      const m = JSON.parse(e.data);
      this.events.push(m);
      if (m.type === "speech") this.onSpeech(m);
      if (m.type === "stop_playback") this.stopped.push(m.item_id);
      this.waiters = this.waiters.filter((w) => {
        for (let i = w.after; i < this.events.length; i++) {
          if (w.pred(this.events[i])) { clearTimeout(w.timer); w.resolve({ msg: this.events[i], index: i }); return false; }
        }
        return true;
      });
    });
    await new Promise((res, rej) => {
      this.ws.addEventListener("open", res, { once: true });
      this.ws.addEventListener("error", () => rej(new Error("ws connect failed")), { once: true });
    });
    this.ws.send(JSON.stringify({ type: "auth", token: TOKEN }));
    const { msg } = await this.wait((m) => m.type === "ready", 8000, 0, "ready");
    return msg;
  }
  mark() { return this.events.length; }
  wait(pred, timeout, after, label) {
    for (let i = after; i < this.events.length; i++) if (pred(this.events[i])) return Promise.resolve({ msg: this.events[i], index: i });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.waiters = this.waiters.filter((w) => w.timer !== timer);
        reject(new Error(`timeout waiting ${label}; last events: ${JSON.stringify(this.events.slice(-6))}`));
      }, timeout);
      this.waiters.push({ pred, after, resolve, reject, timer });
    });
  }
  onSpeech(m) {
    let it = this.items.get(m.item_id);
    if (!it) { it = { kind: m.kind, chunks: [], acked: 0 }; this.items.set(m.item_id, it); }
    it.chunks.push(m);
    if (!this.noAck.has(m.item_id)) {
      this.ws.send(JSON.stringify({ type: "playback_ack", item_id: m.item_id, seq: m.seq, played: true }));
      it.acked++;
    }
  }
  sendJson(o) { this.ws.send(JSON.stringify(o)); }
  async sendPcm(pcm) {
    for (let off = 0; off < pcm.length; off += FRAME) {
      this.ws.send(pcm.subarray(off, Math.min(off + FRAME, pcm.length)));
      await sleep(20);
    }
  }
  close() { try { this.ws.close(); } catch {} }
}

const report = { passed: false, steps: {} };
const dir = mkdtempSync(join(tmpdir(), "fairy-duplex-"));
const c = new DuplexClient();
const guard = setTimeout(() => { console.error("overall timeout"); c.close(); process.exit(1); }, 420000);

try {
  const status = await api("duplex/status");
  if (!status.full_duplex || !status.voice.local_asr || !status.voice.local_tts) throw new Error(`duplex not ready: ${JSON.stringify(status)}`);
  step("status", { voice: status.voice });

  const ready = await c.connect();
  if (!ready.capabilities.barge_in || !ready.capabilities.delegation) throw new Error("missing capabilities");
  step("ready", { session: ready.session_id });
  let mark = c.mark();
  c.sendJson({ type: "ping" });
  await c.wait((m) => m.type === "pong", 5000, mark, "pong");

  // 1) Real voice turn: synthesized speech -> VAD -> whisper -> model -> TTS -> acks.
  const phraseA = synth("你好，我喜欢喝温水", dir);
  mark = c.mark();
  await c.sendPcm(phraseA);
  await c.sendPcm(silence(800));
  await c.wait((m) => m.type === "vad" && m.event === "speech_start", 15000, mark, "speech_start");
  await c.wait((m) => m.type === "vad" && m.event === "speech_end", 15000, mark, "speech_end");
  const trA = await c.wait((m) => m.type === "transcript", 60000, mark, "transcript A");
  if (!/温水|溫水/.test(trA.msg.text)) throw new Error(`transcript missing 温水: ${trA.msg.text}`);
  const replyA = await c.wait((m) => m.type === "reply", 120000, mark, "reply A");
  if (!replyA.msg.text) throw new Error("empty reply A");
  const idleA = await c.wait((m) => m.type === "state" && m.state === "idle", 120000, replyA.index, "idle after A");
  const itemA = c.items.get(replyA.msg.turn_id);
  if (!itemA || !itemA.chunks.length) throw new Error("no speech chunks for A");
  if (!itemA.chunks.some((s) => s.audio_base64 && s.sample_rate === 22050)) throw new Error("no local TTS audio for A");
  if (itemA.acked !== itemA.chunks.length) throw new Error("A chunks not fully acked");
  report.steps.voice_turn = { transcript: trA.msg.text, route: replyA.msg.route, chunks: itemA.chunks.length };
  step("voice_turn", report.steps.voice_turn);

  // 2) Barge-in: long reply playing (unacked) -> >=500ms voiced audio -> stop_playback -> new turn.
  mark = c.mark();
  c.sendJson({ type: "text", text: "请详细介绍一下杭州西湖的四季景色，大约三百字" });
  const replyL = await c.wait((m) => m.type === "reply", 120000, mark, "long reply");
  c.noAck.add(replyL.msg.turn_id);
  await c.wait((m) => m.type === "speech" && m.item_id === replyL.msg.turn_id, 60000, mark, "long speech start");
  const phraseB = synth("等一下，我想打断你，先别说了", dir);
  const bargeMark = c.mark();
  await c.sendPcm(phraseB);
  await c.sendPcm(silence(800));
  const stop = await c.wait((m) => m.type === "stop_playback" && m.item_id === replyL.msg.turn_id, 20000, bargeMark, "stop_playback");
  const trB = await c.wait((m) => m.type === "transcript", 60000, stop.index, "transcript B");
  if (!trB.msg.text) throw new Error("empty transcript B");
  const replyB = await c.wait((m) => m.type === "reply", 120000, trB.index, "reply B");
  await c.wait((m) => m.type === "state" && m.state === "idle", 120000, replyB.index, "idle after B");
  report.steps.barge_in = { stopped_item: stop.msg.item_id, interrupt_transcript: trB.msg.text };
  step("barge_in", report.steps.barge_in);

  // 3) Backchannel: short voiced burst during playback is ignored, playback continues.
  mark = c.mark();
  c.sendJson({ type: "text", text: "请详细介绍中国的二十四节气，每个季节各举两个例子，大约三百字" });
  const replyC = await c.wait((m) => m.type === "reply", 120000, mark, "reply C");
  await c.wait((m) => m.type === "speech" && m.item_id === replyC.msg.turn_id, 60000, mark, "speech C start");
  const bcMark = c.mark();
  await c.sendPcm(tone(200));
  await c.sendPcm(silence(700));
  const bc = await c.wait((m) => m.type === "backchannel", 20000, bcMark, "backchannel");
  await c.wait((m) => m.type === "state" && m.state === "idle", 120000, replyC.index, "idle after C");
  if (c.stopped.includes(replyC.msg.turn_id)) throw new Error("backchannel wrongly stopped playback");
  const itemC = c.items.get(replyC.msg.turn_id);
  if (!itemC || itemC.acked !== itemC.chunks.length || !itemC.chunks.length) throw new Error("C playback incomplete");
  report.steps.backchannel = { duration_ms: bc.msg.duration_ms, chunks_played: itemC.chunks.length };
  step("backchannel", report.steps.backchannel);

  // 4) Delegated work: COMPLETED is not DELIVERED; delivery requires idle session + full acks.
  mark = c.mark();
  c.sendJson({ type: "delegate", text: "用一句话告诉我，根据我的偏好今天适合喝什么水" });
  const workMsg = await c.wait((m) => m.type === "work", 10000, mark, "work created");
  const workId = workMsg.msg.work.id;
  const seen = new Set([workMsg.msg.work.state]);
  let delivered = null;
  const deadline = Date.now() + 180000;
  let workSpeech = null;
  while (Date.now() < deadline) {
    const works = await api("duplex/works");
    const w = works.find((x) => x.id === workId);
    if (!w) throw new Error("work vanished");
    seen.add(w.state);
    if (w.state === "FAILED") throw new Error(`work failed: ${w.error}`);
    if (w.state === "DELIVERED") { delivered = w; break; }
    if (!workSpeech) {
      const it = c.items.get(workId);
      if (it && it.chunks.length) workSpeech = it;
    }
    await sleep(250);
  }
  if (!delivered) throw new Error(`work not DELIVERED in time; states seen: ${[...seen]}`);
  // DELIVERED implies every chunk was acked; do a final lookup in case the
  // state jumped to DELIVERED between polls before the item check ran.
  if (!workSpeech) {
    const it = c.items.get(workId);
    if (it && it.chunks.length) workSpeech = it;
  }
  if (!seen.has("COMPLETED") && !seen.has("DELIVERING")) throw new Error("lifecycle states not observed");
  if (!workSpeech || !workSpeech.chunks.length || workSpeech.kind !== "work") throw new Error("work result not spoken");
  if (workSpeech.acked !== workSpeech.chunks.length) throw new Error("work chunks not fully acked");
  if (!(delivered.result || {}).reply) throw new Error("work result empty");
  report.steps.delegation = { work_id: workId, states: [...seen], chunks: workSpeech.chunks.length, reply: delivered.result.reply };
  step("delegation", report.steps.delegation);

  // 5) Cancel path (best effort: work may finish before cancel lands).
  mark = c.mark();
  c.sendJson({ type: "delegate", text: "写一首关于秋天的三百行长诗" });
  const w2 = await c.wait((m) => m.type === "work", 10000, mark, "work 2");
  const cancelRes = await fetch(`${BASE}/v2/duplex/works/${w2.msg.work.id}/cancel`, { method: "POST", headers: { Authorization: `Bearer ${TOKEN}` } });
  if (cancelRes.status === 200) {
    const body = await cancelRes.json();
    if (body.state !== "CANCELLED") throw new Error(`cancel returned ${body.state}`);
    report.steps.cancel = { state: body.state };
  } else if (cancelRes.status === 409) {
    report.steps.cancel = { state: "already_terminal" };
  } else throw new Error(`cancel -> ${cancelRes.status}`);
  step("cancel", report.steps.cancel);

  report.passed = true;
  report.total_seconds = +((Date.now() - t0) / 1000).toFixed(2);
  console.log("Live duplex acceptance passed");
} catch (err) {
  report.error = String(err && err.message || err);
  console.error("Live duplex acceptance FAILED:", report.error);
  process.exitCode = 1;
} finally {
  clearTimeout(guard);
  c.close();
  rmSync(dir, { recursive: true, force: true });
  const out = process.env.FAIRY_LIVE_REPORT || "docs/implementation/duplex-acceptance.json";
  writeFileSync(out, JSON.stringify(report, null, 2) + "\n");
  step("report_written", { path: out });
}
