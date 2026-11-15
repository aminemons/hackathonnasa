import {geoEqualEarth,geoPath,geoGraticule10,geoCentroid,geoArea} from 'd3-geo';
import {loadCountriesLocal} from './geo-sources.js';

/** Global equal-area atlas. Regional raster imagery keeps its native web-map CRS. */
export async function initializeEqualEarthAtlas(TP) {
  const NS='http://www.w3.org/2000/svg';
  const make=(tag,attrs={})=>{const e=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);return e};
  const root=document.createElement('section');root.id='equal-earth-atlas';
  root.setAttribute('aria-label','Equal Earth global change atlas');
  root.innerHTML='<div class="atlas-heading"><span class="section-meta">Global change atlas</span><h2>Earth in motion</h2><p>Choose evidence in Dataset. Select a feature to inspect it on the regional map.</p></div>';
  const svg=make('svg',{viewBox:'0 0 1000 560',role:'img','aria-label':'World map in the Equal Earth equal-area projection'});
  const projection=geoEqualEarth().fitExtent([[28,30],[972,530]],{type:'Sphere'}),path=geoPath(projection);
  svg.append(make('path',{d:path({type:'Sphere'}),class:'atlas-ocean'}));
  svg.append(make('path',{d:path(geoGraticule10()),class:'atlas-graticule'}));
  const land=make('g',{class:'atlas-land'}),evidence=make('g',{class:'atlas-evidence'});
  svg.append(land,evidence);root.append(svg);
  const caption=document.createElement('p');caption.className='atlas-caption';root.append(caption);
  document.querySelector('.mw').prepend(root);
  const switcher=document.createElement('div');switcher.className='projection-switch';switcher.setAttribute('role','group');switcher.setAttribute('aria-label','Map projection');
  switcher.innerHTML='<button type="button" id="global-view" aria-pressed="true">Equal Earth</button><button type="button" id="regional-view" aria-pressed="false">Regional detail</button>';
  document.querySelector('.mw').append(switcher);
  let global=true,queued=false;
  function mode(value) {
    global=value;root.hidden=!value;
    document.querySelector('#global-view').setAttribute('aria-pressed',String(value));
    document.querySelector('#regional-view').setAttribute('aria-pressed',String(!value));
    document.querySelector('.mw').classList.toggle('global-atlas',value);
    if(!value)TP.map.invalidateSize();else schedule();
  }
  TP.showRegional=()=>mode(false);
  document.querySelector('#global-view').onclick=()=>mode(true);
  document.querySelector('#regional-view').onclick=()=>mode(false);
  document.querySelector('#bmList').addEventListener('click',()=>mode(false));
  function inspect(layer,feature) {
    mode(false);TP.go('Map');
    const p=layer.getLatLng?.();
    if(p)TP.map.setView(p,7);
    else if(layer.getBounds?.().isValid())TP.map.fitBounds(layer.getBounds(),{maxZoom:7});
    else if(feature){const c=geoCentroid(feature);TP.map.setView([c[1],c[0]],5)}
    layer.openPopup?.();
  }
  function interactive(el,action,label) {
    el.setAttribute('tabindex','0');el.setAttribute('role','button');el.setAttribute('aria-label',label);
    el.addEventListener('click',action);el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();action()}});
    const title=make('title');title.textContent=label;el.append(title);
  }
  try {
    const countries=await loadCountriesLocal();
    for(const feature of countries.features) {
      const el=make('path',{d:path(feature)});const name=feature.properties?.name||'Country';
      interactive(el,()=>{const c=geoCentroid(feature);mode(false);TP.map.setView([c[1],c[0]],5)},'Inspect '+name);
      land.append(el);
    }
  }catch{caption.textContent='Country boundaries unavailable · evidence layers remain selectable'}
  function render() {
    queued=false;if(!global)return;evidence.replaceChildren();
    let count=0,rasters=0;
    const active=TP.DS.filter(d=>TP.state[d.id]?.on);
    for(const d of active) {
      const parent=TP.state[d.id].layer;if(!parent)continue;
      function draw(layer) {
        if(layer.eachLayer){layer.eachLayer(draw);return}
        let el;const location=layer.getLatLng?.();
        const color=layer.options?.fillColor||layer.options?.color||d.leg?.[0]||'#bb593b';
        if(location){
          const p=projection([location.lng,location.lat]);if(!p)return;
          el=make('circle',{cx:p[0],cy:p[1],r:Math.min(7,Math.max(3,(layer.options?.radius||5)/2)),fill:color,stroke:'#fff','stroke-width':1});
        }else if(layer.toGeoJSON){
          let feature=layer.toGeoJSON();
          // D3 spherical polygons use the smaller clockwise ring; Leaflet accepts either winding.
          if(feature.geometry?.type==='Polygon'&&geoArea(feature)>2*Math.PI)feature={...feature,geometry:{...feature.geometry,coordinates:feature.geometry.coordinates.map(r=>[...r].reverse())}};
          if(feature.geometry?.type==='MultiPolygon')feature={...feature,geometry:{...feature.geometry,coordinates:feature.geometry.coordinates.map(c=>geoArea({type:'Polygon',coordinates:c})>2*Math.PI?c.map(r=>[...r].reverse()):c)}};
          const p=path(feature);if(!p)return;
          el=make('path',{d:p,fill:layer.options?.fill===false?'none':color,'fill-opacity':.25,stroke:color,'stroke-width':1});
        }else{rasters++;return}
        const popup=layer.getPopup?.()?.getContent();
        const text=document.createElement('div');if(typeof popup==='string')text.innerHTML=popup;
        const label=text.textContent?.trim()||d.n;
        interactive(el,()=>inspect(layer),label+' · open regional detail');evidence.append(el);count++;
      }
      draw(parent);
    }
    caption.textContent=`Equal Earth · equal-area projection · Natural Earth boundaries · ${count.toLocaleString()} mapped features${rasters?' · Raster imagery available in Regional detail':''}`;
    if(!count&&active.some(d=>TP.state[d.id].status==='loading'))caption.textContent+=' · Loading selected evidence…';
  }
  function schedule(){if(!queued){queued=true;requestAnimationFrame(render)}}
  TP.map.on('layeradd layerremove',schedule);
  new MutationObserver(schedule).observe(document.querySelector('#ds'),{childList:true,subtree:true});
  mode(true);render();
}
