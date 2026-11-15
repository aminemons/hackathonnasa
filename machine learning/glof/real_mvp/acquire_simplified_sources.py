"""Bounded public GLIMS and JRC additions for the three-indicator GLOF MVP.

No observed outputs are overwritten. Historical outline dates, model look-ahead
limits, no-data and source attribution remain explicit in each manifest.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import math

import numpy as np
import requests
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely import make_valid

GLIMS='https://integration.glims.org/geoserver/ows'
JRC='https://s3.waw4-1.cloudferro.com/swift/v1/global-surface-water/'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def dump(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False,default=str))

def glaciers(site,folder):
    bbox=site['lake_bbox'];bbox=[bbox[0]-.03,bbox[1]-.03,bbox[2]+.03,bbox[3]+.03]
    params={'service':'WFS','version':'1.0.0','request':'GetFeature',
            'typeName':'GLIMS:GLIMS_Glacier_Outlines','outputFormat':'application/json',
            'srsName':'EPSG:4326','bbox':','.join(map(str,bbox))+',EPSG:4326','maxFeatures':3000}
    raw_path=folder/'glims_source.geojson'
    if raw_path.exists():
        raw=json.loads(raw_path.read_text());query=requests.Request('GET',GLIMS,params=params).prepare().url
    else:
        response=requests.get(GLIMS,params=params,timeout=90);response.raise_for_status();raw=response.json();query=response.url
        dump(raw_path,raw)
    if len(raw.get('features',[]))>=3000:raise ValueError('GLIMS result reached retrieval bound; do not silently truncate')
    grouped={}
    for f in raw.get('features',[]):
        p=f['properties'];gid=p.get('glac_id')
        if gid and p.get('line_type')=='glac_bound' and p.get('rec_status')=='okay':
            grouped.setdefault(gid,{}).setdefault(str(p.get('anlys_id')),[]).append(f)
    output=[]
    for gid,analyses in grouped.items():
        latest=max(analyses.values(),key=lambda fs:(max(str(f['properties'].get('src_date') or '') for f in fs),max(int(f['properties'].get('anlys_id') or 0) for f in fs)))
        # GLIMS also contains reconstructed Little Ice Age outlines (e.g. 1450).
        # Preserve them in raw data, but do not use as modern ice/stable-ground masks.
        source_date=str(latest[0]['properties'].get('src_date') or '')
        if not source_date or source_date[:4]<'1980':continue
        aid=latest[0]['properties'].get('anlys_id')
        geom=unary_union([make_valid(shape(f['geometry'])) for f in latest])
        # Companion rocks and lake polygons from the same analysis are holes,
        # not extra ice surfaces or different-date glacier outlines.
        holes=[make_valid(shape(f['geometry'])) for f in raw.get('features',[])
               if f['properties'].get('glac_id')==gid and f['properties'].get('anlys_id')==aid
               and f['properties'].get('line_type') in ('intrnl_rock','supra_lake','pro_lake')]
        if holes:geom=geom.difference(unary_union(holes))
        if geom.is_empty:continue
        if geom.geom_type=='GeometryCollection':
            geom=unary_union([g for g in geom.geoms if g.geom_type in ('Polygon','MultiPolygon')])
        if geom.geom_type not in ('Polygon','MultiPolygon'):continue
        props={**latest[0]['properties'],'source_group':'International / GLIMS via NSIDC',
               'source_url':'https://nsidc.org/data/nsidc-0272/versions/1',
               'geometry_role':'latest available outline per GLIMS glacier ID; not a validated feeding-glacier delineation',
               'source_date_preserved':True,'same_analysis_holes_subtracted':len(holes)}
        output.append({'type':'Feature','id':gid,'geometry':mapping(geom),'properties':props})
    path=folder/'glaciers.geojson';dump(path,{'type':'FeatureCollection','features':output})
    return {'kind':'glacier_outlines','status':'downloaded' if output else 'no_glacier_outlines',
            'file':path.name,'sha256':sha(path),'source_query':query,'source_group':'International / GLIMS via NSIDC',
            'source_features':len(raw.get('features',[])),'latest_glacier_count':len(output),
            'source_dates':sorted({f['properties'].get('src_date') for f in output if f['properties'].get('src_date')}),
            'glacier_names':sorted({f['properties'].get('glac_name') for f in output if f['properties'].get('glac_name')}),
            'aoi_bbox':bbox,'selection_rule':'latest available okay glacial boundary per glacier ID, source year >=1980; reconstructed older outlines retained only in raw source',
            'citation':'GLIMS Glacier Database, Version 1; GLIMS/NSIDC. Per-feature submitter, analysis ID, source date and analyst affiliation retained.',
            'limitation':'Latest source date varies by glacier and may be historical. IDs can represent different delineations; union masks avoid double-counting overlapping outlines. No automatic feeding-glacier identity is certified.'}

def tile_name(lon,lat):
    west=math.floor(lon/10)*10;north=math.ceil(lat/10)*10
    return f'{abs(west)}{"E" if west>=0 else "W"}_{abs(north)}{"N" if north>=0 else "S"}'

def jrc_crop(site,folder,observed,month=None):
    tile=tile_name(site['lake_lon'],site['lake_lat'])
    if month:
        relative=f'download2024/monthlyhistory/VER1-5/2023/2023_{month:02d}/monthlyhistory_{tile}_v1_5_2023_{month:02d}.tif'
        filename=f'jrc_monthly_2023_{month:02d}.tif'
    else:
        relative=f'download2024/Aggregated/VER1-5/occurrence/occurrence_{tile}_v1_5_2024.tif'
        filename='jrc_occurrence.tif'
    url=JRC+relative;path=folder/filename
    with rasterio.open(observed/site['site_id']/'dem_lake.tif') as template:profile=template.profile.copy()
    profile.update(dtype='uint8',nodata=255,count=1,predictor=1)
    if not path.exists():
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',GDAL_HTTP_TIMEOUT='60',GDAL_HTTP_MAX_RETRY='2'):
            with rasterio.open('/vsicurl/'+url) as src:
                source_profile={'crs':str(src.crs),'pixel_size':list(src.res),'nodata':src.nodata,'width':src.width,'height':src.height}
                with WarpedVRT(src,crs=profile['crs'],transform=profile['transform'],width=profile['width'],height=profile['height'],src_nodata=255,nodata=255,dtype='uint8',resampling=Resampling.nearest) as vrt:array=vrt.read(1)
        with rasterio.open(path,'w',**profile) as dst:
            dst.write(array,1);dst.set_band_description(1,'JRC_monthly_water_class' if month else 'JRC_water_occurrence_percent_1984_2024')
            dst.update_tags(source=url,source_group='European Commission JRC / Google',native_resolution='30 m',resampling='nearest to existing 20m AOI',historical_context='true')
    else:
        source_profile={'native_resolution_m':30,'note':'existing bounded crop; source URL retained'}
    with rasterio.open(path) as src:array=src.read(1)
    tile_covered=array!=255
    valid=np.isin(array,[1,2]) if month else tile_covered
    if not month and np.any(valid & (array>100)):raise ValueError('Occurrence outside 0–100%; invalid v1.5 data')
    if month and np.any(tile_covered & ~np.isin(array,[0,1,2])):raise ValueError('Unexpected monthly classification code')
    return {'kind':'monthly_water_history' if month else 'historical_water_occurrence',
            'status':'downloaded' if valid.any() else 'no_valid_pixels','file':filename,'sha256':sha(path),
            'source_url':url,'source_group':'European Commission JRC / Google','version':'1.5',
            'source_resolution_m':30,'target_pixel_spacing_m':20,'source_raster':source_profile,
            'date_range':[f'2023-{month:02d}-01',f'2023-{month:02d} (monthly composite)'] if month else ['1984','2024'],
            'units':'classification: 0 no data, 1 not water, 2 water; 255 outside tile' if month else 'water occurrence percent; 255 no data',
            'valid_fraction':float(valid.mean()),'tile_coverage_fraction':float(tile_covered.mean()),
            'observation_month':f'2023-{month:02d}' if month else None,
            'classification_codes':{'0':'no observation','1':'observed not water','2':'observed water','255':'outside source tile'} if month else None,
            'pixel_value_counts':{str(int(v)):int(n) for v,n in zip(*np.unique(array,return_counts=True))},
            'documentation':'https://global-surface-water.appspot.com/download',
            'limitation':'Monthly classification is not an exact event-date shoreline.' if month else 'Aggregated historical context only; includes dates after 2023 and must not be used as pre-event prediction truth or current lake level.'}

def velocity_quality(site,folder,root):
    report=json.loads((root/'velocity'/site['site_id']/'report.json').read_text())
    records=report.get('records',[])
    if not records:return {'kind':'velocity_quality','status':'unavailable','reason':'No existing valid annual velocity crop to align with.'}
    year=max(r['year'] for r in records)
    record=next(r for r in records if r['year']==year)
    endpoint='https://stac.itslive.cloud/collections/velocity-mosaics/items/'+record['item_id']
    response=requests.get(endpoint,timeout=35);response.raise_for_status();item=response.json()
    dump(folder/'itslive_quality_source_item.json',item)
    with rasterio.open(root/'velocity'/site['site_id']/record['file']) as template:profile=template.profile.copy()
    profile.update(dtype='float32',nodata=np.nan,count=1)
    result={'kind':'velocity_quality','status':'downloaded','year':year,'item_id':record['item_id'],
            'source_group':'NASA MEaSUREs ITS_LIVE','source_url':endpoint,'files':[]}
    for kind in ['vx','vy','count','v_error']:
        asset=item['assets']['cog_'+kind];url=asset['href'];path=folder/f'velocity_{year}_{kind}.tif'
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',GDAL_HTTP_TIMEOUT='45'):
            with rasterio.open('/vsicurl/'+url) as src:
                encoding={'dtype':src.dtypes[0],'scale':src.scales[0],'offset':src.offsets[0],
                          'nodata':src.nodata,'units':src.units[0],'band_tags':src.tags(1),
                          'source_crs':str(src.crs)}
                if not path.exists():
                    with WarpedVRT(src,crs=profile['crs'],transform=profile['transform'],width=profile['width'],height=profile['height'],nodata=np.nan,dtype='float32',resampling=Resampling.nearest) as vrt:array=vrt.read(1)
                    array=array*encoding['scale']+encoding['offset']
        if not path.exists():
            if kind in ['count','v_error']:array[array<0]=np.nan
            with rasterio.open(path,'w',**profile) as dst:
                dst.write(array.astype('float32'),1);dst.set_band_description(1,kind);dst.update_tags(source=url,source_group='NASA MEaSUREs ITS_LIVE')
        with rasterio.open(path) as src:array=src.read(1)
        result['files'].append({'kind':kind,'file':path.name,'sha256':sha(path),'url':url,
                                'units':'image pair count' if kind=='count' else 'm/yr',
                                'source_encoding':encoding,
                                'finite_fraction':float(np.isfinite(array).mean())})
    result['limitation']='Annual image-pair support and velocity error do not quantify breach probability. vx/vy are source-grid components; geographic vector interpretation requires the product projection. v_error is integer-quantized; valid zero is not proof of exactly zero uncertainty. Count zero is source NoData and is excluded.'
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path('real_mvp/artifacts'));parser.add_argument('--sites',type=Path,default=Path('real_mvp/sites.json'));parser.add_argument('--only-site');args=parser.parse_args()
    out=args.root/'simplified_sources';out.mkdir(exist_ok=True)
    sites=json.loads(args.sites.read_text());sites=[s for s in sites if not args.only_site or s['site_id']==args.only_site]
    def one(site):
        folder=out/site['site_id'];folder.mkdir(exist_ok=True)
        manifest={'site_id':site['site_id'],'acquired_utc':datetime.now(timezone.utc).isoformat(),'records':[],'failures':[],'synthetic_fallback':False}
        jobs=[('GLIMS glacier outlines',lambda:glaciers(site,folder)),('JRC occurrence',lambda:jrc_crop(site,folder,args.root/'observed')),
              ('ITS_LIVE latest annual quality/vector crops',lambda:velocity_quality(site,folder,args.root))]
        if site['site_id']=='south_lhonak':
            jobs += [(f'JRC monthly 2023-{month:02d}',lambda month=month:jrc_crop(site,folder,args.root/'observed',month)) for month in [9,10]]
        for name,work in jobs:
            try:
                result=work();manifest['records'].append(result);print(site['site_id'],name,result['status'],flush=True)
            except Exception as exc:
                manifest['failures'].append({'source':name,'error_type':type(exc).__name__,'detail':str(exc)[:300]});print(site['site_id'],name,'FAILED',type(exc).__name__,flush=True)
            dump(folder/'manifest.json',manifest)
        manifest['status']='complete' if not manifest['failures'] else 'partial';dump(folder/'manifest.json',manifest)
        return manifest
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(one,sites))
    dump(out/'acquisition_summary.json',{'sites':results,'new_source_families':['GLIMS glacier outlines','JRC Global Surface Water v1.5','ITS_LIVE annual velocity vectors and quality'],'operational_warning_validation':False})

if __name__=='__main__':main()
