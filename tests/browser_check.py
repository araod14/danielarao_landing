from playwright.sync_api import sync_playwright
from pathlib import Path
import json
import os

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8765")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
    page = browser.new_page()
    errors=[]
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(BASE_URL, wait_until='networkidle')
    for lang in ['en','es']:
        page.locator(f'[data-language="{lang}"]').click()
        for width in [360,390,768,1024,1440]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (lang,width,'overflow')
            assert page.locator('html').get_attribute('lang') == lang
            page.screenshot(path=f'/tmp/daniel-{lang}-{width}.png',full_page=True)
    page.reload()
    assert page.locator('html').get_attribute('lang') == 'es'
    page.locator('#name').fill('Jane Doe')
    page.locator('#email').fill('jane@example.com')
    page.locator('#message').fill('Please collect clinic records into a CSV file.')
    page.locator('[data-language="en"]').click()
    assert page.locator('#name').input_value() == 'Jane Doe'
    page.route('**/api/contact', lambda route: route.fulfill(status=503, content_type='application/json', body='{}'))
    page.locator('[type="submit"]').click()
    page.wait_for_function("document.querySelector('#form-status').dataset.state === 'unavailable'")
    assert page.locator('#email-fallback').is_visible()
    assert 'Jane%20Doe' in page.locator('#email-fallback').get_attribute('href')
    page.unroute('**/api/contact')
    page.route('**/api/contact', lambda route: route.fulfill(status=429, content_type='application/json', body='{}'))
    page.locator('[type="submit"]').click()
    page.wait_for_function("document.querySelector('#form-status').dataset.state === 'limited'")
    assert not page.locator('#email-fallback').is_visible()
    page.unroute('**/api/contact')
    page.route('**/api/contact', lambda route: route.fulfill(status=200, content_type='application/json', body='{"status":"sent"}'))
    page.locator('[type="submit"]').click()
    page.wait_for_function("document.querySelector('#form-status').dataset.state === 'sent'")
    assert page.locator('#name').input_value() == ''
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('.hero-rule').evaluate("el => getComputedStyle(el).animationName") == 'none'
    page.locator('.faq-list summary').first.click()
    assert page.locator('.faq-list details').first.get_attribute('open') is not None
    context = browser.new_context(java_script_enabled=False)
    nojs = context.new_page()
    nojs.goto(BASE_URL)
    assert nojs.locator('h1').inner_text().startswith('Web scraping')
    assert nojs.locator('noscript').is_visible()
    blocked = browser.new_context()
    blocked.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new Error('Blocked')}})")
    blocked_page=blocked.new_page()
    blocked_page.goto(BASE_URL)
    blocked_page.locator('[data-language="es"]').click()
    assert blocked_page.locator('html').get_attribute('lang') == 'es'
    assert not errors, errors
    print(json.dumps({'responsive_views':10,'language_persistence':True,'form_fallback_rate_success':True,'reduced_motion':True,'no_js_content':True,'blocked_storage':True,'console_errors':errors}))
    browser.close()
