"""Sentinel-1 VV/VH feature contract. Never accepts NISAR HH/HV implicitly."""
import numpy as np
from scipy import ndimage as ndi

FEATURES=['vv_db','vh_db','vv_minus_vh','vv_plus_vh','vv_mean3','vh_mean3','vv_mean9','vh_mean9','vv_mean25','vh_mean25','vv_std9','vh_std9','vv_std25','vh_std25','vv_local_residual','vh_local_residual','vv_edge','vh_edge','vh_dark_fraction','slope_deg','local_height_m']

def features(sar,slope=None,height=None):
    a=np.clip(np.nan_to_num(sar[:2],nan=-25,posinf=5,neginf=-50),-50,10).astype('float32')
    vv,vh=a;out=[vv,vh,vv-vh,vv+vh];means={}
    for n in (3,9,25):
        means[n]=[ndi.uniform_filter(v,n,mode='reflect') for v in a]
        out.extend(means[n])
    for n in (9,25):
        out.extend([np.sqrt(np.maximum(ndi.uniform_filter(v*v,n,mode='reflect')-m*m,0)) for v,m in zip(a,means[n])])
    out += [vv-means[25][0],vh-means[25][1],np.hypot(*np.gradient(vv)),np.hypot(*np.gradient(vh)),ndi.uniform_filter((vh<-23).astype('float32'),9)]
    out += [np.full(vv.shape,np.nan,dtype='float32') if v is None else np.asarray(v,dtype='float32') for v in (slope,height)]
    return np.stack(out).astype('float32')

def otsu(a):
    v=a[np.isfinite(a)];v=np.clip(v,-50,5)
    if len(v)<10:return -23.
    h,e=np.histogram(v,bins=256,range=(-50,5));m=(e[:-1]+e[1:])/2
    w=np.cumsum(h);rev=w[-1]-w;s=np.cumsum(h*m);den=w*rev
    score=np.divide((s[-1]*w-s*w[-1])**2,den,out=np.zeros_like(s),where=den>0)
    return float(m[np.argmax(score)])

def terrain_from_dem(dem,transform,crs):
    resx=abs(transform.a);resy=abs(transform.e)
    if crs.is_geographic:
        lat=transform.f+transform.e*dem.shape[0]/2
        resx*=111320*np.cos(np.radians(lat));resy*=110574
    valid=np.isfinite(dem)
    filled=np.where(valid,dem,np.nanmedian(dem) if valid.any() else 0.)
    gy,gx=np.gradient(filled,resy,resx)
    slope=np.degrees(np.arctan(np.hypot(gx,gy))).astype('float32')
    # Physical 500 m local relief window, explicitly not drainage-derived HAND.
    window=max(3,round(500/max((resx+resy)/2,1)));window+=1-window%2
    height=(filled-ndi.minimum_filter(filled,size=window)).astype('float32')
    slope[~valid]=np.nan;height[~valid]=np.nan
    return slope,height

def counts(y,p,valid):
    y=y[valid]==1;p=p[valid].astype(bool)
    return [int(np.sum(y&p)),int(np.sum(~y&p)),int(np.sum(y&~p)),int(np.sum(~y&~p))]

def metrics(c):
    tp,fp,fn,tn=map(int,c)
    div=lambda a,b:a/b if b else None
    return dict(tp=tp,fp=fp,fn=fn,tn=tn,iou=div(tp,tp+fp+fn),f1=div(2*tp,2*tp+fp+fn),precision=div(tp,tp+fp),recall=div(tp,tp+fn),valid_pixels=tp+fp+fn+tn)
