import os

async def scan_folder(folder_path: str) -> list[str]:
    files = []
    for file in os.listdir(folder_path):
        files.append(file)
    return files