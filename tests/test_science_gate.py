import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
HERE=Path(__file__).resolve().parents[1]
CLI=HERE/"scripts/science_gate.py"
def run(*args):
    return subprocess.run([sys.executable,str(CLI),*map(str,args)],capture_output=True,text=True)
def test_report_confusion_arithmetic(tmp_path):
    p=tmp_path/"report.json";out=tmp_path/"out.json"
    p.write_text(json.dumps({"test":{"tp":8,"fp":2,"fn":2,"tn":88,"f1":.8,"iou":2/3},"bolivia":{"tp":6,"fp":2,"fn":4,"tn":88,"f1":2/3}}))
    r=run("report","--report",p,"--out",out)
    assert r.returncode==0,r.stderr
    assert json.loads(out.read_text())["status"]=="PASS"
    p.write_text(json.dumps({"test":{"tp":8,"fp":2,"fn":2,"f1":.99}}))
    assert run("report","--report",p,"--out",out).returncode==2
def tif(path,array,transform=None):
    with rasterio.open(path,"w",driver="GTiff",height=array.shape[0],width=array.shape[1],count=1,dtype="float32",crs="EPSG:32645",transform=transform or from_origin(500000,3100000,20,20),nodata=-9999) as ds:ds.write(array.astype("float32"),1)
def test_nisar_qa_and_mismatch(tmp_path):
    a=tmp_path/"a.tif";b=tmp_path/"b.tif";c=tmp_path/"c.tif";o=tmp_path/"qa.json"
    x=np.ones((50,50),dtype="float32")*.1
    y=x.copy();y[:15,:15]=.05
    tif(a,x);tif(b,y);tif(c,10*np.log10(y/x))
    r=run("nisar","--before",a,"--after",b,"--change",c,"--out",o)
    assert r.returncode==0,r.stderr
    data=json.loads(o.read_text());assert data["common_valid_pixels"]==2500
    assert data["published_change_check"]["p95_abs_error_db"]<.01
    tif(c,abs(10*np.log10(y/x)))
    assert run("nisar","--before",a,"--after",b,"--change",c,"--out",o).returncode==2
    tif(b,y,from_origin(500100,3100000,20,20))
    assert run("nisar","--before",a,"--after",b,"--out",o).returncode==2
