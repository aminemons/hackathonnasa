"""Real Chromium smoke test of the built blue TerraPulse interface.

Mock third-party data *only inside this test*. It verifies that UI actions,
route calls, layers, Time controls and alarm states work; it does NOT claim
that an external source will be online forever. Production source availability
is additionally checked through live API smoke tests after deployment.
"""
import base64
import json
import re
from playwright.sync_api import sync_playwright, expect

PNG=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg==")
NOW=1794730000000
CATALOG={"sites":[
    {"site_id":"south_lhonak","name":"South Lhonak Lake","lon":88.195,"lat":27.91},
    {"site_id":"imja_tsho","name":"Imja Tsho","lon":86.925,"lat":27.898},
]}
def events(hazard,days):
    if hazard == "eq":
        record={"id":"usgs:example","title":"M 5.4 · Example",
          "place":"Example","magnitude":5.4,"depth_km":9.1,"time":NOW,
          "lon":86.9,"lat":27.9,"level":"notable",
          "notes":"USGS PAGER yellow","url":"https://earthquake.usgs.gov/"}
        return {"hazard":"eq","status":"ok","records":[record]}
    return {"hazard":hazard,"status":"ok","records":[]}

def site_detail(site):
    return {"site":{"site_id":site}, "movement":{
        "series":[{"year":2023,"median_m_yr":15.0,"valid_glacier_pixels":120},
                  {"year":2024,"median_m_yr":14.7,"valid_glacier_pixels":123}],
        "status":"annual_glacier_context"
    }}

def main():
    with sync_playwright() as w:
        browser=w.chromium.launch(headless=True,args=["--no-sandbox"])
        page=browser.new_page(viewport={"width":1440,"height":900})
        errors=[]
        page.on("pageerror",lambda error:errors.append(str(error)))
        def interceptor(route):
            url=route.request.url
            if "/api/events" in url:
                from urllib.parse import urlsplit,parse_qs
                q=parse_qs(urlsplit(url).query)
                payload=events(q.get("hazard",[""])[0],q.get("days",["1"])[0])
                return route.fulfill(status=200,content_type="application/json",body=json.dumps(payload))
            if "/api/glof" in url:
                from urllib.parse import urlsplit,parse_qs
                q=parse_qs(urlsplit(url).query)
                payload=site_detail(q["site"][0]) if "site" in q else CATALOG
                return route.fulfill(status=200,content_type="application/json",body=json.dumps(payload))
            if "server.arcgisonline.com" in url or "gibs.earthdata.nasa.gov" in url:
                return route.fulfill(status=200,content_type="image/png",body=PNG)
            return route.continue_()
        page.route("**/*",interceptor)
        page.goto("http://127.0.0.1:4173",wait_until="domcontentloaded",timeout=30000)
        expect(page.locator("#tabs button[data-t='Time']")).to_be_visible()
        # User-requested removals: both real map menu and Time section.
        assert page.locator("#ds label:has-text('Global landslide catalog')").count()==0
        assert page.locator("#ds label:has-text('Snow cover')").count()==0
        assert page.locator("#tTime [data-t='glc']").count()==0
        page.locator("#tabs button[data-t='Time']").click()
        expect(page.locator("#tTime.tc.on")).to_be_visible()
        expect(page.locator("#seg button[data-d='1']")).to_be_visible(timeout=10000)
        page.locator("#seg button[data-d='1']").click()
        expect(page.locator("#seg button[data-d='1'].on")).to_be_visible()
        assert page.locator("#mag").count()==1
        page.locator("#tabs button[data-t='Dataset']").click()
        # Glacier historical annual speed: visible even if outline source is offline.
        page.locator("details:has(summary:has-text('Glaciers')) summary").first.click()
        checkbox=page.locator("#c_motion")
        expect(checkbox).to_be_visible()
        checkbox.check()
        expect(page.locator("#c_motion")).to_be_checked(timeout=15000)
        page.locator("#tabs button[data-t='Time']").click()
        expect(page.locator("#tp-motion-controls.show")).to_be_visible(timeout=15000)
        expect(page.locator("#tp-motion-status")).to_contain_text("2024")
        page.locator("#tp-motion-range").fill("2023")
        expect(page.locator("#tp-motion-year")).to_have_text("2023")
        # The five watches should start off, explicitly opt in, report 0 data
        # separately from unavailable, and never request browser notification access.
        page.locator("#nav button[data-p='Alarm']").click()
        expect(page.locator("#aAll")).to_be_visible()
        assert page.locator("#aSound").is_checked() is False
        page.locator("#aAll").click()
        for key in ("eq","ls","gl","fi","fl"):
            expect(page.locator("#ac_"+key)).to_be_checked(timeout=10000)
            expect(page.locator("#as_"+key)).to_contain_text("Checked",timeout=15000)
        expect(page.locator("#aList")).to_contain_text("M 5.4")
        assert "emergency" in page.locator("#aSafety").inner_text().lower()
        # The page must have no uncaught execution errors.
        if errors:
            raise AssertionError("Browser JS exceptions: "+" | ".join(errors[:7]))
        browser.close()

if __name__=="__main__":
    main()
