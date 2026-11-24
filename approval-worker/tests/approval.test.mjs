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
function harness({deleted=false}={}) {
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
      if (deleted) return {ok:false,status:410};
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
function post(url,origin=base,{confirmation=true,fetchSite}={}){
  const parsed=new URL(url);
  const payload=parsed.pathname.slice(1).split("/").slice(0,-1).join("/");
  const mac=createHmac("sha256",key).update("form-confirm/v1/"+payload).digest("hex");
  const headers={"Content-Type":"application/x-www-form-urlencoded"};
  if(origin!==null)headers.Origin=origin;
  if(fetchSite)headers["Sec-Fetch-Site"]=fetchSite;
  return new Request(url,{method:"POST",headers,
    body:"consent=yes"+(confirmation?"&confirmation="+mac:"")});
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
test("discard emits only /reject; missing form signature and tampered URL cannot act",async()=>{
  const h=harness();
  try{
    const invalid=await worker.fetch(post(link("discard"),"https://attacker.invalid",{confirmation:false}),h.env);
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

test("deleted GitHub review (410) shows final state, never posts or reserves",async()=>{
  const h=harness({deleted:true});
  try {
    const response=await worker.fetch(new Request(link("tiktok")),h.env);
    assert.equal(response.status,410);
    assert.match(await response.text(),/Entwurf gelöscht/);
    assert.deepEqual(h.posted,[]);
    const postResponse=await worker.fetch(post(link("tiktok")),h.env);
    assert.equal(postResponse.status,410);
    assert.deepEqual(h.posted,[]);
  } finally {h.restore();}
});

test("privacy-mode browser omitting Origin can confirm only a signed GET-form token",async()=>{
  const h=harness();
  try{
    const url=link("tiktok");
    const get=await worker.fetch(new Request(url),h.env);
    assert.equal(get.status,200);
    const html=await get.text();
    const match=html.match(/name='confirmation' value='([0-9a-f]{64})'/);
    assert.ok(match,"GET form includes independently signed confirmation token");
    const noToken=await worker.fetch(post(url,null,{confirmation:false}),h.env);
    assert.equal(noToken.status,403);
    assert.deepEqual(h.posted,[]);
    const crossSite=await worker.fetch(post(url,null,{confirmation:false,fetchSite:"cross-site"}),h.env);
    assert.equal(crossSite.status,403);
    assert.deepEqual(h.posted,[]);
    // Some in-app browsers send Origin: null or Sec-Fetch-Site: cross-site.
    // A valid secret-derived form HMAC + consent must still succeed.
    const valid=await worker.fetch(post(url,"null",{fetchSite:"cross-site"}),h.env);
    assert.equal(valid.status,200);
    assert.deepEqual(h.posted,["/publish tiktok"]);
  }finally{h.restore();}
});

test("request without token cannot confirm even with a valid signed review URL",async()=>{
  const h=harness();
  try{
    const url=link("instagram");
    const req=post(url,base,{confirmation:false});
    assert.equal((await worker.fetch(req,h.env)).status,403);
    assert.deepEqual(h.posted,[]);
  }finally{h.restore();}
});
test("tokenized cross-origin form succeeds only because of explicit signed confirmation",async()=>{
  const h=harness();
  try{
    const url=link("tiktok");
    // Headers are only hints, not credentials. Cross-site with no form MAC fails.
    assert.equal((await worker.fetch(post(url,"https://attacker.invalid",{confirmation:false}),h.env)).status,403);
    assert.deepEqual(h.posted,[]);
    // A legitimately generated form can be submitted from an in-app browser
    // whose visible origin differs from the Worker URL.
    assert.equal((await worker.fetch(post(url,"https://privacy-browser.invalid",{confirmation:true}),h.env)).status,200);
    assert.deepEqual(h.posted,["/publish tiktok"]);
  }finally{h.restore();}
});
