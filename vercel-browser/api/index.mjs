import { Sandbox } from '@vercel/sandbox';

const NAME = 'tiktok-agent-browser';
const PORT = 3000;
const API_KEY = process.env.AGENT_API_KEY || '';

const worker = `
import http from 'node:http';
import { chromium } from 'playwright';
import fs from 'node:fs';
const PROFILE='/vercel/sandbox/tiktok-profile';
let browser=null,page=null,busy=false;
async function ensure(){
 if(page && !page.isClosed()) return page;
 fs.mkdirSync(PROFILE,{recursive:true});
 browser=await chromium.launchPersistentContext(PROFILE,{headless:true,args:['--disable-blink-features=AutomationControlled'],viewport:{width:1440,height:900}});
 page=browser.pages()[0]||await browser.newPage();
 return page;
}
async function body(){return page.locator('body').innerText().catch(()=> '');}
async function go(url){await ensure();await page.goto(url,{waitUntil:'domcontentloaded',timeout:45000});await page.waitForTimeout(1500);}
async function status(){await ensure();const u=page.url(),t=await body();return {ok:true,url:u,title:await page.title(),loggedIn:!u.includes('/login')&&!/Log in/i.test(t.slice(0,2000)),preview:t.slice(0,3000)};}
async function login(d){await go('https://www.tiktok.com/login/phone-or-email/email');await page.getByPlaceholder('Email or username').fill(d.email);await page.getByPlaceholder('Password').fill(d.password);await page.getByRole('button',{name:'Log in',exact:true}).click();await page.waitForTimeout(4000);return status();}
async function verify(d){await ensure();const ins=page.locator('input');for(let i=0;i<await ins.count();i++){const x=ins.nth(i),ph=((await x.getAttribute('placeholder'))||'').toLowerCase();if(ph.includes('code')||ph.includes('verification')||ph.includes('otp')){await x.fill(d.code);break;}}const b=page.getByRole('button',{name:/verify|continue|confirm|submit/i});if(await b.count())await b.first().click();await page.waitForTimeout(3000);return status();}
async function me(){await go('https://www.tiktok.com/profile');return {ok:true,url:page.url(),text:(await body()).slice(0,8000)};}
async function messages(){await go('https://www.tiktok.com/messages');return {ok:true,url:page.url(),text:(await body()).slice(0,12000)};}
async function findUser(username){const ins=page.locator('input');for(let i=0;i<await ins.count();i++){const x=ins.nth(i),ph=((await x.getAttribute('placeholder'))||'').toLowerCase();if(ph.includes('search')){await x.fill(username);await page.waitForTimeout(1800);const h=page.getByText(username,{exact:false});if(await h.count()){await h.first().click();return true;}}}const links=page.getByRole('link',{name:new RegExp(username.replace('@',''),'i')});if(await links.count()){await links.first().click();return true;}return false;}
async function send(d){await messages();if(!(await findUser(d.username)))throw Error('user_not_found');let ta=page.locator('textarea');if(!await ta.count())ta=page.getByRole('textbox');await ta.last().fill(d.message);const b=page.getByRole('button',{name:/send/i});if(await b.count())await b.last().click();else await ta.last().press('Enter');await page.waitForTimeout(800);return {ok:true,text:(await body()).slice(-5000)};}
async function react(d){await messages();if(!(await findUser(d.username)))throw Error('user_not_found');const m=page.getByText(d.message,{exact:false});if(!await m.count())throw Error('message_not_found');await m.last().click({button:'right'}).catch(()=>{});await page.waitForTimeout(500);const r=page.getByText(d.emoji||'❤️',{exact:true});if(await r.count())await r.last().click();else throw Error('reaction_control_not_found');return {ok:true,text:(await body()).slice(-4000)};}
async function edit(d){await go('https://www.tiktok.com/profile');let b=page.getByRole('button',{name:/edit profile/i});if(await b.count())await b.first().click();else{const l=page.getByText('Edit profile',{exact:true});if(await l.count())await l.first().click();}await page.waitForTimeout(800);if(d.displayName!==undefined){let x=page.getByLabel(/name|display name/i);if(await x.count())await x.first().fill(d.displayName);else{const ins=page.locator('input');if(await ins.count())await ins.first().fill(d.displayName);}}if(d.bio!==undefined){let x=page.getByLabel(/bio/i);if(await x.count())await x.first().fill(d.bio);else{const ta=page.locator('textarea');if(await ta.count())await ta.first().fill(d.bio);}}const save=page.getByRole('button',{name:/save/i});if(await save.count())await save.first().click();await page.waitForTimeout(1000);return me();}
async function handle(action,d){const forbidden=['delete','delete_message','delete_chat','block','report','deactivate','logout','account_delete'];if(forbidden.includes(action))throw Error('disabled_action');if(action==='status')return status();if(action==='login')return login(d);if(action==='verify')return verify(d);if(action==='me')return me();if(action==='messages')return messages();if(action==='search_messages'){await messages();const q=String(d.q||'').toLowerCase();return {ok:true,matches:(await body()).split('\\n').filter(x=>x.toLowerCase().includes(q)).slice(0,100)};}if(action==='send_dm'||action==='reply_dm')return send(d);if(action==='react_message')return react(d);if(action==='edit_profile')return edit(d);throw Error('unsupported_action');}
function out(res,x,c=200){res.writeHead(c,{'content-type':'application/json'});res.end(JSON.stringify(x));}
http.createServer(async(req,res)=>{try{let s='';for await(const c of req)s+=c;const d=s?JSON.parse(s):{};const action=d.action||'status';if(busy&&action!=='status')return out(res,{ok:false,error:'busy'},409);busy=action!=='status';try{out(res,await handle(action,d));}finally{busy=false;}}catch(e){busy=false;out(res,{ok:false,error:String(e?.message||e)},400);}}).listen(3000,'127.0.0.1');
`;

async function sandbox(){
 return Sandbox.getOrCreate({
  name:NAME,ports:[PORT],timeout:5*60*1000,persistent:true,snapshotExpiration:0,resources:{vcpus:1},
  onCreate:async s=>{
   await s.writeFiles([{path:'/vercel/sandbox/worker.mjs',content:Buffer.from(worker)}]);
   await s.runCommand({cmd:'npm',args:['init','-y'],cwd:'/vercel/sandbox'});
   const install=await s.runCommand({cmd:'npm',args:['install','playwright'],cwd:'/vercel/sandbox',timeoutMs:240000});
   if(install.exitCode!==0)throw Error('playwright_install_failed');
   const browser=await s.runCommand({cmd:'npx',args:['playwright','install','chromium'],cwd:'/vercel/sandbox',timeoutMs:240000});
   if(browser.exitCode!==0)throw Error('chromium_install_failed');
   await s.runCommand({cmd:'node',args:['worker.mjs'],cwd:'/vercel/sandbox',detached:true});
  },
  onResume:async s=>{await s.runCommand({cmd:'node',args:['worker.mjs'],cwd:'/vercel/sandbox',detached:true});}
 });
}
async function forward(action,body){const s=await sandbox();const r=await fetch(s.domain(PORT),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action,...body})});return r.json();}
function authorized(req){return !API_KEY||req.headers.get('x-api-key')===API_KEY;}
export default async function handler(req,res){
 try{
  if(req.method==='GET'&&req.url.startsWith('/api/health'))return res.status(200).json({ok:true,service:'tiktok-agent-access',browser:'vercel-persistent-sandbox',destructive_actions:false});
  if(!authorized(req))return res.status(401).json({error:'unauthorized'});
  if(req.method==='GET'&&req.url.startsWith('/api/capabilities'))return res.status(200).json({transport:'HTTP',actions:['status','login','verify','me','messages','search_messages','send_dm','reply_dm','react_message','edit_profile'],disabled_actions:['delete','delete_message','delete_chat','block','report','deactivate','logout','account_delete']});
  if(req.method==='GET'&&req.url.startsWith('/api/status'))return res.status(200).json(await forward('status',{}));
  if(req.method==='POST'&&req.url.startsWith('/api/action')){const b=req.body||{};if(!b.action)return res.status(400).json({error:'action_required'});const out=await forward(b.action,b);return res.status(out.ok===false?400:200).json(out);}
  return res.status(404).json({error:'not_found'});
 }catch(e){return res.status(500).json({error:String(e?.message||e)});}
}
