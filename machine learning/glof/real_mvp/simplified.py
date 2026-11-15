"""Execute the three-indicator GLOF monitoring MVP on acquired observations.

Lake area, glacier-masked annual speed, and partial glacier surface-volume
change remain distinct measurements with their own dates and quality limits.
There is no calibrated breach probability or inferred water-level measurement.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.features import rasterize
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom, Resampling
from scipy import ndimage
from shapely.geometry import shape, mapping, Point
from shapely.ops import unary_union, transform as geom_transform


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False))


def choose_glacier(features, lon, lat):
    """Prefer substantial nearby named glaciers; keep association provisional."""
    projector=Transformer.from_crs('EPSG:4326',f'EPSG:{32600+int((lon+180)//6)+1 if lat>=0 else 32700+int((lon+180)//6)+1}',always_xy=True).transform
    point=geom_transform(projector,Point(lon,lat))
    candidates=[]
    for feature in features:
        props=feature.get('properties',{})
        if props.get('line_type')=='intrnl_rock':continue
        try:
            geometry=shape(feature['geometry'])
            if geometry.is_empty or geometry.geom_type not in ('Polygon','MultiPolygon'):continue
            projected=geom_transform(projector,geometry)
            distance=projected.distance(point);name=str(props.get('glac_name') or '').strip()
            substantial=projected.area>=1e6 and distance<=2000
            rank=0 if substantial and name.lower() not in ('','none','null') else 1 if substantial else 2
            candidates.append((rank,distance,-projected.area,feature))
        except (ValueError,TypeError):continue
    if not candidates:return None
    _,distance,_,feature=min(candidates,key=lambda v:v[:3])
    return feature if distance<=5000 else None


def mask_geometry(geometry, profile):
    g=transform_geom('EPSG:4326',profile['crs'],geometry)
    return rasterize([(g,1)],out_shape=(profile['height'],profile['width']),transform=profile['transform'],fill=0).astype(bool)


def monthly_water_indicator(root,sid,out):
    """Calendar-month classifications are separate from dated SAR acquisitions."""
    rows=[]
    inventory=read(root/'supplementary/india/south_lhonak_nrsc_inventory.geojson',{}) if sid=='south_lhonak' else {}
    if not inventory.get('features'):return rows
    outline=inventory['features'][0]['geometry']
    for path in sorted((root/'simplified_sources'/sid).glob('jrc_monthly_*.tif')):
        with rasterio.open(path) as src:
            a=src.read(1);profile=src.profile
        historical=mask_geometry(outline,profile)
        roi=ndimage.binary_dilation(historical,iterations=40)
        observed=np.isin(a,[1,2]);water=(a==2)&roi
        labels,n=ndimage.label(water)
        scores=np.bincount(labels[historical].ravel(),minlength=n+1);scores[0]=0
        selected=int(np.argmax(scores)) if scores.sum() else 0
        component=(labels==selected) if selected else np.zeros_like(water)
        coverage=float(observed[historical].mean())
        area=float(component.sum()*abs(profile['transform'].a*profile['transform'].e)/1e6) if component.any() else None
        month=path.stem.removeprefix('jrc_monthly_').replace('_','-')
        row={'month':month,'mapped_connected_water_area_km2':area,
             'observed_fraction_of_2016_lake':coverage,
             'status':'mapped_component' if area is not None and coverage>=.8 else 'incomplete_observation',
             'source_group':'EC JRC / Google','source_native_resolution_m':30,
             'interpretation':'Calendar-month optical water classification; class 0 has no observation. October 2023 may mix observations before and after the outburst. No lake-level or breach-probability inference.'}
        rows.append(row)
    return rows


def velocity_indicator(root, sid, feature, out):
    result={'status':'unavailable','confidence':'unavailable','value_m_yr':None,
            'source_group':'NASA MEaSUREs / ITS_LIVE','units':'m/year',
            'interpretation':'Annual movement of the mapped glacier candidate within the downloaded AOI, not a short-term surge forecast.',
            'series':[]}
    if feature is None:
        result['reason']='No usable glacier outline acquired; surrounding terrain is not substituted for glacier speed.';return result
    report=read(root/'velocity'/sid/'report.json',{})
    mask=None
    for record in sorted(report.get('records',[]),key=lambda r:r['year']):
        path=root/'velocity'/sid/record['file']
        if not path.exists():continue
        with rasterio.open(path) as src:
            ar=src.read(1,masked=True).filled(np.nan)
            current_mask=mask_geometry(feature['geometry'],src.profile)
            valid=current_mask & np.isfinite(ar) & (ar>=0) & (ar<30000)
            total=int(current_mask.sum())
            if not valid.any():continue
            result['series'].append({'year':record['year'],'median_m_yr':float(np.median(ar[valid])),
                'valid_glacier_pixels':int(valid.sum()),'outline_pixels_in_aoi':total,
                'valid_fraction_of_outline_in_aoi':float(valid.sum()/total) if total else 0,
                'source_item_id':record['item_id']})
            latest_ar,latest_valid,mask,profile=ar,valid,current_mask,src.profile
    if not result['series']:
        result['reason']='No finite glacier pixels in available velocity crops.';return result
    last=result['series'][-1]
    baseline=[r['median_m_yr'] for r in result['series'] if r['year']<=2022 and r['valid_glacier_pixels']>=3 and r['valid_fraction_of_outline_in_aoi']>=.5]
    base=float(np.median(baseline)) if len(baseline)>=3 else None
    result.update(status='annual_glacier_context',confidence='limited',value_m_yr=last['median_m_yr'],
        latest_year=last['year'],baseline_median_m_yr=base,baseline_years=len(baseline),
        latest_to_historical_ratio=last['median_m_yr']/base if base is not None and base>5 else None,
        valid_fraction_of_outline_in_aoi=last['valid_fraction_of_outline_in_aoi'],
        baseline_rule='Median of glacier-mask annual medians through 2022; at least three years; ratio withheld when baseline <=5m/yr.',
        caveat='Outline may predate observations. AOI clips the glacier. Per-pixel velocity uncertainty is not fully propagated; confidence is a heuristic evidence grade.')
    quality={}
    for kind in ['count','v_error']:
        path=root/'simplified_sources'/sid/f"velocity_{last['year']}_{kind}.tif"
        if path.exists():
            with rasterio.open(path) as src:
                with WarpedVRT(src,crs=profile['crs'],transform=profile['transform'],width=profile['width'],height=profile['height'],nodata=np.nan,dtype='float32',resampling=Resampling.nearest) as vrt:q=vrt.read(1,masked=True).filled(np.nan)
            valid=latest_valid & np.isfinite(q)
            if valid.any():quality[kind]={'median':float(np.median(q[valid])),'pixels':int(valid.sum())}
    if quality:
        result['latest_source_quality']=quality
        result['quality_note']='Count is annual image-pair support; v_error is integer-quantized m/year, so zero is not exact zero uncertainty. These diagnostics are not a confidence interval on the mask median.'
        if quality.get('v_error',{}).get('median',0)>last['median_m_yr']:result['confidence']='low'
    fig,axes=plt.subplots(1,2,figsize=(10,3.5),constrained_layout=True)
    im=axes[0].imshow(np.ma.masked_where(~mask,latest_ar),cmap='viridis',vmin=0,vmax=max(5,float(np.nanpercentile(latest_ar[latest_valid],95))))
    axes[0].set_title(f"Mapped glacier candidate · {last['year']}");axes[0].set_axis_off();fig.colorbar(im,ax=axes[0],label='m/year')
    axes[1].plot([r['year'] for r in result['series']],[r['median_m_yr'] for r in result['series']],color='#2c765f')
    axes[1].set(xlabel='Year',ylabel='Glacier-mask median speed (m/year)',title='Annual movement context')
    fig.savefig(out/'velocity.png',dpi=140,bbox_inches='tight');plt.close(fig)
    return result


def surface_change(before, after, glacier_mask, stable_mask, pixel_area, years):
    """Difference co-dated grids on common valid support; no gap extrapolation."""
    common=np.isfinite(before)&np.isfinite(after)
    raw=after-before
    stable=stable_mask&common&(np.abs(raw)<50)
    if stable.sum()<500:
        return {'status':'insufficient_stable_ground','partial_surface_volume_change_m3':None,
                'reason':'Fewer than 500 screened stable-ground pixels for residual vertical-bias assessment.'},None
    bias=float(np.median(raw[stable]));nmad=float(1.4826*np.median(np.abs(raw[stable]-bias)))
    valid=glacier_mask&common
    if valid.sum()<100:
        return {'status':'insufficient_glacier_coverage','partial_surface_volume_change_m3':None,
                'reason':'Fewer than 100 common valid glacier pixels.'},None
    corrected=raw-bias
    # A fixed screen is disclosed, not used to replace missing terrain or smooth extremes.
    result={'status':'partial_glacier_surface_change','mean_dh_m':float(np.mean(corrected[valid])),
            'median_dh_m':float(np.median(corrected[valid])),
            'mean_dh_dt_m_yr':float(np.mean(corrected[valid])/years),
            'partial_surface_volume_change_m3':float(np.sum(corrected[valid])*pixel_area),
            'observed_glacier_footprint_km2':float(valid.sum()*pixel_area/1e6),
            'common_valid_fraction_of_mask_in_grid':float(valid.sum()/max(1,glacier_mask.sum())),
            'stable_ground_bias_m':bias,'stable_ground_nmad_m':nmad,
            'stable_ground_pixels':int(stable.sum()),'glacier_pixels':int(valid.sum()),
            'years':years,'vertical_change_resolved_above_stable_scatter':bool(abs(np.mean(corrected[valid]))>nmad),
            'uncertainty_interpretation':'Stable-ground NMAD is a diagnostic scatter estimate, not a volume confidence interval. Spatial correlation and snow-season differences remain.'}
    return result,np.where(valid,corrected,np.nan).astype('float32')


def elevation_indicator(root,sid,feature,all_features,out):
    result={'status':'unavailable','confidence':'unavailable','partial_surface_volume_change_m3':None,
            'source_group':'Research / CNES-derived Pleiades','units':'m and m3',
            'interpretation':'Partial surface-volume change over a historical glacier outline on common valid terrain, not total glacier volume or lake water volume.'}
    if sid!='south_lhonak' or feature is None:
        result['reason']='No matched high-resolution repeat DEMs with a usable glacier outline for this site.';return result
    folder=root/'supplementary/lake_4m_crops'
    pre=folder/'13124662_20221018_lake4m.tif';post=folder/'13124662_20231029_lake4m.tif'
    if not pre.exists() or not post.exists():
        result['reason']='Repeat research DEM crops unavailable.';return result
    with rasterio.open(pre) as src:
        before=src.read(1,masked=True).filled(np.nan);profile=src.profile
    with rasterio.open(post) as src:
        with WarpedVRT(src,crs=profile['crs'],transform=profile['transform'],width=profile['width'],height=profile['height'],nodata=np.nan,dtype='float32',resampling=Resampling.bilinear) as vrt:
            after=vrt.read(1,masked=True).filled(np.nan)
    glacier=mask_geometry(feature['geometry'],profile)
    all_ice=np.zeros_like(glacier)
    for f in all_features:
        try:all_ice|=mask_geometry(f['geometry'],profile)
        except (ValueError,TypeError):continue
    # Exclude mapped historical lake and its near-shore fringe from glacier integration.
    lake=np.zeros_like(glacier)
    inv=read(root/'supplementary/india/south_lhonak_nrsc_inventory.geojson',{})
    for f in inv.get('features',[]):lake|=mask_geometry(f['geometry'],profile)
    for metadata in (root/'observed'/sid).glob('optical_*.npz'):
        # Existing optical water is a conservative exclusion, not a DEM-derived level.
        with np.load(metadata) as z:water=z['label']==1
        with rasterio.open(root/'observed'/sid/'dem_lake.tif') as src:
            from rasterio.warp import reproject
            dst=np.zeros(glacier.shape,'uint8')
            reproject(water.astype('uint8'),dst,src_transform=src.transform,src_crs=src.crs,
                      dst_transform=profile['transform'],dst_crs=profile['crs'],resampling=Resampling.nearest)
            lake|=dst.astype(bool)
    glacier &= ~ndimage.binary_dilation(lake,iterations=8)
    glacier=ndimage.binary_erosion(glacier,iterations=2)
    # Conservative background only; lack of moving-ground truth is disclosed.
    stable=~ndimage.binary_dilation(all_ice|lake,iterations=50)
    filled=np.where(np.isfinite(before),before,np.nanmedian(before))
    dy,dx=np.gradient(filled,abs(profile['transform'].e),abs(profile['transform'].a))
    slope=np.rad2deg(np.arctan(np.hypot(dx,dy)))
    stable &= (slope>5)&(slope<30)
    years=(date(2023,10,29)-date(2022,10,18)).days/365.25
    computed,dh=surface_change(before,after,glacier,stable,abs(profile['transform'].a*profile['transform'].e),years)
    result.update(computed,start_date='2022-10-18',end_date='2023-10-29',confidence='limited',
                  glacier_mask_note='Historical outline candidate; mapped water buffered 32m and glacier edge eroded 8m.',
                  stable_mask_note='Outside acquired glacier/lake outlines with 200m exclusion, 5–30deg slopes and abs(raw dh)<50m.',
                  caveat='Publisher DEMs are coregistered, but glacier boundaries, seasonal snow, stable-ground assumptions and missing coverage limit interpretation. No whole-glacier extrapolation or mass-density conversion.')
    full_area=shape(transform_geom('EPSG:4326',profile['crs'],feature['geometry'])).area
    result['full_historical_outline_area_km2']=float(full_area/1e6)
    result['fraction_of_full_historical_glacier_observed']=float(result.get('observed_glacier_footprint_km2',0)/(full_area/1e6)) if full_area else None
    if dh is None:return result
    path=out/'glacier_surface_change_m.tif'
    with rasterio.open(path,'w',**profile) as dst:dst.write(dh,1);dst.set_band_description(1,'partial_glacier_surface_elevation_change_m')
    result['raster_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    fig,ax=plt.subplots(figsize=(6,4),constrained_layout=True)
    im=ax.imshow(np.ma.masked_invalid(dh),cmap='RdBu',vmin=-20,vmax=20)
    ax.set_title('Glacier candidate surface change\n2022-10-18 → 2023-10-29 · partial footprint')
    ax.set_axis_off();fig.colorbar(im,ax=ax,label='After − before, residual-bias corrected (m)')
    fig.savefig(out/'elevation.png',dpi=140,bbox_inches='tight');plt.close(fig)
    return result


def run_site(root,site):
    sid=site['site_id'];out=root/'simplified'/sid;out.mkdir(parents=True,exist_ok=True)
    observed=read(root/'observed'/sid/'observed_summary.json',{})
    sources=read(root/'simplified_sources'/sid/'manifest.json',{})
    outlines=read(root/'simplified_sources'/sid/'glaciers.geojson',{'features':[]})
    features=outlines.get('features',[])
    feature=choose_glacier(features,site['lake_lon'],site['lake_lat'])
    context=[]
    if feature:
        context.append({**feature,'properties':{**feature.get('properties',{}),'layer':'feeding_glacier_zone',
                          'interpretation':'Spatially selected mapped glacier candidate; hydrological connection not verified'}})
    inv=read(root/'supplementary/india/south_lhonak_nrsc_inventory.geojson',{}) if sid=='south_lhonak' else {}
    for f in inv.get('features',[]):context.append({**f,'properties':{**f['properties'],'layer':'historical_lake_inventory'}})
    write(out/'context.geojson',{'type':'FeatureCollection','features':context})
    movement=velocity_indicator(root,sid,feature,out)
    elevation=elevation_indicator(root,sid,feature,features,out)
    audit=read(root/'supplementary/shoreline_review/shoreline_audit.json',{}) if sid=='south_lhonak' else {}
    checks=[{'sar_date':c['sar_date'],'optical_datetime':c['optical_datetime'],'date_gap_days':c['date_gap_days'],**c['metrics']} for c in audit.get('cases',[])]
    if not checks:
        checks=[{'sar_date':c['date'],'optical_datetime':c['reference']['optical_datetime'],
                 'date_gap_days':c['reference']['date_gap_days'],**c['metrics']['ml'],
                 'scope':'Raw pixel classifier diagnostic; final connected component not separately audited for this lake.'} for c in observed.get('optical_validation',[])]
    lake={'status':'modelled_area_observations','confidence':observed.get('evidence',{}).get('confidence','limited'),
          'source_group':'ESA / Copernicus Sentinel-1','units':'km2','water_level_m':None,'lake_volume_m3':None,
          'water_level_status':'not_measured','volume_status':'not_measured',
          'series':observed.get('timeseries',[]),'independent_checks':checks,
          'independent_monthly_water':monthly_water_indicator(root,sid,out),
          'area_drop_candidates':observed.get('area_drop_candidates',[]),
          'interpretation':'Mapped area only. Missing water under snow/ice and ambiguous shorelines remain unresolved; changes are review candidates.'}
    available_count=int(bool(lake['series']))+int(movement.get('value_m_yr') is not None)+int(elevation.get('mean_dh_m') is not None)
    dates=[r['date'] for r in lake['series']]
    groups=[{'provider':'NASA MEaSUREs','product':'ITS_LIVE annual glacier velocity','status':movement['status'],'url':'https://its-live.jpl.nasa.gov/'},
            {'provider':'GLIMS / NSIDC and contributing analysts','product':'Dated glacier outlines','status':'acquired' if features else 'unavailable','url':'https://www.glims.org/'},
            {'provider':'EC JRC / Google','product':'Global Surface Water occurrence v1.5','status':'acquired' if (root/'simplified_sources'/sid/'jrc_occurrence.tif').exists() else 'unavailable','url':'https://global-surface-water.appspot.com/download'},
            {'provider':'Research / CNES-derived Pleiades','product':'Repeat terrain and partial glacier surface change','status':elevation['status'],'url':'https://zenodo.org/records/13124662'}]
    if sid=='south_lhonak':groups.append({'provider':'India / NRSC / ISRO','product':'Resourcesat-2 historical lake inventory','status':'acquired','url':'https://bhuvan.nrsc.gov.in/nhp/webgis-glacials/map'})
    groups.append({'provider':'Joint NASA–ISRO mission / NASA ASF access','product':'NISAR L-band radiometric comparison','status':observed.get('nisar',{}).get('status','unavailable'),'url':'https://nisar-docs.asf.alaska.edu/'})
    groups.append({'provider':'India / ISRO Bhoonidhi','product':'NISAR S-band','status':'not_ingested','url':'https://bhoonidhi.nrsc.gov.in/NISAR/'})
    result={'schema_version':'1.0','generated_utc':datetime.now(timezone.utc).isoformat(),'site':site,
            'title':'Three-indicator GLOF change observatory','assessment':'observations_for_review',
            'assessment_explanation':'Inspect lake area, annual glacier movement and dated surface change together. Each indicator has separate dates and evidence limits.',
            'confidence':'insufficient' if available_count<=1 and lake['confidence']=='unassessed' else 'limited',
            'available_indicators':available_count,'confidence_kind':'qualitative evidence grade; not a calibrated event probability',
            'lake':lake,'movement':movement,'elevation':elevation,
            'glacier_candidate':feature.get('properties') if feature else None,
            'glacier_attribution':'Spatial candidate selection prefers a named glacier >=1km² within 2km, then a substantial nearby outline, then nearest within 5km. Hydrological linkage is unverified. Statistics use only downloaded grid intersections.',
            'sources':groups,'source_acquisition':sources,'observation_date_range':[min(dates),max(dates)] if dates else [],
            'operational_warning_ready':False,'breach_probability':None,
            'water_level_measured':False,'whole_glacier_volume_measured':False,
            'context_layers':'context.geojson'}
    write(out/'summary.json',result)
    print(sid,'lake epochs',len(lake['series']),'movement',movement['status'],'elevation',elevation['status'],flush=True)
    return {'site_id':sid,'lake_epochs':len(lake['series']),'movement_status':movement['status'],'elevation_status':elevation['status']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--sites',type=Path,default=Path(__file__).with_name('sites.json'))
    args=parser.parse_args()
    rows=[run_site(args.root,site) for site in read(args.sites,[])]
    write(args.root/'simplified/run_manifest.json',{'status':'complete','sites':rows,
            'scope':'Research monitoring execution; unavailable indicators remain null; no breach forecast.',
            'operational_warning_ready':False})


if __name__=='__main__':main()
