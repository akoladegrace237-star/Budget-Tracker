"""Browser checks against the isolated preview on port 5055."""
import json
import os
import re
import secrets
from pathlib import Path
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path(__file__).resolve().parent.parent/'.browser-cache')
from playwright.sync_api import sync_playwright

OUT=Path(__file__).resolve().parent.parent/'.qa'/'screenshots'
OUT.mkdir(exist_ok=True)
BASE='http://127.0.0.1:5055'
USERNAME='review-'+secrets.token_hex(3)

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000})
    page=context.new_page(); errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    for size,label in [({'width':1440,'height':1000},'desktop'),({'width':390,'height':844},'mobile')]:
        page.set_viewport_size(size)
        for route in ['/login','/register','/forgot-pin']:
            page.goto(BASE+route)
            page.screenshot(path=str(OUT/(label+'-'+route.strip('/')+'.png')),full_page=True,animations='disabled')
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto(BASE+'/register')
    page.locator('#username').fill(USERNAME)
    page.locator('#pin').fill('visual-review-password')
    page.get_by_role('button',name='Create Account').click()
    page.wait_for_url('**/register')
    if page.get_by_text('Save your recovery code',exact=True).count():
        page.get_by_role('link',name='I saved my code').click()
    else: page.goto(BASE+'/login')
    page.locator('#username').fill(USERNAME);page.locator('#pin').fill('visual-review-password')
    page.get_by_role('button',name='Sign In',exact=True).click()
    page.wait_for_url(re.compile('.*(?:setup|dashboard)$'))
    page.goto(BASE+'/setup')
    page.locator('#opening_cash').fill('3500')
    if page.locator('#monthly_income').count():
        page.locator('#monthly_income').fill('2800');page.locator('#regular_bill').fill('900')
        page.locator('#limit_groceries').fill('350');page.locator('#limit_housing').fill('950')
    page.get_by_role('button',name='Save and open dashboard').click()
    page.wait_for_url('**/dashboard');page.wait_for_function("document.querySelector('#dashboardState').hidden")
    token=page.locator('meta[name=csrf-token]').get_attribute('content')
    for route,fields in [('/savings/goal/add',dict(name='Emergency fund',target='3000',saved='650')),
                         ('/savings/add',dict(month=page.evaluate("new Date().toISOString().slice(0,7)"),amount='200',investment='0',type='Emergency fund')),
                         ('/credit/add',dict(name='Everyday card',rate='19.9',balance='1200')),
                         ('/loans/add',dict(name='Personal loan',rate='5.5',balance='500')),
                         ('/shares/add',dict(name='Index fund',units='10',price_per_unit='42.1250'))]:
        response=context.request.post(BASE+route,form={'csrf_token':token,**fields});assert response.ok
    page.goto(BASE+'/transactions?add=1')
    page.locator('#addTransactionSheet [name=amount]').fill('62.45')
    page.locator('#addTransactionSheet [name=category]').select_option('groceries')
    page.locator('#addTransactionSheet [name=description]').fill('Weekly groceries')
    page.get_by_role('button',name='Save Transaction').click()
    page.wait_for_url('**/transactions')
    page.goto(BASE+'/dashboard');page.wait_for_function("document.querySelector('#dashboardState').hidden")
    report=[]
    for width,height,label in [(1440,1000,'desktop'),(390,844,'mobile'),(320,740,'small-mobile')]:
        page.set_viewport_size({'width':width,'height':height})
        for route in ['/dashboard','/transactions','/income','/expenses','/recurring','/budgets','/savings','/debt','/projections','/shares','/settings','/setup','/import','/restore']:
            response=page.goto(BASE+route)
            if route=='/dashboard': page.wait_for_function("document.querySelector('#dashboardState').hidden")
            page.wait_for_timeout(350)
            page.screenshot(path=str(OUT/(label+'-'+route.strip('/')+'.png')),full_page=True,animations='disabled')
            layout=page.evaluate('''() => ({width:innerWidth, scrollWidth:document.documentElement.scrollWidth,
              unlabeled:[...document.querySelectorAll('input:not([type=hidden]),select,textarea')].filter(el =>
                !el.labels?.length && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby')).map(el=>el.name),
              overflow:[...document.querySelectorAll('main *')].filter(el=>el.getClientRects().length &&
                getComputedStyle(el).visibility!=='hidden' && el.getBoundingClientRect().right>innerWidth+2 &&
                !el.closest('.table-responsive,.csv-example,.bottom-sheet')).slice(0,8).map(el=>el.className)})''')
            report.append(dict(view=label,route=route,status=response.status,**layout))
    page.set_viewport_size({'width':390,'height':844})
    page.goto(BASE+'/transactions')
    trigger=page.get_by_role('button',name='+ Add',exact=True); trigger.click()
    page.wait_for_timeout(300)
    assert page.locator('#addTransactionSheet').get_attribute('aria-hidden')=='false'
    page.keyboard.press('Escape')
    assert page.locator('#addTransactionSheet').get_attribute('aria-hidden')=='true'
    assert trigger.evaluate('(el)=>el===document.activeElement')
    # Exercise the edit dialogs for populated ancillary screens.
    for route,selector,form_id,field,expected in [
        ('/recurring','.record-card-main','editRecurringForm','name','Rent / mortgage'),
        ('/shares','.record-card-main','editShareForm','name','Index fund'),
    ]:
        page.goto(BASE+route);page.locator(selector).first.click()
        page.locator('.record-card .btn-edit').first.click()
        assert page.locator('#'+form_id+' [name='+field+']').input_value()==expected
        page.keyboard.press('Escape')
    page.goto(BASE+'/savings');page.locator('.goal-card .btn-edit').first.click()
    assert page.locator('#editGoalForm [name=name]').input_value()=='Emergency fund'
    page.keyboard.press('Escape')
    page.goto(BASE+'/debt');page.locator('.debt-kebab-btn').first.click()
    page.locator('.debt-kebab-menu button').first.click()
    assert page.locator('#editCreditForm [name=name]').input_value()=='Everyday card'
    page.keyboard.press('Escape')
    page.locator('#totalBudgetInput').fill('250');page.get_by_role('button',name='Calculate',exact=True).click()
    assert page.locator('#payoffResults').is_visible()
    # A zero-interest budget large enough to cover both balances must clear both in one month.
    result=page.evaluate("amortize([{name:'A',balance:100,rate:0},{name:'B',balance:100,rate:0}],200)")
    assert result['totalMonths']==1
    page.goto(BASE+'/dashboard');page.wait_for_function("document.querySelector('#dashboardState').hidden")
    page.route('**/api/dashboard-data',lambda route:route.abort())
    page.reload();page.get_by_role('button',name='Retry').wait_for()
    assert page.locator('#totalIncome').inner_text()=='—'
    assert page.locator('#cashBalance').inner_text()=='—'
    page.screenshot(path=str(OUT/'mobile-dashboard-error.png'),full_page=True)
    page.unroute('**/api/dashboard-data')
    page.get_by_role('button',name='Retry').click();page.wait_for_function("document.querySelector('#dashboardState').hidden")
    # User text must stay text rather than become markup or execute scripts.
    token=page.locator('meta[name=csrf-token]').get_attribute('content')
    response=context.request.post(BASE+'/savings/goal/add',form={'csrf_token':token,'name':'<img src=x onerror="window.injected=1">','target':'100','saved':'10'})
    assert response.ok
    page.reload();page.wait_for_function("document.querySelector('#dashboardState').hidden")
    assert page.evaluate('window.injected===undefined')
    assert page.locator('.dg-goal-name img').count()==0
    page.goto(BASE+'/transactions?type=transfer&add=1')
    page.locator('#addTransactionSheet [name=amount]').fill('100')
    page.locator('#addTransactionSheet [name=description]').fill('Investment purchase')
    page.get_by_role('button',name='Save Transaction').click()
    page.wait_for_url('**/transactions')
    assert page.get_by_text('Investment purchase',exact=True).count()>=1
    page.get_by_role('button',name='More sections',exact=True).click()
    page.wait_for_timeout(300); assert page.locator('#moreSheet').get_attribute('aria-hidden')=='false'
    page.keyboard.press('Escape'); assert page.locator('#moreSheet').get_attribute('aria-hidden')=='true'
    page.goto(BASE+'/dashboard');page.wait_for_function("document.querySelector('#dashboardState').hidden")
    # Inspect cache storage after visiting financial pages: static assets only.
    page.wait_for_function("navigator.serviceWorker.controller !== null")
    cached=page.evaluate('''async()=>{const names=await caches.keys();const urls=[];for(const name of names){const c=await caches.open(name);urls.push(...(await c.keys()).map(r=>new URL(r.url).pathname));}return urls;}''')
    assert '/api/dashboard-data' not in cached and '/dashboard' not in cached
    context.set_offline(True)
    page.goto(BASE+'/dashboard',wait_until='domcontentloaded')
    assert page.get_by_role('heading',name='You are offline').count()==1
    context.set_offline(False)
    (OUT/'report.json').write_text(json.dumps(dict(pages=report,errors=errors,cache=cached),indent=2),encoding='utf-8')
    print(json.dumps(dict(pages=len(report),errors=errors,layout_issues=[r for r in report if r['scrollWidth']>r['width'] or r['overflow'] or r['unlabeled']],screenshots=str(OUT)),indent=2))
    browser.close()
