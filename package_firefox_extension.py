import os
import zipfile
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE_DIR, "ui")
DIST_DIR = os.path.join(BASE_DIR, "dist")
EXT_DIR = os.path.join(DIST_DIR, "extension")

def package_firefox_extension():
    os.makedirs(EXT_DIR, exist_ok=True)
    xpi_path = os.path.join(EXT_DIR, "ShortBot-v1.2.1-Firefox.xpi")
    zip_path = os.path.join(EXT_DIR, "ShortBot-v1.2.1-WebExtension.zip")
    
    for f in (xpi_path, zip_path):
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    print(f"Building Firefox Add-on package from {UI_DIR}...")
    
    # Files to include
    with zipfile.ZipFile(xpi_path, "w", zipfile.ZIP_DEFLATED) as xpi:
        for root, dirs, files in os.walk(UI_DIR):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, UI_DIR)
                # Skip any git or temporary files
                if any(part.startswith(".") for part in rel_path.split(os.sep)):
                    continue
                xpi.write(abs_path, rel_path)
                print(f"  + Added {rel_path}")

    # Also keep a .zip copy
    shutil.copyfile(xpi_path, zip_path)

    # Maintain release aliases in root DIST_DIR
    shutil.copyfile(xpi_path, os.path.join(DIST_DIR, "shortbot-firefox.xpi"))
    shutil.copyfile(zip_path, os.path.join(DIST_DIR, "shortbot-firefox.zip"))
    
    size_kb = os.path.getsize(xpi_path) / 1024
    print("\n" + "=" * 60)
    print(f"[SUCCESS] Firefox Extension Package Created!")
    print(f"File: {xpi_path} ({size_kb:.1f} KB)")
    print(f"Zip:  {zip_path} ({size_kb:.1f} KB)")
    print("=" * 60)
    print("\nHow to install in Mozilla Firefox:")
    print("1. Open Firefox and go to: about:debugging#/runtime/this-firefox")
    print("2. Click 'Load Temporary Add-on...'")
    print("3. Select either dist/shortbot-firefox.xpi or ui/manifest.json")
    print("=" * 60 + "\n")
    return xpi_path

if __name__ == "__main__":
    package_firefox_extension()
