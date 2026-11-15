"""Hybrid TerraPulse assistant: deterministic map actions + grounded speech.
Optional Groq free-tier key enriches language only, never controls map tools.
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError,URLError
import json
import os
try:
    from .chat_router import plan
    from .chat_science import select
except ImportError:
    from chat_router import plan
    from chat_science import select

API="https://api.groq.com/openai/v1/chat/completions"
MODEL="llama-3.1-8b-instant"
GUIDANCE=(
 "You are TerraPulse, a precise but friendly Earth-observation tutor. "
 "Respond in plain English using only the provided verified evidence. "
 "Never invent live observations, source availability, local hazard probability, "
 "earthquake prediction, GLOF breach prediction, evacuation orders or unsupported dates. "
 "When the evidence is insufficient say what is not known. Keep explanations under "
 "140 words, conversational, with helpful context. Do not output tool commands, JSON or HTML."
)
def clean_history(history):
    if not isinstance(history,list):return []
    result=[]
    for item in history[-6:]:
        if isinstance(item,dict) and item.get("role") in ("user","assistant") and isinstance(item.get("content"),str):
            result.append({"role":item["role"],"content":item["content"][:500]})
    return result

def llm_reply(message,history,evidence,planned):
    secret=os.environ.get("GROQ_API_KEY","")
    if not secret:return None
    body={
      "model":os.environ.get("GROQ_MODEL",MODEL),
      "temperature":0.25,"max_tokens":280,
      "messages":[{"role":"system","content":GUIDANCE+"\nVerified evidence: "+evidence+
                   "\nDeterministic interface result: "+planned},
                  *clean_history(history),{"role":"user","content":message[:800]}]
    }
    request=Request(API,method="POST",data=json.dumps(body).encode("utf-8"),headers={
        "Authorization":"Bearer "+secret,"Content-Type":"application/json",
        "Accept":"application/json","User-Agent":"TerraPulse-Research-Assistant/2.0"})
    try:
        with urlopen(request,timeout=8) as resp:
            payload=resp.read(96_000)
        obj=json.loads(payload)
        reply=obj.get("choices",[{}])[0].get("message",{}).get("content")
        if isinstance(reply,str) and len(reply.strip())>10:return reply.strip()[:1300]
    except (OSError,HTTPError,URLError,TimeoutError,ValueError,KeyError,IndexError,json.JSONDecodeError):
        pass
    return None

def respond(message,history=None):
    planned=plan(message)
    safe_history=clean_history(history)
    evidence=select(message,safe_history)
    action=bool(planned.get("actions"))
    is_question=message.strip().endswith("?") or bool(__import__("re").match(
        r"(?i)^\s*(what|why|how|when|where|can you explain|explain|compare|tell me|is it)\b",message))
    primary=(evidence["answer"] if evidence and (is_question or not action) else planned["reply"])
    if evidence and action and is_question:
        primary=planned["reply"]+" "+evidence["answer"]
    enriched=llm_reply(message,safe_history,primary,planned["reply"])
    reply=enriched or primary
    return {"reply":reply,"actions":planned["actions"],"references":evidence["references"] if evidence else [],
       "model_is_generative":bool(enriched),
       "engine":"Groq LLM + deterministic action router" if enriched else "Grounded local explanations + deterministic action router",
       "limitations":"Information and experimental model outputs, not official emergency warnings"}

class handler(BaseHTTPRequestHandler):
    def send_json(self,obj,status=200):
        raw=json.dumps(obj,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if urlsplit(self.path).path.rstrip("/")!="/api/chat":return self.send_json({"error":"Not found"},404)
        self.send_json({"name":"TerraPulse conversational map assistant",
          "generative_llm_configured":bool(os.environ.get("GROQ_API_KEY")),
          "conversation_storage":"none","speech":"Browser speechSynthesis + optional SpeechRecognition",
          "actions":"strict deterministic whitelist"})
    def do_POST(self):
        if urlsplit(self.path).path.rstrip("/")!="/api/chat":return self.send_json({"error":"Not found"},404)
        if self.headers.get_content_type()!="application/json":
            return self.send_json({"error":"JSON request required"},415)
        try:
            length=int(self.headers.get("Content-Length","0"))
            if not 1<=length<=8192:raise ValueError("Request must be 1–8192 bytes")
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise ValueError("Expected object")
            message=data.get("message")
            if not isinstance(message,str) or not 1<=len(message.strip())<=800:
                raise ValueError("Enter 1–800 characters")
            result=respond(message,data.get("history"))
        except (ValueError,TypeError,json.JSONDecodeError) as exc:return self.send_json({"error":str(exc)},400)
        self.send_json(result)
