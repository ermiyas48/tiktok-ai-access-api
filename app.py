import io, json, os, re, time, secrets, hmac, hashlib
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

BASE_URL=os.getenv("BASE_URL","").rstrip("/")
CLIENT_KEY=os.getenv("TIKTOK_CLIENT_KEY","")
CLIENT_SECRET=os.getenv("TIKTOK_CLIENT_SECRET","")
REDIRECT_URI=os.getenv("TIKTOK_REDIRECT_URI") or (f"{BASE_URL}/auth/tiktok/callback" if BASE_URL else "")
DATABASE_URL=os.getenv("DATABASE_URL","sqlite:////data/tiktok.db")
API_KEY=os.getenv("API_KEY","")
SCOPES=re.split(r"[ ,]+",os.getenv("TIKTOK_SCOPES","user.info.basic user.info.profile user.info.stats video.list video.publish video.upload portability.all.single portability.all.ongoing portability.postsandprofile.single portability.postsandprofile.ongoing portability.activity.single portability.activity.ongoing portability.directmessages.single portability.directmessages.ongoing" ).strip())
SCOPES=[x for x in SCOPES if x]
TIKTOK="https://open.tiktokapis.com"
AUTH="https://www.tiktok.com/v2/auth/authorize/"
TOKEN=f"{TIKTOK}/v2/oauth/token/"
connect_args={"check_same_thread":False} if DATABASE_URL.startswith("sqlite") else {}
engine=create_engine(DATABASE_URL,connect_args=connect_args,pool_pre_ping=True)
Session=sessionmaker(bind=engine,expire_on_commit=False)

class Base(DeclarativeBase): pass
class Connection(Base):
    __tablename__="connections"
    id:Mapped[int]=mapped_column(primary_key=True)
    open_id:Mapped[str]=mapped_column(unique=True)
    access_token:Mapped[str]
    refresh_token:Mapped[str]
    access_expires_at:Mapped[int]
    refresh_expires_at:Mapped[int]=mapped_column(default=0)
    scopes:Mapped[str]=mapped_column(default="")
    updated_at:Mapped[int]
class DataRequest(Base):
    __tablename__="data_requests"
    id:Mapped[int]=mapped_column(primary_key=True)
    request_id:Mapped[int]=mapped_column(unique=True)
    category:Mapped[str]
    data_format:Mapped[str]
    status:Mapped[str]=mapped_column(default="REQUESTED")
    created_at:Mapped[int]
Base.metadata.create_all(engine)

app=FastAPI(title="TikTok AI Access API",version="1.0.0",docs_url="/api/docs",redoc_url="/api/redoc",openapi_url="/openapi.json")

class PostRequest(BaseModel):
    video_url:str
    title:str=""
    privacy_level:str="SELF_ONLY"
    disable_duet:bool=False
    disable_comment:bool=False
    disable_stitch:bool=False
    brand_organic_toggle:bool=False
    brand_content_toggle:bool=False
    is_aigc:bool=False
class DataRequestIn(BaseModel):
    categories:list[str]=Field(default_factory=lambda:["all_data"])
    data_format:str="json"
class RequestIdIn(BaseModel):
    request_id:int

def now(): return int(time.time())
def auth_guard(request:Request):
    if API_KEY and request.headers.get("X-API-Key")!=API_KEY: raise HTTPException(401,detail={"error":"invalid_api_key"})
def safe_json(r):
    try:return r.json()
    except:return {"http_status":r.status_code,"text":r.text[:500]}
def refresh(c):
    r=httpx.post(TOKEN,data={"client_key":CLIENT_KEY,"client_secret":CLIENT_SECRET,"grant_type":"refresh_token","refresh_token":c.refresh_token},timeout=30)
    if r.status_code>=400: raise HTTPException(401,detail={"error":"token_refresh_failed","tiktok":safe_json(r)})
    d=r.json()
    with Session() as db:
        row=db.get(Connection,c.id); row.access_token=d["access_token"]; row.refresh_token=d.get("refresh_token",row.refresh_token); row.access_expires_at=now()+int(d.get("expires_in",86400)); row.refresh_expires_at=now()+int(d.get("refresh_expires_in",0)); row.scopes=d.get("scope",row.scopes); row.updated_at=now(); db.commit(); db.refresh(row); return row
def conn():
    with Session() as db:c=db.query(Connection).order_by(Connection.id.desc()).first()
    if not c: raise HTTPException(401,detail={"error":"not_connected","message":"Connect TikTok at /auth/tiktok"})
    return refresh(c) if c.access_expires_at<=now()+120 else c
def scope(c,s):
    if s not in set((c.scopes or "").split()): raise HTTPException(403,detail={"error":"scope_not_authorized","required_scope":s,"authorized_scopes":(c.scopes or "").split()})
def tiktok(c,method,path,**kw):
    h={"Authorization":f"Bearer {c.access_token}"}; h.update(kw.pop("headers",{}) or {})
    url=path if path.startswith("http") else TIKTOK+path
    r=httpx.request(method,url,headers=h,timeout=90,**kw)
    if r.status_code==401:
        c=refresh(c); h["Authorization"]=f"Bearer {c.access_token}"; r=httpx.request(method,url,headers=h,timeout=90,**kw)
    if r.status_code>=400: raise HTTPException(r.status_code,detail={"error":"tiktok_api_error","tiktok":safe_json(r)})
    return r

def discovery():
    return {"service":"TikTok AI Access API","version":"1.0.0","base_url":BASE_URL or None,"oauth":"/auth/tiktok","docs":"/api/docs","openapi":"/openapi.json","capabilities":"/api/capabilities","endpoints":["/api/me","/api/profile","/api/stats","/api/videos","/api/videos/{id}","/api/creator","/api/post/status/{publish_id}","/api/video/upload","/api/video/publish","/api/data/request","/api/data","/api/data/status","/api/data/cancel","/api/data/download","/api/export","/api/export/{request_id}"],"boundary":"Likes, reposts, followers/following, comments and DMs are exposed through portability exports only when included by TikTok; no fake live endpoint is created."}

@app.get("/api")
def api_root(request:Request):auth_guard(request);return discovery()
@app.get("/api/health")
def health():return {"ok":True,"service":"tiktok-ai-access-api","time":datetime.now(timezone.utc).isoformat()}
@app.get("/api/capabilities")
def capabilities(request:Request):
    auth_guard(request); c=conn(); scopes=set((c.scopes or "").split()); items={}
    for label,s in [("Profile","user.info.basic"),("Profile details","user.info.profile"),("Statistics","user.info.stats"),("Videos","video.list"),("Publishing","video.publish"),("Draft upload","video.upload"),("Data export","portability.all.single"),("Data export ongoing","portability.all.ongoing"),("Posts/profile export","portability.postsandprofile.single"),("Activity export","portability.activity.single"),("Messages export","portability.directmessages.single")]:items[label]={"authorized":s in scopes,"scope":s}
    return {"connected":True,"open_id":c.open_id,"authorized_scopes":sorted(scopes),"capabilities":items}

@app.get("/auth/tiktok")
def auth_tiktok():
    if not CLIENT_KEY or not CLIENT_SECRET or not REDIRECT_URI: raise HTTPException(500,detail={"error":"missing_oauth_config"})
    p=f"{now()}:{secrets.token_urlsafe(16)}"; sig=hmac.new(CLIENT_SECRET.encode(),p.encode(),hashlib.sha256).hexdigest(); state=f"{p}:{sig}"
    q={"client_key":CLIENT_KEY,"response_type":"code","scope":" ".join(SCOPES),"redirect_uri":REDIRECT_URI,"state":state}
    return RedirectResponse(AUTH+"?"+urlencode(q))
@app.get("/auth/tiktok/callback")
def auth_callback(code:Optional[str]=None,state:Optional[str]=None,error:Optional[str]=None,error_description:Optional[str]=None):
    if error:return JSONResponse({"connected":False,"error":error,"error_description":error_description},status_code=400)
    if not code or not state:raise HTTPException(400,detail={"error":"missing_code_or_state"})
    parts=state.rsplit(":",2); payload=":".join(parts[:2]) if len(parts)==3 else ""; sig=parts[2] if len(parts)==3 else ""
    if not payload or not hmac.compare_digest(hmac.new(CLIENT_SECRET.encode(),payload.encode(),hashlib.sha256).hexdigest(),sig):raise HTTPException(400,detail={"error":"invalid_state"})
    if now()-int(parts[0])>600:raise HTTPException(400,detail={"error":"expired_state"})
    r=httpx.post(TOKEN,data={"client_key":CLIENT_KEY,"client_secret":CLIENT_SECRET,"code":code,"grant_type":"authorization_code","redirect_uri":REDIRECT_URI},timeout=30)
    if r.status_code>=400:raise HTTPException(400,detail={"error":"oauth_exchange_failed","tiktok":safe_json(r)})
    d=r.json()
    with Session() as db:
        row=db.query(Connection).filter_by(open_id=d["open_id"]).first()
        if not row:row=Connection(open_id=d["open_id"],access_token=d["access_token"],refresh_token=d["refresh_token"],access_expires_at=now()+int(d.get("expires_in",86400)),refresh_expires_at=now()+int(d.get("refresh_expires_in",0)),scopes=d.get("scope",""),updated_at=now());db.add(row)
        else:row.access_token=d["access_token"];row.refresh_token=d["refresh_token"];row.access_expires_at=now()+int(d.get("expires_in",86400));row.refresh_expires_at=now()+int(d.get("refresh_expires_in",0));row.scopes=d.get("scope",row.scopes);row.updated_at=now()
        db.commit()
    return RedirectResponse("/connected")

@app.get("/")
def home():
    return HTMLResponse(f"<html><body style='font-family:system-ui;max-width:850px;margin:50px auto;padding:20px'><h1>TikTok AI Access API</h1><div style='padding:20px;border:1px solid #ddd;border-radius:12px'><h2>Connect TikTok</h2><p>TikTok Login Kit OAuth 2.0. No password is requested here.</p><a href='/auth/tiktok'>Connect TikTok</a></div><p>AI API Base URL: <code>{BASE_URL or '(set BASE_URL)'}</code></p><p><a href='/api'>API</a> · <a href='/api/docs'>Docs</a> · <a href='/openapi.json'>OpenAPI</a></p></body></html>")
@app.get("/connected")
def connected():
    with Session() as db:c=db.query(Connection).order_by(Connection.id.desc()).first()
    if not c:return RedirectResponse("/")
    scopes=(c.scopes or "").split();return HTMLResponse("<html><body style='font-family:system-ui;max-width:850px;margin:50px auto'><h1>TikTok Connected ✓</h1><p>Authorized scopes:</p><pre>"+json.dumps(sorted(scopes),indent=2)+"</pre><p><a href='/api/capabilities'>Capabilities</a> · <a href='/api/docs'>Docs</a></p></body></html>")

@app.get("/api/me")
def me(request:Request):auth_guard(request);c=conn();scope(c,"user.info.basic");return tiktok(c,"GET","/v2/user/info/",params={"fields":"open_id,union_id,avatar_url,display_name"}).json()
@app.get("/api/profile")
def profile(request:Request):auth_guard(request);c=conn();scope(c,"user.info.profile");return tiktok(c,"GET","/v2/user/info/",params={"fields":"open_id,display_name,avatar_url,profile_deep_link,bio_description,is_verified,username"}).json()
@app.get("/api/stats")
def stats(request:Request):auth_guard(request);c=conn();scope(c,"user.info.stats");return tiktok(c,"GET","/v2/user/info/",params={"fields":"follower_count,following_count,likes_count,video_count"}).json()
@app.get("/api/videos")
def videos(request:Request,cursor:Optional[int]=None,limit:int=20):
    auth_guard(request);c=conn();scope(c,"video.list");body={"max_count":max(1,min(limit,20)),"fields":["id","create_time","cover_image_url","share_url","video_description","duration"]};body.update({"cursor":cursor} if cursor is not None else {});return tiktok(c,"POST","/v2/video/list/",json=body).json()
@app.get("/api/videos/{video_id}")
def video(video_id:str,request:Request):auth_guard(request);c=conn();scope(c,"video.list");return tiktok(c,"POST","/v2/video/query/",json={"filters":{"video_ids":[video_id]},"fields":["id","create_time","cover_image_url","share_url","video_description","duration"]}).json()
@app.get("/api/creator")
def creator(request:Request):auth_guard(request);c=conn();scope(c,"video.publish");return tiktok(c,"POST","/v2/post/publish/creator_info/query/",json={}).json()
@app.get("/api/post/status/{publish_id}")
def post_status(publish_id:str,request:Request):auth_guard(request);c=conn();scope(c,"video.publish");return tiktok(c,"POST","/v2/post/publish/status/fetch/",json={"publish_id":publish_id}).json()

def post_init(c,body,scope_name):
    scope(c,scope_name);path="/v2/post/publish/video/init/" if scope_name=="video.publish" else "/v2/post/publish/inbox/video/init/"
    payload={"post_info":{"title":body.title,"privacy_level":body.privacy_level,"disable_duet":body.disable_duet,"disable_comment":body.disable_comment,"disable_stitch":body.disable_stitch,"brand_organic_toggle":body.brand_organic_toggle,"brand_content_toggle":body.brand_content_toggle,"is_aigc":body.is_aigc},"source_info":{"source":"PULL_FROM_URL","video_url":body.video_url}}
    return tiktok(c,"POST",path,json=payload).json()
@app.post("/api/video/publish")
def publish(body:PostRequest,request:Request):auth_guard(request);return post_init(conn(),body,"video.publish")
@app.post("/api/video/upload")
def upload(body:PostRequest,request:Request):auth_guard(request);return post_init(conn(),body,"video.upload")

@app.post("/api/data/request")
def data_request(body:DataRequestIn,request:Request):
    auth_guard(request);c=conn();cats=body.categories or ["all_data"];scopes=set((c.scopes or "").split())
    if "all_data" in cats:needed={"portability.all.single","portability.all.ongoing"}
    elif "direct_message" in cats:needed={"portability.directmessages.single","portability.directmessages.ongoing"}
    elif any(x in cats for x in ("video","profile")):needed={"portability.postsandprofile.single","portability.postsandprofile.ongoing"}
    else:needed={"portability.activity.single","portability.activity.ongoing"}
    if not scopes.intersection(needed):raise HTTPException(403,detail={"error":"scope_not_authorized","required_any":sorted(needed),"authorized_scopes":sorted(scopes)})
    d=tiktok(c,"POST","/v2/user/data/add/",params={"fields":"request_id"},json={"data_format":body.data_format,"category_selection_list":cats}).json();rid=d.get("data",{}).get("request_id")
    if rid:
        with Session() as db:
            db.add(DataRequest(request_id=rid,category=",".join(cats),data_format=body.data_format,status="REQUESTED",created_at=now()))
            db.commit()
    return d
@app.get("/api/data")
def data_root(request:Request):
    auth_guard(request)
    with Session() as db:rows=db.query(DataRequest).order_by(DataRequest.created_at.desc()).limit(20).all()
    return {"requests":[{"request_id":r.request_id,"category":r.category,"format":r.data_format,"status":r.status,"created_at":r.created_at} for r in rows]}
@app.post("/api/data/status")
def data_status(body:RequestIdIn,request:Request):
    auth_guard(request);c=conn();d=tiktok(c,"POST","/v2/user/data/check/",params={"fields":"request_id,status,apply_time,collect_time,data_format,category_selection_list"},json={"request_id":body.request_id}).json();st=d.get("data",{}).get("status")
    if st:
        with Session() as db:row=db.query(DataRequest).filter_by(request_id=body.request_id).first();row.status=st if row else st;db.commit() if row else None
    return d
@app.post("/api/data/cancel")
def data_cancel(body:RequestIdIn,request:Request):auth_guard(request);return tiktok(conn(),"POST","/v2/user/data/cancel/",json={"request_id":body.request_id}).json()
@app.post("/api/data/download")
def data_download(body:RequestIdIn,request:Request):
    auth_guard(request);r=tiktok(conn(),"POST","/v2/user/data/download/",json={"request_id":body.request_id},headers={"Accept":"application/octet-stream"});return StreamingResponse(io.BytesIO(r.content),media_type="application/zip",headers={"Content-Disposition":f"attachment; filename=tiktok-{body.request_id}.zip"})
@app.get("/api/export")
def latest_export(request:Request):
    auth_guard(request)
    with Session() as db:r=db.query(DataRequest).order_by(DataRequest.created_at.desc()).first()
    return {"export":None} if not r else {"export":{"request_id":r.request_id,"category":r.category,"format":r.data_format,"status":r.status,"download_endpoint":"/api/data/download"}}
@app.get("/api/export/{request_id}")
def export_info(request_id:int,request:Request):
    auth_guard(request);d=tiktok(conn(),"POST","/v2/user/data/check/",params={"fields":"request_id,status,apply_time,collect_time,data_format,category_selection_list"},json={"request_id":request_id}).json();return {"request_id":request_id,"status":d,"download_endpoint":"/api/data/download"}

@app.get("/tiktokwhMmGbrtd3Zbv1qNf6KV6Ol5yNGGda75.txt")
def tiktok_site_verification():
    return StreamingResponse(
        io.BytesIO(b"tiktok-developers-site-verification=whMmGbrtd3Zbv1qNf6KV6Ol5yNGGda75"),
        media_type="text/plain",
    )
