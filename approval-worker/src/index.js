// CarleCool free Cloudflare Worker: 48-hour signed, single-use review decisions.
// GET: presentation only. POST: owner authorisation via GitHub token, D1 atomic reservation.
const commands = {instagram:"/publish instagram",tiktok:"/publish tiktok",both:"/publish both",discard:"/reject"};
const names = {instagram:"Nur Instagram",tiktok:"Nur TikTok",both:"TikTok & Instagram",discard:"Nicht veröffentlichen – Entwurf löschen"};
const route = /^\/review\/([1-9]\d*)\/([1-9]\d*)\/([0-9a-f]{64})\/(instagram|tiktok|both|discard)\/(\d{10})\/([0-9a-f]{64})$/;
const headers = {"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store, private","Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY","Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"};
function esc(s){return String(s).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");}
function page(title,body,status=200){return new Response('<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+' – CarleCool</title><style>body{font:16px system-ui,sans-serif;background:#f6f4f1;color:#202b36;padding:25px}main{max-width:480px;margin:7vh auto;padding:34px;border-radius:16px;background:white}p{line-height:1.5}button{width:100%;background:#202b36;color:white;border:0;border-radius:10px;padding:17px;font-size:16px;margin-top:22px}label{display:flex;gap:12px}</style><main><small>CARLECOOL / STUDIO</small><h1>'+esc(title)+'</h1>'+body+'</main></html>',{status,headers});}
async function verify(env,payload,signature){
  if(!env.APPROVAL_LINK_SECRET || env.APPROVAL_LINK_SECRET.length<32)return false;
  const key=await crypto.subtle.importKey("raw",new TextEncoder().encode(env.APPROVAL_LINK_SECRET),{name:"HMAC",hash:"SHA-256"},false,["sign"]);
  const bytes=new Uint8Array(await crypto.subtle.sign("HMAC",key,new TextEncoder().encode(payload)));
  const hex=Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join("");
  if(hex.length!==signature.length)return false;
  let diff=0;for(let i=0;i<hex.length;i++)diff|=hex.charCodeAt(i)^signature.charCodeAt(i);
  return diff===0;
}
// Independent, purpose-bound form token prevents cross-site POSTs when a
// privacy-focused browser omits the Origin header on a normal same-site form.
async function confirmationToken(env, payload) {
  const key=await crypto.subtle.importKey("raw",new TextEncoder().encode(env.APPROVAL_LINK_SECRET),{name:"HMAC",hash:"SHA-256"},false,["sign"]);
  const bytes=new Uint8Array(await crypto.subtle.sign("HMAC",key,new TextEncoder().encode("form-confirm/v1/"+payload)));
  return Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join("");
}
async function github(env,path,init={}){
  if(!/^[a-z0-9_.-]+\/[a-z0-9_.-]+$/i.test(env.GITHUB_REPOSITORY||""))throw Error("config-repository");
  if(typeof env.GITHUB_APPROVAL_TOKEN!=="string"||!env.GITHUB_APPROVAL_TOKEN.trim())throw Error("config-token");
  let r;
  try{
    r=await fetch("https://api.github.com/repos/"+env.GITHUB_REPOSITORY+"/"+path,{...init,redirect:"manual",headers:{"Authorization":"Bearer "+env.GITHUB_APPROVAL_TOKEN,"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"CarleCool-Review",...(init.headers||{})}});
  }catch(_error){throw Error("github-network")}
  if(!r.ok)throw Error("github-http-"+r.status);
  try{return await r.json()}catch(_error){throw Error("github-response-json")}
}
function issuePayload(body){
  const start="<!-- CARLECOOL_APPROVAL_JSON\n",end="\nEND_CARLECOOL_APPROVAL_JSON -->";
  if(!body||body.split(start).length!==2||body.split(end).length!==2)throw Error("Missing review metadata");
  return JSON.parse(body.split(start)[1].split(end)[0]);
}
export default {async fetch(request,env){
  const url=new URL(request.url),parts=url.pathname.match(route);
  if(!parts)return page("Link ungültig","<p>Ungültige Freigabe.</p>",404);
  if(!["GET","POST"].includes(request.method))return page("Nicht erlaubt","<p>Nur GET und POST sind erlaubt.</p>",405);
  if(!env.DB)return page("Nicht eingerichtet","<p>Cloudflare D1 ist nicht verbunden.</p>",503);
  const [,issue,run,sha,choice,expiry,mac]=parts;
  const now=Math.floor(Date.now()/1000);
  if(Number(expiry)<now||Number(expiry)>now+49*3600)return page("Abgelaufen","<p>Dieser Link ist nicht mehr gültig.</p>",410);
  if(!(await verify(env,"review/"+issue+"/"+run+"/"+sha+"/"+choice+"/"+expiry,mac)))return page("Ungültiger Link","<p>Signatur ungültig.</p>",403);
  let phase="d1-read";
  try{
    const existing=await env.DB.prepare("SELECT action FROM used_approvals WHERE issue=?").bind(Number(issue)).first();
    if(existing)return page("Bereits entschieden","<p>Dieser Entwurf wurde bereits bearbeitet.</p>",409);
    phase="github-issue-get";
    let item;
    try {
      item=await github(env,"issues/"+issue);
    } catch (error) {
      if (error?.message==="github-http-410")
        return page("Entwurf gelöscht","<p>Der zugehörige GitHub-Freigabeentwurf wurde bereits gelöscht. Dieser alte E-Mail-Link kann nicht mehr verwendet werden. Es wurde keine neue Veröffentlichung ausgelöst.</p>",410);
      throw error;
    }
    if(item.state!=="open"||item.pull_request||!(item.labels||[]).some(x=>x.name==="carlecool-review"))
      return page("Geschlossen","<p>Dieser Entwurf ist nicht mehr freigegeben.</p>",409);
    phase="issue-payload";
    const approved=issuePayload(item.body);
    if(Number(approved.run_id)!==Number(run)||approved.sha256!==sha)
      return page("Falsches Video","<p>Die Videoidentität stimmt nicht überein.</p>",409);
    const deleting=choice==="discard";
    const payload="review/"+issue+"/"+run+"/"+sha+"/"+choice+"/"+expiry;
    const confirmation=await confirmationToken(env,payload);
    if(request.method==="GET"){
      const detail=deleting?"Der Entwurf wird verworfen und die Freigabe geschlossen. Die E-Mail-Kopie bleibt in deinem Postfach.":
        "Das geprüfte Reel wird nach Bestätigung zur ausgewählten Plattform weitergeleitet.";
      const consent=deleting?"Ich möchte diesen Entwurf verwerfen.":
        "Ich habe das Video geprüft und stimme der öffentlichen Veröffentlichung ausdrücklich zu.";
      return page("Freigabe bestätigen","<p><strong>"+esc(names[choice])+"</strong></p><p>"+esc(detail)+
        "</p><form action='"+esc(url.pathname)+"' method='POST'><input type='hidden' name='confirmation' value='"+confirmation+"'><label><input type='checkbox' name='consent' value='yes' required> "+
        esc(consent)+"</label><button type='submit'>"+esc(deleting?"Entwurf verwerfen":"Jetzt Veröffentlichung freigeben")+
        "</button></form><p><small>Ein Link-Aufruf allein löst nichts aus.</small></p>");
    }
    // Browser / mail webviews may omit, send "null", or rewrite Origin and
    // Sec-Fetch-Site on an otherwise valid first-party form submission.
    // These headers are not authenticated evidence of the submitter. Instead,
    // require the purpose-bound HMAC generated only by the signed GET page,
    // explicit consent, an unexpired signed URL, and single-use D1 reservation.
    // Cross-site forms without the independent secret-derived token cannot act.
    const contentType=(request.headers.get("Content-Type")||"").toLowerCase();
    if(!contentType.startsWith("application/x-www-form-urlencoded"))
      return page("Ungültige Anfrage","<p>Bitte die Bestätigungsseite verwenden.</p>",403);
    const form=await request.formData();
    const supplied=String(form.get("confirmation")||"");
    if(!(await verify(env,"form-confirm/v1/"+payload,supplied)))
      return page("Ungültige Anfrage","<p>Bitte die Bestätigungsseite erneut öffnen.</p>",403);
    if(form.get("consent")!=="yes")return page("Zustimmung fehlt","<p>Bitte zustimmen.</p>",400);
    // Atomic first-writer-wins. No retry after uncertain GitHub response.
    phase="d1-reserve";
    const reserved=await env.DB.prepare("INSERT OR IGNORE INTO used_approvals(issue,run_id,sha256,action,created_at) VALUES(?,?,?,?,?)")
      .bind(Number(issue),Number(run),sha,choice,now).run();
    if(reserved.meta?.changes!==1)return page("Bereits entschieden","<p>Dieser Entwurf wurde bereits bearbeitet.</p>",409);
    phase="github-comment-post";
    await github(env,"issues/"+issue+"/comments",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({body:commands[choice]})});
    return page("Entscheidung übermittelt","<p>"+esc(names[choice])+" wurde an GitHub weitergegeben.</p><p>"+
      (deleting?"Der Freigabeentwurf wird verworfen; die E-Mail-Kopie bleibt erhalten.":
      "Der Veröffentlichungsworkflow verarbeitet deine Entscheidung. Bitte den tatsächlichen Plattformstatus prüfen.")+"</p>");
  }catch(error){
    // Never log signed URLs, hashes, approval tokens, authorization headers, or response bodies.
    // Keep diagnostic output to an allowlisted stage and an optional GitHub HTTP status.
    const diagnostic=String(error?.message||"");
    const code=/^(config-repository|config-token|github-network|github-response-json|github-http-[1-5][0-9]{2})$/.test(diagnostic)
      ? diagnostic : "internal";
    console.error("CarleCool approval diagnostic", {phase, code});
    return page("Status ungeklärt","<p>Die Weitergabe konnte nicht bestätigt werden. Bitte den GitHub-Workflow prüfen und nicht blind erneut freigeben.</p>",502);
  }
}};
