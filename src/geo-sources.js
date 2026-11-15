import {feature} from 'topojson-client';

/** Versioned, self-hosted map context; avoids dependence on public GitHub CDN. */
export async function loadCountriesLocal() {
  const response=await fetch('/data/world.json',{cache:'force-cache'});
  if(!response.ok)throw new Error('Local country boundaries unavailable');
  const topology=await response.json();
  const countries=feature(topology,topology.objects.countries);
  if(!Array.isArray(countries.features)||countries.features.length<100)
    throw new Error('Country outline data are incomplete');
  return countries;
}

export async function loadPlateBoundariesLocal() {
  const response=await fetch('/data/plate-boundaries.json',{cache:'force-cache'});
  if(!response.ok)throw new Error('Local plate-boundary data unavailable');
  const data=await response.json();
  if(data.type!=='MultiLineString'||!Array.isArray(data.coordinates)||!data.coordinates.length)
    throw new Error('Tectonic plate data are invalid');
  return data;
}
