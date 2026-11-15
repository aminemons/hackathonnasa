"""Apply the real-trained water model to observed, same-orbit lake sequences."""
import argparse,json,hashlib,math
from pathlib import Path
from datetime import datetime,timezone
import numpy as np,rasterio,xgboost as xgb
from scipy import ndimage as ndi
from rasterio.warp import transform as warp_coords,transform_geom
from rasterio.features import shapes
from rasterio.transform import rowcol
from real_mvp.water import features,terrain_from_dem,FEATURES,counts,metrics,otsu
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--gpu',type=int,default=-1);p.add_argument('--site',default=None);a=p.parse_args();W=a.root/'water';O=a.root/'observed';card=json.loads((W/'water_model_card.json').read_text());threshold=card['threshold'];model=xgb.Booster();model.load_model(W/'models/water_model.json');model.set_param({'device':f'cuda:{a.gpu}' if a.gpu>=0 else 'cpu','nthread':4});weight_hash=hashlib.sha256((W/'models/water_model.json').read_bytes()).hexdigest()
def dump(p,x):
 tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,indent=2,allow_nan=False,default=str));tmp.replace(p)
def target(prob,r,c,t):
 mask=np.isfinite(prob)&(prob>=t);labels,n=ndi.label(mask);sizes=np.bincount(labels.ravel());good=np.where(sizes>=12)[0];good=good[good>0]
 if not len(good):return np.zeros_like(mask)
 yy,xx=np.indices(mask.shape);dist=(yy-r)**2+(xx-c)**2;near=labels[(dist<=(1200/20)**2)&np.isin(labels,good)]
 if not len(near):return np.zeros_like(mask)
 nearest=int(labels.ravel()[np.argmin(np.where(np.isin(labels,good),dist,np.inf))]);return labels==nearest
for S in sorted(O.iterdir()):
 if a.site and S.name!=a.site:continue
 if not S.is_dir() or not (S/'manifest.json').exists() or not (S/'dem_lake.tif').exists():continue
 m=json.loads((S/'manifest.json').read_text());site=m['site'];ts=[];optical=[];geometries={}
 cache_path=S/'prediction_cache.json';cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
 cache_key={'weights_sha256':weight_hash,'threshold':threshold,'feature_version':'water-v1-21'}
 cache_matches=cache.get('model')==cache_key;source_cache={}
 with rasterio.open(S/'dem_lake.tif') as ds:dem=ds.read(1);tr=ds.transform;crs=ds.crs
 slope,height=terrain_from_dem(dem,tr,crs);x,y=warp_coords('EPSG:4326',crs,[site['lake_lon']],[site['lake_lat']]);r,c=rowcol(tr,x[0],y[0]);r=int(np.clip(r,0,dem.shape[0]-1));c=int(np.clip(c,0,dem.shape[1]-1))
 for epoch in sorted(m['epochs'],key=lambda e:e['date']):
  day=epoch['date'];path=S/f'prediction_{day}.npz'
  with rasterio.open(S/epoch['file']) as src:sar=src.read();profile=src.profile
  if sar.shape[1:]!=dem.shape:raise ValueError('Terrain/SAR alignment mismatch')
  if path.exists() and cache_matches and cache.get('sources',{}).get(day)==epoch['sha256']:
   with np.load(path) as z:prob=z['prob'].astype('float32');lake=z['lake_mask']
  else:
   f=features(sar,slope,height).reshape(len(FEATURES),-1).T;prob=model.predict(xgb.DMatrix(f,feature_names=FEATURES)).reshape(dem.shape);prob[~np.all(np.isfinite(sar),axis=0)]=np.nan;lake=target(prob,r,c,threshold);np.savez_compressed(path,prob=prob.astype('float16'),lake_mask=lake)
  source_cache[day]=epoch['sha256']
  low=target(prob,r,c,min(.95,threshold+.1));high=target(prob,r,c,max(.05,threshold-.1));raw_area=float(lake.sum()*abs(tr.a*tr.e)/1e6);area=raw_area if lake.any() else None;valid=float(np.mean(np.all(np.isfinite(sar),axis=0)))
  ts.append({'date':day,'accepted':valid>=.7,'lake_area_km2':area,'raw_lake_area_km2':raw_area,'area_filter_changed':False,'area_estimate_status':'mapped_component' if area is not None else 'unresolved_no_connected_lake','lake_area_sensitivity_km2':[float(min(low.sum()*.0004,raw_area,high.sum()*.0004)),float(max(low.sum()*.0004,raw_area,high.sum()*.0004))] if area is not None else None,'interval_kind':'threshold_sensitivity_not_95pct_ci','valid_fraction':valid,'source_ids':[g['id'] for g in epoch['granules']],'operational_status':'not_assessed'})
  gg=[]
  for geom,val in shapes(lake.astype('uint8'),mask=lake,transform=tr):
   gg.append({'type':'Feature','geometry':transform_geom(crs,'EPSG:4326',geom,precision=7),'properties':{'layer':'glacial_lake','site_id':site['site_id'],'date':day,'area_km2':area,'evidence_kind':'observed_SAR_model_output','operational_status':'not_assessed'}})
  fc={'type':'FeatureCollection','features':gg};dump(S/f'lake_{day}.geojson',fc);geometries[day]=fc
  op=S/f'optical_{day}.npz'
  if op.exists():
   with np.load(op) as z:label=z['label']
   yy,xx=np.indices(dem.shape);roi=((yy-r)**2+(xx-c)**2)<(2000/20)**2;ev=(label>=0)&roi&np.isfinite(prob)&np.isfinite(slope)&np.isfinite(height);terrain=(slope<10)&(height<30);ot=otsu(sar[1][np.isfinite(sar[1])]);vh=card['training']['validation_vh_terrain_db']
   optical.append({'date':day,'reference':json.loads(op.with_suffix('.json').read_text()),'evaluated_roi_radius_m':2000,'metrics':{'ml':metrics(counts(label,prob>=threshold,ev)),'otsu_terrain':metrics(counts(label,(sar[1]<ot)&terrain,ev)),'tuned_vh_terrain':metrics(counts(label,(sar[1]<vh)&terrain,ev))},'status':'independent optical spectral reference; not manual field truth'})
 if not ts:continue
 dump(cache_path,{'model':cache_key,'sources':source_cache})
 latest=ts[-1];events=[]
 for before,after in zip(ts,ts[1:]):
  if before['lake_area_km2'] is not None and after['lake_area_km2'] is not None and before['lake_area_km2']>.05 and after['lake_area_km2']<before['lake_area_km2']*.7:
   events.append({'between':[before['date'],after['date']],'area_drop_pct':100*(1-after['lake_area_km2']/before['lake_area_km2']),'interpretation':'Observed-model area-drop candidate; seasonal ice, geometry and classification error require review. Post-change detection, not forecast.'})
 ni=a.root/'nisar'/S.name/'report.json';nisar=json.loads(ni.read_text()) if ni.exists() else {'status':'unavailable'};ve=a.root/'velocity'/S.name/'report.json';velocity=json.loads(ve.read_text()) if ve.exists() else {'status':'unavailable'}
 source_rows=[{'provider':'NASA / ASF','product':'NISAR L-band GCOV','status':'observed' if nisar.get('status')=='complete' else nisar.get('status'),'detail':'Real NISAR pair with concept IDs; separate GPU 1 radiometric regression. No NISAR water/hazard accuracy claimed.','url':'https://nisar-docs.asf.alaska.edu/'},{'provider':'India / ISRO','product':'S-band / Bhoonidhi','status':'not_ingested','detail':'NISAR is joint NASA–ISRO. No ISRO S-band observations are silently substituted by ESA Sentinel-1.','url':'https://bhoonidhi.nrsc.gov.in/NISAR/'},{'provider':'ESA / Copernicus','product':'Sentinel-1 C-band RTC','status':'observed','detail':f"{len(ts)} real same-orbit epochs, {ts[0]['date']} to {latest['date']}. Model trained on hand-labelled C-band GRD: RTC radiometric/domain transfer is evaluated separately.",'url':'https://planetarycomputer.microsoft.com/dataset/sentinel-1-rtc'},{'provider':'ESA / Copernicus','product':'Independent Sentinel-2 optical reference','status':'available' if optical else 'unavailable','detail':'Cloud/snow-masked spectral references, fixed independently of SAR. Date gaps and automatic label uncertainty are reported.'},{'provider':'Copernicus','product':'GLO-30 observed terrain','status':'observed','detail':'Real 30 m DSM, resampled onto 20 m processing grid. Local relief is a HAND proxy, not hydrologically derived HAND.'},{'provider':'NASA MEaSUREs','product':'ITS_LIVE annual velocities','status':velocity.get('status','unavailable'),'detail':'Measured annual velocity and available 1985–2022 median. Velocity is not a glacier thinning measurement.','url':'https://its-live.jpl.nasa.gov/'}]
 usable_refs=[v for v in optical if v['metrics']['ml']['tp']+v['metrics']['ml']['fn']>=100 and v['metrics']['ml']['iou'] is not None]
 median_iou=float(np.median([v['metrics']['ml']['iou'] for v in usable_refs])) if usable_refs else None
 water_grade='moderate' if len(usable_refs)>=2 and median_iou>=.7 else 'limited' if median_iou is not None and median_iou>=.4 else 'low' if median_iou is not None else 'unassessed'
 grade_basis=f'Heuristic water-map evidence grade only: median optical-reference IoU {median_iou} across {len(usable_refs)} checks with at least100 annotated water pixels. Automatic references and date mismatch remain uncertain. This does not grade breach forecasting.'
 validation=[{'id':'benchmark','title':'Independent annotated benchmark','status':'complete','detail':'446 real Sentinel-1 / hand-label pairs; publisher checksums verified. Leave-one-event-region-out with nested validation and event-cluster bootstrap.'},{'id':'baseline','title':'Terrain-aware baseline','status':'complete','detail':'All methods evaluated on identical valid pixels; thresholds tuned only in validation. Every held-out case is inspectable.'},{'id':'alpine','title':'Glacial-lake transfer','status':'partial' if optical else 'pending','detail':f'{len(optical)} independent optical-reference comparisons for this lake. Spectral references are not surveyed shorelines.'},{'id':'forecast','title':'Real GLOF forecast calibration','status':'missing','detail':'Historical event inventory ingested. Verified stable control lake-years and fully observed pre-event precursor tables are missing; no operational event probability is produced.'},{'id':'routing','title':'Flood routing validation','status':'pending','detail':'Conservative 2D solver is tested for mass balance; observed flood-depth and arrival-time validation is not established.'}]
 summary={'site':site,'latest_date':latest['date'],'latest_lake_area_km2':latest['lake_area_km2'],'latest_lake_area_sensitivity_km2':latest['lake_area_sensitivity_km2'],'timeseries':ts,'data_sources':{'sar_source':'observed_sentinel1_rtc','manifest':'manifest.json','weights_sha256':weight_hash},'prediction':{'alert_level':'NOT_ASSESSED','breach_probability':None},'research_prediction':{'interpretation':'No breach model score is substituted from synthetic training.'},'evidence':{'data_kind':'observed','confidence':water_grade,'confidence_basis':grade_basis,'interval_interpretation':'Area ranges are threshold sensitivity envelopes, not calibrated confidence intervals.','sources':source_rows,'validation':validation,'history':'Documented outburst on 4 October 2023; historical observed replay includes pre/post-event SAR. Area-drop detection is not an early-warning forecast.' if S.name=='south_lhonak' else 'Historical observed replay; recurring ice-dam drainage is distinct from moraine breach.' if S.name=='suicide_basin' else 'Historical observed replay; no calibrated event probability is claimed.','map_geometry':'Geometry is available per observed epoch.'},'flood_simulation':{'town_impacts':[],'interpretation':'No synthetic flood scenario is mixed into the observed run.'},'noise_diagnostics':{'total_scenes':len(ts),'accepted_scenes':sum(t['accepted'] for t in ts)},'optical_validation':optical,'area_drop_candidates':events,'nisar':nisar,'velocity':velocity,'model':{'path':'water/models/water_model.json','threshold':threshold,'sha256':weight_hash,'features':FEATURES},'cogs':{},'segmentation_metrics':{}}
 if (S/'flood_scenario.json').exists():summary['flood_simulation']=json.loads((S/'flood_scenario.json').read_text())
 if (S/'exposure_report.json').exists():summary['exposure']=json.loads((S/'exposure_report.json').read_text())
 if (S/'orbit_diagnostic.json').exists():summary['orbit_diagnostic']=json.loads((S/'orbit_diagnostic.json').read_text())
 dump(S/'observed_summary.json',summary);dump(S/'observed_geometry.geojson',geometries[latest['date']]);dump(S/'optical_validation.json',optical);print(S.name,len(ts),'epochs',len(optical),'optical references',flush=True)
