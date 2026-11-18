import test from "node:test";
import assert from "node:assert/strict";
import { createHmac, webcrypto } from "node:crypto";
import worker from "../src/index.js";

globalThis.crypto ||= webcrypto;
const key = "a-dedicated-very-long-private-secret-for-unit-tests";
const sha = "a".repeat(64);
const base = "https://carlecool-test.example.workers.dev";
function link(choice) {
  const path = "review/15/990/" + sha + "/" + choice + "/" + (Math.floor(Date.now()/1000) + 3600);
  const mac = createHmac("sha256", key).update(path).digest("hex");
  return base + "/" + path + "/" + mac;
}
function harness() {
  let used = null, posted = [];
  const env = {
    APPROVAL_LINK_SECRET: key,
    GITHUB_REPOSITORY: "pcctradinginc-alt/carlecool-reels-automation",
    GITHUB_APPROVAL_TOKEN: "test-private-owner-pat",
    DB: {
      prepare(sql) {
        return {
          bind(...args) {
            return {
              async first() { return used; },
              async run() {
                if (used) return { meta: { changes: 0 } };
                used = { issue: args[0], action: args[3] };
                return { meta: { changes: 1 } };
              },
            };
          },
        };
      },
    },
  };
  const initialFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    if (url.endsWith("/issues/15")) {
      return { ok: true, json: async () => ({
        state: "open", labels: [{name:"carlecool-review"}],
        body: "<!-- CARLECOOL_APPROVAL_JSON\n" +
          JSON.stringify({run_id:990,sha256:sha}) +
          "\nEND_CARLECOOL_APPROVAL_JSON -->",
      }) };
    }
    if (url.endsWith("/issues/15/comments")) {
      posted.push(JSON.parse(options.body).body);
      return { ok: true, json: async () => ({ id: 123 }) };
    }
    throw Error("Unexpected URL");
  };
  return {env, posted, restore(){globalThis.fetch = initialFetch;}};
}
function post(url,origin=base){
  return new Request(url,{ method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded",Origin:origin},
    body:"consent=yes" });
}
test("GET scans never post or reserve approval",async()=>{
  const h=harness();
  try{
    const response=await worker.fetch(new Request(link("tiktok")),h.env);
    assert.equal(response.status,200);
    const html=await response.text();
    assert.match(html,/Jetzt Veröffentlichung freigeben/);
    assert.match(html,/checkbox/);
    assert.deepEqual(h.posted,[]);
    const other=await worker.fetch(new Request(link("instagram")),h.env);
    assert.equal(other.status,200);
  }finally{h.restore();}
});
test("a confirmed POST chooses one platform; competing link is blocked",async()=>{
  const h=harness();
  try{
    const first=await worker.fetch(post(link("tiktok")),h.env);
    assert.equal(first.status,200);
    assert.deepEqual(h.posted,["/publish tiktok"]);
    const second=await worker.fetch(post(link("both")),h.env);
    assert.equal(second.status,409);
    assert.deepEqual(h.posted,["/publish tiktok"]);
  }finally{h.restore();}
});
test("discard emits only /reject; wrong Origin and tampered signature cannot act",async()=>{
  const h=harness();
  try{
    const invalid=await worker.fetch(post(link("discard"),"https://attacker.invalid"),h.env);
    assert.equal(invalid.status,403);
    const url=link("both").replace("/both/","/tiktok/");
    const tampered=await worker.fetch(new Request(url),h.env);
    assert.equal(tampered.status,403);
    assert.deepEqual(h.posted,[]);
    const discarded=await worker.fetch(post(link("discard")),h.env);
    assert.equal(discarded.status,200);
    assert.deepEqual(h.posted,["/reject"]);
  }finally{h.restore();}
});
