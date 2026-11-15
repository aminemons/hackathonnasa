"""Bounded, source-attributed same-origin EONET fetch on browser CORS failure."""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.error import HTTPError, URLError
import json
try:
    from .events import _request
except ImportError:
    from events import _request

CATEGORIES=frozenset(("volcanoes","wildfires","floods","landslides","severeStorms","drought","seaLakeIce"))
def collect(category,status="open",limit=200,start=None,end=None,days=None):
    if category not in CATEGORIES: raise ValueError("Unsupported EONET category")
    if status not in ("open","all","closed"): raise ValueError("Invalid event status")
    if type(limit) is not int or not 1 <= limit <= 1500: raise ValueError("Invalid event limit")
    if (start is None)!=(end is None): raise ValueError("Both date boundaries required")
    if days is not None and (start is not None or type(days) is not int or not 1 <= days <= 365):
        raise ValueError("Choose a 1–365-day lookback")
    if start is not None:
        try:
            lo=datetime.strptime(start,"%Y-%m-%d").date()
            hi=datetime.strptime(end,"%Y-%m-%d").date()
        except (TypeError,ValueError) as exc: raise ValueError("Use YYYY-MM-DD") from exc
        if not lo<=hi or (hi-lo).days>366: raise ValueError("Select at most one calendar year")
    params={"status":status,"category":category,"limit":limit}
    if days is not None:params["days"]=days
    if start:params.update({"start":start,"end":end})
    response=_request("https://eonet.gsfc.nasa.gov/api/v3/events?"+urlencode(params))
    if not isinstance(response.get("events"),list):raise RuntimeError("Invalid EONET event collection")
    return {"events":response["events"],"status":"ok","source":"NASA EONET",
            "category":category,"fetched_at":datetime.now(timezone.utc).isoformat()}

class handler(BaseHTTPRequestHandler):
    def send_json(self,obj,status=200):
        body=json.dumps(obj,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","public, s-maxage=600, stale-while-revalidate=300" if status==200 else "no-store")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if urlsplit(self.path).path.rstrip("/")!="/api/catalog":
            return self.send_json({"error":"Not found"},404)
        q=parse_qs(urlsplit(self.path).query)
        try:
            result=collect(q.get("category",[""])[0],q.get("status",["open"])[0],
                int(q.get("limit",["200"])[0]),q.get("start",[None])[0],
                q.get("end",[None])[0],int(q["days"][0]) if "days" in q else None)
        except (ValueError,TypeError) as exc:return self.send_json({"error":str(exc)},400)
        except (HTTPError,URLError,OSError,TimeoutError,RuntimeError,json.JSONDecodeError):
            return self.send_json({"status":"unavailable",
                "error":"NASA EONET source unavailable; do not interpret as zero events"},503)
        self.send_json(result)
