import pyautogui
from PIL import Image
import pytesseract
import time
import subprocess
import os
import json
import hashlib

def load_config():
    with open('config.json', 'r') as config_file:
        return json.load(config_file)

def activate_kindle_app():
    applescript_command = '''
    tell application "Kindle"
        activate
    end tell
    '''
    subprocess.run(["osascript", "-e", applescript_command])
    time.sleep(2)

def capture_screenshot(region):
    return pyautogui.screenshot(region=region)

def extract_text_from_image(image, tessdata_dir, lang='jpn_vert'):
    try:
        tessdata_dir_config = f'--tessdata-dir "{tessdata_dir}"'
        config = f"{tessdata_dir_config} --psm 5"
        return pytesseract.image_to_string(image, lang=lang, config=config)
    except Exception as e:
        print(f"OCR処理中にエラーが発生しました: {e}")
        return ""

def image_hash(image):
    hash_obj = hashlib.md5()
    hash_obj.update(image.tobytes())
    return hash_obj.hexdigest()

def main():
    config = load_config()
    os.environ['TESSDATA_PREFIX'] = config['tessdata_prefix']
    region = config['screenshot_region']
    activate_kindle_app()
    input("対象の本をKindleで開いてください。準備ができたらEnterキーを押してください...")
    activate_kindle_app()
    pyautogui.hotkey('ctrl', 'cmd', 'f')

    last_image_hash = None
    page = 0
    while True:
        print(f"ページ {page + 1} を処理中...")
        screenshot = capture_screenshot(region)
        current_image_hash = image_hash(screenshot)

        if last_image_hash is not None and last_image_hash == current_image_hash:
            print("ページが変化していないため、処理を終了します。")
            break

        last_image_hash = current_image_hash
        text = extract_text_from_image(screenshot, config['tessdata_prefix'])
        with open(config['output_file'], 'a', encoding='utf-8') as file:
            file.write(f"--- Page {page + 1} ---\n{text}\n")
        
        pyautogui.press('left')  # ページ送りに左キーを使用
        time.sleep(config['page_turn_delay'])
        page += 1

if __name__ == "__main__":
    main()
