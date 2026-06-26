import os
import sys
# Add backend directory and project root to sys.path to locate db/, services/, and agent/
_base_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_base_dir)
if _base_dir not in sys.path:
    sys.path.append(_base_dir)
if _root_dir not in sys.path:
    sys.path.append(_root_dir)

# 解决国内服务器加载 Hugging Face 模型报错：在任何第三方库载入前，自动读取并加载 .env 文件中的镜像配置 (如 HF_ENDPOINT)
# 使用 __file__ 的绝对路径定位，确保无论在哪个目录下运行 python3 server.py，都能精准读取到根目录下的 .env 文件
_env_path = os.path.join(os.path.dirname(_base_dir), ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")


import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

# Database setup
from db.mysql import get_db
from db.redis import check_redis_connectivity

# Services setup
import services.feedback_service as feedback_service
import services.event_service as event_service
import services.chat_service as chat_service

app = FastAPI(title="Sanguozhi Map API")

@app.on_event("startup")
async def startup_event():
    await check_redis_connectivity()
    try:
        from db.mysql import Base, engine
        Base.metadata.create_all(bind=engine)
        print("✅ [Database] Checked and successfully initialized MySQL tables.")
    except Exception as e:
        print(f"⚠️ [Database] Failed to initialize MySQL tables: {e}")

# Add CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic schemas (keeping exactly what frontend expects)
class AskRequest(BaseModel):
    question: str
    history: list[dict] = []
    session_id: Optional[str] = None
    user_id: Optional[str] = None

class FeedbackRequest(BaseModel):
    event_id: str
    event_title: str
    field_name: str
    proposed_value: str

class AdminDeleteRequest(BaseModel):
    ids: list[int]

class AdminApplyItem(BaseModel):
    id: int
    event_id: str
    field_name: str
    proposed_value: str

class AdminApplyRequest(BaseModel):
    items: list[AdminApplyItem]

class ShareCreateRequest(BaseModel):
    question: str
    answer: str

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "sanguo123")

def verify_admin_password(x_admin_password: str = Header(None)):
    if not x_admin_password or x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=401,
            detail="密码错误，军师请重新输入。"
        )

# Routes

@app.get("/api/eastern-han-admin")
def get_eastern_han_admin():
    try:
        return event_service.get_eastern_han_admin()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/feedback")
def api_feedback(req: FeedbackRequest, db: Session = Depends(get_db)):
    success = feedback_service.create_feedback(
        db, req.event_id, req.event_title, req.field_name, req.proposed_value
    )
    if success:
        return {"success": True, "message": "Feedback submitted successfully."}
    else:
        return {"success": False, "message": "Failed to submit feedback."}

@app.get("/api/admin/feedback")
def get_admin_feedback(x_admin_password: str = Header(None), db: Session = Depends(get_db)):
    verify_admin_password(x_admin_password)
    try:
        feedbacks = feedback_service.get_pending_feedbacks(db)
        results = []
        for fb in feedbacks:
            results.append({
                "id": fb.id,
                "event_id": fb.event_id,
                "event_title": fb.event_title,
                "field_name": fb.field_name,
                "proposed_value": fb.proposed_value,
                "status": fb.status,
                "created_at": fb.created_at.isoformat() if fb.created_at else None
            })
        return {"success": True, "feedbacks": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/feedback/delete")
def delete_admin_feedback(req: AdminDeleteRequest, x_admin_password: str = Header(None), db: Session = Depends(get_db)):
    verify_admin_password(x_admin_password)
    if not req.ids:
        return {"success": True, "message": "No feedbacks to delete."}
    try:
        success = feedback_service.delete_feedbacks(db, req.ids)
        if success:
            return {"success": True, "message": f"Successfully deleted {len(req.ids)} feedback records."}
        else:
            raise HTTPException(status_code=500, detail="Failed to delete feedbacks.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/feedback/apply")
def apply_admin_feedback(req: AdminApplyRequest, x_admin_password: str = Header(None), db: Session = Depends(get_db)):
    verify_admin_password(x_admin_password)
    if not req.items:
        return {"success": True, "message": "No feedbacks to apply."}
    try:
        result = feedback_service.apply_feedbacks(db, req.items)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ask")
async def api_ask(req: AskRequest, db: Session = Depends(get_db)):
    return await chat_service.handle_ask_stream(req.question, req.history, req.session_id, req.user_id, db)

@app.post("/api/shares")
def create_share(req: ShareCreateRequest, db: Session = Depends(get_db)):
    import secrets
    from db.mysql import Share
    try:
        for _ in range(5):
            share_id = "s_" + secrets.token_hex(4)
            existing = db.query(Share).filter(Share.id == share_id).first()
            if not existing:
                break
        else:
            raise HTTPException(status_code=500, detail="Failed to generate unique share ID")

        new_share = Share(
            id=share_id,
            question=req.question,
            answer=req.answer
        )
        db.add(new_share)
        db.commit()
        return {"success": True, "share_id": share_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/shares/{share_id}")
def get_share(share_id: str, db: Session = Depends(get_db)):
    from db.mysql import Share
    try:
        share = db.query(Share).filter(Share.id == share_id).first()
        if not share:
            raise HTTPException(status_code=404, detail="分享的锦囊卷宗不存在。")
        return {
            "success": True,
            "share": {
                "id": share.id,
                "question": share.question,
                "answer": share.answer,
                "created_at": share.created_at.isoformat() if share.created_at else None
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/lan-ip")
def get_lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return {"ip": ip}
    except Exception:
        return {"ip": "127.0.0.1"}

@app.get("/api/status")
async def api_status():
    try:
        event_service.check_neo4j_status()
        return {"status": "connected"}
    except Exception as e:
        return {"status": "disconnected", "error": str(e)}

@app.get("/api/events")
async def api_events(
    start: int, end: int,
    person_include: str = "",
    person_or: str = "",
    person_exclude: str = "",
    location: str = "",
    event_type: str = "",
    biography_only: bool = False,
    limit: int = 100,
    offset: int = 0,
):
    try:
        events, has_more = event_service.query_events(
            start=start, end=end,
            person_include=person_include,
            person_or=person_or,
            person_exclude=person_exclude,
            location=location,
            event_type=event_type,
            biography_only=biography_only,
            limit=limit,
            offset=offset
        )
        return {
            "events": events,
            "has_more": has_more,
            "offset": offset,
            "limit": limit
        }
    except Exception as err:
        print(f"[Query error] {err}")
        return {"events": []}

@app.get("/api/location-events")
async def api_location_events(
    name: str,
    level: str = "county",
    province: str = "",
    commandery: str = "",
    start: int = 180,
    end: int = 280,
    limit: int = 500,
):
    try:
        events = event_service.query_location_events(
            name=name, level=level, province=province, commandery=commandery,
            start=start, end=end, limit=limit
        )
        location_names = event_service.expand_location_names(name, level, province, commandery)
        return {
            "location": name,
            "level": level,
            "expanded_locations": location_names,
            "events": events
        }
    except Exception as err:
        print(f"[Location query error] {err}")
        location_names = event_service.expand_location_names(name, level, province, commandery)
        return {"location": name, "level": level, "expanded_locations": location_names, "events": []}

@app.get("/api/events/{event_id}")
async def api_event_detail(event_id: str):
    try:
        event = event_service.query_event_detail(event_id)
        return {"event": event}
    except Exception as err:
        print(f"Event detail query error: {err}")
        return {"event": None}

@app.get("/api/filter-meta")
async def api_filter_meta():
    try:
        return event_service.get_filter_meta()
    except Exception as err:
        print(f"Meta error: {err}")
        return {"locations": [], "event_types": []}

@app.get("/api/persons")
async def api_persons():
    try:
        persons = event_service.get_persons_list()
        return {"persons": persons}
    except Exception as err:
        return {"persons": []}

@app.get("/api/person/{name}")
async def api_person_timeline(name: str):
    try:
        events = event_service.get_person_timeline(name)
        return {"name": name, "events": events}
    except Exception as err:
        print(f"Person query error: {err}")
        return {"name": name, "events": []}

@app.get("/api/person-relations/{name}")
async def api_person_relations(name: str, limit: int = 80):
    try:
        return event_service.get_person_relations(name, limit)
    except Exception as err:
        print(f"Person relations query error: {err}")
        return {
            "name": name,
            "hometown": None,
            "clan": None,
            "nodes": [{"id": name, "label": name, "type": "center"}],
            "links": [],
            "relations": []
        }

@app.get("/api/graph")
async def api_graph(limit: int = 150):
    try:
        return event_service.get_force_graph(limit)
    except Exception as err:
        return {"nodes": [], "links": []}

if __name__ == "__main__":
    print("🚀 正在启动三国历史数字地图 API 服务...")
    print("请在浏览器中打开: http://127.0.0.1:8000")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
