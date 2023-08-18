
auth = "brd-customer-hl_f6ac9ba2-zone-scraping_browser:p42yduf8gfzf"
# auth = "brd-customer-hl_f6ac9ba2-zone-scraping_browser1:3jow9ai49er4"

from selenium.webdriver import Remote, ChromeOptions
from selenium.webdriver.common.by import By

auth = "brd-customer-hl_f6ac9ba2-zone-scraping_browser1:3jow9ai49er4"
AUTH = auth
SBR_WEBDRIVER = f'https://{AUTH}@zproxy.lum-superproxy.io:9515'

def main():
    driver = Remote(
        command_executor=SBR_WEBDRIVER,
        options=ChromeOptions(),
    )
    try:
        driver.get('https://example.com')
        driver.get_screenshot_as_file('./page.png')
        body = driver.find_element(By.TAG_NAME, 'body')
        print(body.text)
    finally:
        driver.quit()

if __name__ == '__main__':
    main()