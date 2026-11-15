/** Accept both ordinary JSON summaries and standards-compliant GeoJSON. */
export async function readStudy(url,signal) {
  const response=await fetch(url,{signal,cache:'default'});
  const mime=response.headers.get('content-type')||'';
  if(!response.ok || !/^application\/(?:[\w.-]+\+)?json(?:\s*;|\s*$)/i.test(mime))
    throw new Error('Static historical study evidence is unavailable ('+response.status+').');
  return response.json();
}
