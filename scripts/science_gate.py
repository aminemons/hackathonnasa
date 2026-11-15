#!/usr/bin/env python3
"""TerraPulse scientific-evidence gate, not a disaster-prediction engine."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys
import urllib.parse
import urllib.request

def save(path, data):
    p=pathlib.Path(path)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    print("Wrote",p)

def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()

def check_confusions(obj,path="$",found=None):
    if found is None:found=[]
    if isinstance(obj,dict):
        if {"tp","fp","fn"}.issubset(obj):
            tp,fp,fn=[int(obj[k]) for k in ("tp","fp","fn")]
            tn=int(obj.get("tn",0))
            if min(tp,fp,fn,tn)<0:raise ValueError(f"{path}: negative confusion count")
            safe=lambda numerator,denominator:numerator/denominator if denominator else 0.0
            p=safe(tp,tp+fp);r=safe(tp,tp+fn)
            f1=safe(2*tp,2*tp+fp+fn);iou=safe(tp,tp+fp+fn)
            checks={k:abs(float(obj[k])-v)<2e-5 for k,v in [("precision",p),("recall",r),("f1",f1),("iou",iou)] if k in obj}
            found.append({"path":path,"precision":p,"recall":r,"f1":f1,"iou":iou,"counts":{"tp":tp,"fp":fp,"fn":fn,"tn":tn},"claimed_metric_checks":checks})
        for k,v in obj.items():check_confusions(v,path+"."+k,found)
    elif isinstance(obj,list):
        for i,v in enumerate(obj):check_confusions(v,f"{path}[{i}]",found)
    return found

def audit_report(args):
    src=pathlib.Path(args.report)
    if not src.is_file():raise FileNotFoundError(src)
    obj=json.loads(src.read_text(encoding="utf-8"))
    scores=check_confusions(obj)
    fails=[r["path"] for r in scores if not all(r["claimed_metric_checks"].values())]
    ret={"kind":"model_report_audit","source_path":str(src),"source_sha256":digest(src),
         "checked_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
         "mathematically_checked_splits":scores,
         "status":"PASS" if scores and not fails else "FAIL",
         "caveats":["Correct confusion arithmetic does not establish label validity or absence of event leakage.",
                    "Sen1Floods11 standard split is chip-level; report Bolivia geographical holdout separately.",
                    "Water extent from a flood event is not necessarily newly flooded area."]}
    if not scores:ret["error"]="No tp/fp/fn confusion counts found. Cannot verify metrics."
    if fails:ret["error"]="Inconsistent metrics: "+", ".join(fails)
    save(args.out,ret)
    print("MODEL AUDIT",ret["status"])
    for s in scores:print(s["path"],"F1=",round(s["f1"],4),"IoU=",round(s["iou"],4),"recall=",round(s["recall"],4))
    return 0 if ret["status"]=="PASS" else 2

def audit_nisar(args):
    import numpy as np
    import rasterio
    files={"before":args.before,"after":args.after}
    if args.change:files["change"]=args.change
    rasters={};meta={}
    for name,path in files.items():
        src=rasterio.open(path)
        if src.count<1:raise ValueError(f"{name}: no bands")
        if not src.crs:raise ValueError(f"{name}: missing CRS")
        rasters[name]=src
    try:
        base=rasters["before"]
        for name,src in rasters.items():
            if src.crs!=base.crs or src.width!=base.width or src.height!=base.height or src.transform!=base.transform:
                raise ValueError(f"{name}: raster grids differ (CRS, shape or transform); reproject correctly and rerun")
            meta[name]={"path":str(files[name]),"sha256":digest(files[name]),"crs":str(src.crs),
                        "width":src.width,"height":src.height,"dtype":src.dtypes[0],
                        "nodata":src.nodata,"transform":list(src.transform)[:6]}
        a=rasters["before"].read(1,masked=True).astype("float64")
        b=rasters["after"].read(1,masked=True).astype("float64")
        av=np.asarray(a.filled(np.nan));bv=np.asarray(b.filled(np.nan))
        valid=np.isfinite(av)&np.isfinite(bv)&(av>0)&(bv>0)
        n=int(np.count_nonzero(valid))
        if n==0:raise ValueError("No common positive finite GCOV power pixels; verify input units")
        delta=np.full(av.shape,np.nan)
        delta[valid]=10*np.log10(bv[valid]/av[valid])
        vals=delta[valid]
        p=np.percentile(vals,[1,5,25,50,75,95,99])
        total=base.width*base.height
        result={"kind":"nisar_gcov_change_audit",
                "measurement":"HHHH co-polarized power change",
                "assumed_input_units":"positive, linear GCOV diagonal covariance power (not dB)",
                "delta_formula":"10*log10(P_after/P_before) dB",
                "checked_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
                "common_valid_pixels":n,"total_pixels":total,"coverage_fraction":n/total,
                "grid":meta,"change_db_percentiles":{str(q):float(v) for q,v in zip([1,5,25,50,75,95,99],p)},
                "darkening_candidate_pixels":int(np.count_nonzero(vals<=args.darkening_db)),
                "darkening_candidate_db_threshold":args.darkening_db,
                "scientific_status":"OBSERVED_RADAR_CHANGE_ONLY",
                "caveats":["Radar darkening alone is not floodwater: geometry, roughness, moisture, vegetation and seasonality matter.",
                           "No NISAR inundation F1/IoU without independent flood labels.",
                           "Check acquisition geometry, polarization, QA masks, radiometric conventions and event times.",
                           "No area is claimed without confirmed pixel area support."]}
        if args.change:
            x=rasters["change"].read(1,masked=True).astype("float64").filled(np.nan)
            common=valid&np.isfinite(x)
            if np.count_nonzero(common)==0:raise ValueError("No common valid pixels in change raster")
            absdiff=np.abs(x[common]-delta[common])
            result["published_change_check"]={"common_pixels":int(np.count_nonzero(common)),
                    "mae_db":float(np.mean(absdiff)),"p95_abs_error_db":float(np.percentile(absdiff,95)),
                    "agreement_within_0_1_db_fraction":float(np.mean(absdiff<=0.1))}
            if result["published_change_check"]["p95_abs_error_db"]>0.2:
                result["scientific_status"]="REVIEW_CHANGE_CONVENTION"
                result["caveats"].append("Change GeoTIFF disagrees with direct ratio; check sign, unit conversion and resampling.")
        result["status"]="PASS_GEOMETRY_AND_NUMERIC_QA" if result["scientific_status"]=="OBSERVED_RADAR_CHANGE_ONLY" else "REVIEW"
        save(args.out,result)
        print("NISAR",result["status"],"valid pixels",n,"median delta dB",round(float(p[3]),3))
        return 0 if result["status"].startswith("PASS") else 2
    finally:
        for src in rasters.values():src.close()

def cmr(args):
    vals=list(map(float,args.bbox))
    if len(vals)!=4 or vals[0]>=vals[2] or vals[1]>=vals[3] or not (-180<=vals[0]<=180 and -180<=vals[2]<=180 and -90<=vals[1]<=90 and -90<=vals[3]<=90):
        raise ValueError("BBox must be west south east north")
    if args.start>args.end:raise ValueError("Start must precede end")
    params={"short_name":args.short_name,"bounding_box":",".join(map(str,vals)),
            "temporal":args.start+"T00:00:00Z,"+args.end+"T23:59:59Z",
            "page_size":str(args.limit),"sort_key[]":"-start_date"}
    url="https://cmr.earthdata.nasa.gov/search/granules.umm_json?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"TerraPulseScienceAudit/1.0"})
    with urllib.request.urlopen(req,timeout=50) as resp:obj=json.load(resp)
    items=[]
    for x in obj.get("items",[]):
        umm=x.get("umm",{});time=umm.get("TemporalExtent",{}).get("RangeDateTime",{})
        items.append({"concept_id":x.get("meta",{}).get("concept-id"),"granule_ur":umm.get("GranuleUR"),
                      "beginning":time.get("BeginningDateTime"),"ending":time.get("EndingDateTime"),
                      "collection_reference":umm.get("CollectionReference",{}),
                      "provider":x.get("meta",{}).get("provider-id")})
    data={"kind":"CMR_catalog_search_not_data_download","query":params,"requested_url":url,
          "results":items,"count":len(items),
          "caveat":"Footprint intersection is not pixel overlap; science pixels and metadata require QA."}
    save(args.out,data)
    print("CMR results:",len(items))
    return 0 if items else 3

def main():
    p=argparse.ArgumentParser(description="TerraPulse scientific evidence gate")
    sub=p.add_subparsers(dest="cmd",required=True)
    a=sub.add_parser("report",help="Recalculate reported confusion metrics from raw counts")
    a.add_argument("--report",required=True);a.add_argument("--out",default="outputs/qa_model.json");a.set_defaults(func=audit_report)
    a=sub.add_parser("nisar",help="Audit before/after NISAR GCOV HHHH rasters")
    a.add_argument("--before",required=True);a.add_argument("--after",required=True)
    a.add_argument("--change");a.add_argument("--darkening-db",type=float,default=-3.0)
    a.add_argument("--out",default="outputs/qa_nisar.json");a.set_defaults(func=audit_nisar)
    a=sub.add_parser("cmr",help="Discover real NASA NISAR granule metadata")
    a.add_argument("--short-name",default="NISAR_L2_GCOV_PROVISIONAL_V1")
    a.add_argument("--bbox",nargs=4,metavar=("W","S","E","N"),required=True)
    a.add_argument("--start",required=True);a.add_argument("--end",required=True)
    a.add_argument("--limit",type=int,default=20);a.add_argument("--out",default="outputs/cmr_manifest.json")
    a.set_defaults(func=cmr)
    args=p.parse_args()
    try:return args.func(args)
    except Exception as e:
        print("SCIENCE GATE FAILED:",type(e).__name__,str(e),file=sys.stderr)
        return 2

if __name__=="__main__":raise SystemExit(main())
