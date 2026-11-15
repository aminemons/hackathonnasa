"""Offline tests for provider coverage, failover, budgets and honest caching."""
import json
from io import BytesIO
from pathlib import Path
import sys
import time
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from api import exposure


class Response:
    status = 200
    def __init__(self, value):
        self.stream = BytesIO(value if isinstance(value,bytes) else json.dumps(value).encode())
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,size): return self.stream.read(size)


def payload(elements=None):
    return {'elements':elements or [],'osm3s':{'timestamp_osm_base':'2026-11-14T21:20:41Z'}}


class OSMResilienceTests(unittest.TestCase):
    def setUp(self):
        exposure._cache.clear()
        exposure._query_times.clear()
        exposure._retry_at.clear()

    def test_regional_providers_only_cover_their_actual_extract(self):
        with patch.object(exposure,'OVERPASS',None):
            self.assertEqual(exposure.providers(-134.419,58.302,500)[0][2], 'north-america')
            self.assertEqual(exposure.providers(2.35,48.85,500)[0][2], 'europe')
            for lon,lat in [(3.0585,36.773),(88.195,27.91),(-77.379,-9.397)]:
                self.assertTrue(all(p[2]=='global' for p in exposure.providers(lon,lat,500)))

    def test_full_search_footprint_must_fit_within_coverage(self):
        region={'rings':[{'hole':False,'coordinates':[[0,0],[1,0],[1,1],[0,1],[0,0]]}]}
        self.assertTrue(exposure._covered(region,.5,.5,600))
        self.assertFalse(exposure._covered(region,.999,.5,600))

    def test_configured_provider_is_exclusive_and_requires_https(self):
        with patch.object(exposure,'OVERPASS','https://custom.example/api/interpreter'):
            self.assertEqual(len(exposure.providers(3,36,500)),1)
        for url in ['http://custom.example/api','https://user:password@custom.example/api']:
            with self.subTest(url=url),patch.object(exposure,'OVERPASS',url),self.assertRaises(ValueError):
                exposure.providers(3,36,500)

    def test_timeout_falls_back_once_to_the_next_provider(self):
        choices=[('First','https://one.example/api','global'),('Second','https://two.example/api','global')]
        with patch.object(exposure,'providers',return_value=choices),patch.object(exposure,'urlopen',side_effect=[TimeoutError(),Response(payload())]) as call:
            data=exposure.load_osm(3.0585,36.773,500)
        self.assertEqual(call.call_count,2)
        self.assertEqual(data['provider'],'Second')
        self.assertEqual(data['mode'],'upstream')
        self.assertLessEqual(call.call_args.kwargs['timeout'],exposure.ATTEMPT_SECONDS)
        self.assertEqual(call.call_args.args[0].get_method(),'GET')

    def test_partial_json_response_never_becomes_zero_assets(self):
        choices=[('First','https://one.example/api','global'),('Second','https://two.example/api','global')]
        partial={**payload(),'remark':'runtime error: Query timed out'}
        with patch.object(exposure,'providers',return_value=choices),patch.object(exposure,'urlopen',side_effect=[Response(partial),Response(payload())]):
            self.assertEqual(exposure.load_osm(3,36,500)['provider'],'Second')

    def test_rate_limit_stops_without_hopping_to_another_host(self):
        choices=[('First','https://one.example/api','global'),('Second','https://two.example/api','global')]
        error=HTTPError('https://one.example/api',429,'Rate limited',{},None)
        with patch.object(exposure,'providers',return_value=choices),patch.object(exposure,'urlopen',side_effect=error) as call:
            with self.assertRaises(exposure.SourceUnavailable):exposure.load_osm(3,36,500)
        self.assertEqual(call.call_count,1)

    def test_all_failed_providers_stay_unavailable_with_no_counts(self):
        with patch.object(exposure,'urlopen',side_effect=TimeoutError()):
            with self.assertRaises(exposure.SourceUnavailable) as error:
                exposure.load_osm(3,36,500)
        self.assertTrue(error.exception.attempts)
        self.assertNotIn((3,36,500),exposure._cache)

    def test_recent_success_is_reused_without_network(self):
        key=(3.0,36.0,500)
        source={'elements':[],'osm_timestamp':'2026-11-14T21:20:41Z','provider':'Test',
                'retrieved_at':'2026-11-15T00:00:00Z','mode':'upstream'}
        exposure._cache[key]=(time.monotonic(),source)
        with patch.object(exposure,'urlopen') as call:
            self.assertEqual(exposure.load_osm(3,36,500)['mode'],'memory_cache')
        call.assert_not_called()

    def test_cache_fallback_is_explicit_and_does_not_extend_retention(self):
        key=(3.0,36.0,500)
        source={'elements':[],'osm_timestamp':'2026-11-14T21:20:41Z','provider':'Test',
                'retrieved_at':'2026-11-15T00:00:00Z','mode':'upstream'}
        exposure._cache[key]=(time.monotonic()-exposure.FRESH_SECONDS-10,source)
        with patch.object(exposure,'urlopen',side_effect=TimeoutError()):
            data=exposure.load_osm(3,36,500)
        self.assertEqual(data['mode'],'cached_fallback')
        self.assertEqual(data['retrieved_at'],source['retrieved_at'])
        exposure._cache[key]=(time.monotonic()-exposure.MAX_CACHE_AGE_SECONDS-1,source)
        with self.assertRaises(exposure.SourceUnavailable):exposure.load_osm(3,36,500)

    def test_response_size_and_source_timestamp_are_required(self):
        for body in [b'x'*(exposure.MAX_BODY+1),{'elements':[]}]:
            with self.subTest(size=type(body).__name__),patch.object(exposure,'urlopen',return_value=Response(body)),self.assertRaises(OSError):
                exposure._fetch('https://one.example/api','q',time.monotonic()+10)

    def test_exhausted_budget_does_not_start_another_request(self):
        with patch.object(exposure,'urlopen') as call,self.assertRaises(TimeoutError):
            exposure._fetch('https://one.example/api','q',time.monotonic()-1)
        call.assert_not_called()


if __name__=='__main__':unittest.main()
