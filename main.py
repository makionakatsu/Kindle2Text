import subprocess
import sys
import os
import json
import time
import hashlib
import cv2
import numpy as np
import pyautogui
from PIL import Image
import pytesseract
import importlib.util
import threading
import queue
import platform
import pygetwindow as gw

# 必要なライブラリリスト
required_packages = ["pyautogui", "Pillow", "pytesseract", "opencv-python", "numpy"]
shutdown_flag = False

def install_missing_packages():
    """必要なライブラリをインストールする（すでにインストール済みならスキップ）"""
    missing_packages = [pkg for pkg in required_packages if importlib.util.find_spec(pkg) is None]

    if not missing_packages:
        print("すべてのライブラリがインストールされています。スキップします。")
        return

    print(f"以下のライブラリが見つかりません。インストールします: {', '.join(missing_packages)}")
    subprocess.run([sys.executable, "-m", "pip", "install", *missing_packages], check=True)

# ライブラリのインストールを実行
install_missing_packages()

def load_config():
    """OSに応じて適切な設定ファイルをロードする"""
    config_filename = "config_mac.json" if platform.system() == "Darwin" else "config_windows.json"
    config_path = os.path.join(os.path.dirname(__file__), config_filename)

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"設定ファイル {config_filename} が見つかりません。")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # デフォルト値を設定
    return {
        "screenshot_region": config.get("screenshot_region", [0, 0, 800, 600]),
        "language": config.get("language", "jpn"),
        "text_orientation": config.get("text_orientation", "vertical"),
        "page_turn_direction": config.get("page_turn_direction", "left"),
        "page_turn_delay": config.get("page_turn_delay", 3),
        "tessdata_prefix": config.get("tessdata_prefix", "./tessdata"),
        "output_file": config.get("output_file", "./output.txt")
    }

# グローバル変数として `config` をロード
config = load_config()

# 設定値をグローバル変数として定義
region = config['screenshot_region']
lang = config.get('language', 'jpn')
text_orientation = config.get('text_orientation', 'vertical')
page_turn_direction = config.get('page_turn_direction', 'left')
page_turn_delay = config.get('page_turn_delay', 3)

# `tessdata_dir` をOSごとに切り替え
tessdata_dir = config.get('tessdata_prefix', './tessdata')

def preprocess_image(image):   
    # 1. グレースケール化
    image_np = np.array(image)
    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
    
    # 2. CLAHEで局所的なコントラスト強調（やや控えめ）
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    clahe_img = clahe.apply(gray)
    
    # 3. Bilateral Filterで平滑化（エッジ保持）
    filtered = cv2.bilateralFilter(clahe_img, d=9, sigmaColor=75, sigmaSpace=75)
    
    # 4. 二値化（niBlackThresholdを試すが、ブロックサイズを大きめ・k値を小さめ）
    #    未インストールの場合は適応的二値化にフォールバック
    try:
        thresh = cv2.ximgproc.niBlackThreshold(
            filtered, 255, cv2.THRESH_BINARY, blockSize=21, k=0.05
        )
    except AttributeError:
        # blockSizeを大きめにし、定数を小さめにする
        thresh = cv2.adaptiveThreshold(
            filtered, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            21, 2
        )
    
    # 5. 形態学的処理（最小限、またはスキップ）
    processed = thresh  # 処理を省略
    
    # 6. 結果をPILに戻す
    processed_image = Image.fromarray(processed)
 
    return processed_image

def image_hash(image):
    """画像データの MD5 ハッシュを生成し、一意の識別子を返す"""
    try:
        return hashlib.md5(image.tobytes()).hexdigest()
    except (MemoryError, ValueError) as e:
        print(f"画像ハッシュの生成中にエラーが発生しました: {e}")
        return None

def extract_text_from_image(image, tessdata_dir, lang, text_orientation):
    """画像から OCR を用いてテキストを抽出する"""
    try:
        if image is None:
            return ""

        # 画像の前処理を実行
        processed_image = preprocess_image(image)
        tessdata_dir_config = f'--tessdata-dir "{tessdata_dir}"'
        psm_mode = "5" if text_orientation == "vertical" else "3"
        config_str = f"{tessdata_dir_config} --psm {psm_mode} --oem 3"

        return pytesseract.image_to_string(processed_image, lang=lang, config=config_str)
    except Exception as e:
        print(f"OCR処理中にエラーが発生しました: {e}")
        return ""

def activate_kindle_app():
    """Kindle アプリをアクティブ化する"""
    try:
        if platform.system() == "Darwin":  # macOS
            subprocess.run(["osascript", "-e", 'tell application "Kindle" to activate'], check=True)
        elif platform.system() == "Windows":
            subprocess.run(["powershell", "-Command", "Start-Process kindle.exe"], check=True)
        time.sleep(2)
    except subprocess.SubprocessError:
        print("エラー: Kindle アプリをアクティブ化できませんでした。")
        sys.exit(1)

def minimize_kindle_app():
    """Kindle アプリを最小化する"""
    try:
        if platform.system() == "Darwin":  # macOS
            applescript_command = '''
            tell application "Kindle" to set miniaturized of window 1 to true
            '''
            subprocess.run(["osascript", "-e", applescript_command], check=True)
        elif platform.system() == "Windows":
            kindle_window = gw.getWindowsWithTitle("Kindle")
            if kindle_window:
                kindle_window[0].minimize()
            else:
                print("エラー: Kindleのウィンドウが見つかりません。")
    except Exception as e:
        print(f"エラー: Kindle の最小化に失敗しました。{e}")

def monitor_exit():
    # エンターを2回打ち込むとプログラムを終了するための監視
    global shutdown_flag
    print("途中で作業を終了するには、エンターを2回押してください。")
    count = 0
    while not shutdown_flag:
        line = input()
        if line == "":
            count += 1
            if count >= 2:
                print("終了要求が受け付けられました。処理を停止します。")
                shutdown_flag = True
                image_queue.put(None)
                break
        else:
            count = 0

def show_message():
    """OCR開始位置の設定を促すメッセージを表示し、エンターキー入力後にKindleを最大化"""
    message = "OCR開始位置にページ位置を設定したら、ターミナル画面に戻ってEnterキーを押してください。"
    try:
        if platform.system() == "Darwin":  # macOS
            subprocess.run(["osascript", "-e", f'display notification "{message}" with title "Kindle2Text"'])
        elif platform.system() == "Windows":
            subprocess.run(["powershell", "-Command", f'[System.Windows.MessageBox]::Show("{message}", "Kindle2Text")'])
    except subprocess.SubprocessError:
        print("エラー: 通知の送信に失敗しました。")

    print("\n=== Kindle2Text ===")
    print(f"📌 {message}")
    input("準備ができたらEnterキーを押してください...")

    # Kindleをフルスクリーン化
    try:
        if platform.system() == "Darwin":  # macOS
            applescript_command = '''
            tell application "System Events"
                tell process "Kindle"
                    set frontmost to true
                    keystroke "f" using {command down, control down}
                end tell
            end tell
            '''
            subprocess.run(["osascript", "-e", applescript_command])
        elif platform.system() == "Windows":
            powershell_command = '''
            $wshell = New-Object -ComObject wscript.shell
            $wshell.AppActivate('Kindle')
            Start-Sleep -Seconds 1
            $wshell.SendKeys('{F11}')
            '''
            subprocess.run(["powershell", "-Command", powershell_command], check=True)
        print("Kindleをフルスクリーンにしました。")
    except subprocess.SubprocessError:
        print("エラー: Kindle のフルスクリーン化に失敗しました。")

def capture_screenshot(region):
    """指定された領域のスクリーンショットを取得"""
    try:
        screenshot = pyautogui.screenshot(region=region)
        # screenshot.save("debug_screenshot.png")  # デバッグ用に保存
        return screenshot
    except Exception as e:
        print(f"スクリーンショット取得中にエラー: {e}")
        return None

# 画像キュー（スクリーンショットとOCRを並列処理）
image_queue = queue.Queue()

def capture_screenshots():
    # Kindleのスクリーンショットを連続取得し、キューに送る
    print("📸 スクリーンショットの取得を開始します...")
    last_image_hash = None
    page = 1

    while True:
        if shutdown_flag:
            print("終了要求によりスクリーンショットの取得を停止します。")
            image_queue.put(None) 
            break
        screenshot = capture_screenshot(region)
        if screenshot is None:
            time.sleep(0.1)
            continue

        current_image_hash = image_hash(screenshot)
        if last_image_hash == current_image_hash:
            print("🔄 ページの変化がないため終了")
            image_queue.put(None) 
            break
        
        last_image_hash = current_image_hash
        image_queue.put((screenshot, page))

        # Kindleのページを送る
        pyautogui.press(page_turn_direction)
        time.sleep(page_turn_delay)  
        page += 1

def process_ocr():
    # OCR処理を行い、結果を保存
    print("📝 OCR処理を開始します...")
    with open(config['output_file'], 'a', encoding='utf-8') as file:
        while True:
            item = image_queue.get()
            if item is None:
                break  # OCRスレッド終了の合図
            
            screenshot, page = item
            text = extract_text_from_image(screenshot, tessdata_dir, lang, text_orientation)
            
            if text.strip():
                file.write(f"--- Page {page} ---\n{text}\n")

def main():
    # Kindle からスクリーンショットを撮影し OCR でテキストを抽出、ファイルに保存
    activation_delay = config.get('activation_delay', 5)  # `config.json` から取得

    activate_kindle_app()
    show_message()
    time.sleep(activation_delay)

    monitor_thread = threading.Thread(target=monitor_exit, daemon=True)
    monitor_thread.start()

    # スクリーンショットとOCRを並列処理
    screenshot_thread = threading.Thread(target=capture_screenshots)
    ocr_thread = threading.Thread(target=process_ocr)

    screenshot_thread.start()
    ocr_thread.start()

    screenshot_thread.join()
    ocr_thread.join()

    print("✅ OCR処理完了")
    
    # **OCR完了後に音を鳴らす**
    if platform.system() == "Darwin":  # macOS
        os.system('afplay /System/Library/Sounds/Glass.aiff')
    elif platform.system() == "Windows":
        os.system('powershell -Command "[console]::beep(1000, 500)"')
    
    # Kindleを最小化する
    minimize_kindle_app()
    
if __name__ == "__main__":
    main()
