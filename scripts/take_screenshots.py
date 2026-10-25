"""Capture high-resolution screenshots of the Streamlit app and printable sheets."""

import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def capture_all():
    out_dir = Path("docs/images")
    out_dir.mkdir(parents=True, exist_ok=True)

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--width=1440")
    options.add_argument("--height=1000")

    driver = webdriver.Firefox(options=options)
    driver.set_window_size(1440, 1000)

    try:
        # 1. Main Page / Brackets Explorer
        print("Capturing 01_brackets_explorer.png...")
        driver.get("http://127.0.0.1:8503")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[role='tab']"))
        )
        time.sleep(3)  # Wait for iframe preview component to render
        driver.save_screenshot(str(out_dir / "01_brackets_explorer.png"))

        # Find tab buttons
        tabs = driver.find_elements(By.CSS_SELECTOR, "[role='tab']")
        print(f"Found {len(tabs)} tabs")

        # 2. Tweak & Regenerate Tab
        if len(tabs) >= 2:
            print("Capturing 02_tweak_regenerate.png...")
            tabs[1].click()
            time.sleep(2)
            driver.save_screenshot(str(out_dir / "02_tweak_regenerate.png"))

        # 3. Sheet Import Tab
        if len(tabs) >= 3:
            print("Capturing 03_sheet_import.png...")
            tabs[2].click()
            time.sleep(2)
            driver.save_screenshot(str(out_dir / "03_sheet_import.png"))

        # 4. Print & Export Tab
        if len(tabs) >= 4:
            print("Capturing 04_print_export.png...")
            tabs[3].click()
            time.sleep(2)
            driver.save_screenshot(str(out_dir / "04_print_export.png"))

        # 5. Audit Log Tab
        if len(tabs) >= 5:
            print("Capturing 05_audit_log.png...")
            tabs[4].click()
            time.sleep(2)
            driver.save_screenshot(str(out_dir / "05_audit_log.png"))

        # 6. Actual Printable Bracket Sheet HTML
        html_file = Path("data/tournaments/example-tournament/exports/brackets.html").resolve()
        if html_file.exists():
            print("Capturing 06_printable_bracket_sheet.png...")
            driver.get(f"file://{html_file}")
            time.sleep(2)
            driver.save_screenshot(str(out_dir / "06_printable_bracket_sheet.png"))

        print("All screenshots captured successfully!")
    finally:
        driver.quit()


if __name__ == "__main__":
    capture_all()
