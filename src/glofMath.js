import {geoEqualEarth, geoPath} from 'd3-geo';

const projection = geoEqualEarth().scale(108).translate([300,153]);
// Spherical path streaming clips the antimeridian before projection.
export const worldPath = geoPath(projection);

// Keep missing observations as gaps; never turn null into zero water.
export function lakeSegments(series, width = 600, height = 110) {
  const valid = series.filter(r => Number.isFinite(r.lake_area_km2));
  const max = Math.max(0.01, ...valid.map(r => r.lake_area_km2));
  const segments = [];
  let current = [];
  const first = Date.parse(series[0]?.date);
  const span = Math.max(1, Date.parse(series.at(-1)?.date) - first);
  series.forEach(r => {
    if (!Number.isFinite(r.lake_area_km2)) {
      if (current.length) segments.push(current);
      current = [];
      return;
    }
    current.push([8 + (Date.parse(r.date) - first) / span * (width - 16),
      height - 8 - r.lake_area_km2 / max * (height - 16)]);
  });
  if (current.length) segments.push(current);
  return { segments, max };
}

export function equalEarth([lon, lat]) {
  return projection([lon, lat]);
}

export function initialEpoch(summary) {
  const series = summary.lake.series;
  const showcase = summary.site.site_id === 'south_lhonak'
    ? series.findIndex(r => r.date === '2023-10-07') : -1;
  return showcase >= 0 ? showcase : Math.max(0, series.length - 1);
}
