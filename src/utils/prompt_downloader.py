import os
import shutil
import requests
import zipfile
import io
from urllib.parse import urlparse
from main_logger import logger

class PromptDownloader:
    def __init__(self):
        self.repo_url = "https://github.com/VinerX/NeuroMita" #https://github.com/vlad2830/NeuroMita
        self.branch = "main"
        self.base_path = os.environ.get("NEUROMITA_PROMPTS_DIR", os.path.abspath("Prompts"))
        self.temp_download_path = self.base_path + "_temp"

    def download_and_replace_prompts(self):
        """Downloads prompts from GitHub and replaces the existing ones"""
        try:
            parsed_url = urlparse(self.repo_url)
            path_parts = parsed_url.path.split('/')
            owner = path_parts[1]
            repo = path_parts[2]
            
            zip_url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{self.branch}"
            logger.info(f"Downloading repository zip from: {zip_url}")
            
            response = requests.get(zip_url)
            response.raise_for_status()

            backup_path = f"{self.base_path}_backup"
            if os.path.exists(self.base_path):
                if os.path.exists(backup_path):
                    shutil.rmtree(backup_path)
                shutil.copytree(self.base_path, backup_path)
                logger.info(f"Created backup at: {backup_path}")
            
            with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
                root_folder = next(name for name in zip_ref.namelist() if name.endswith('/'))
                prompts_path = os.path.join(root_folder, "Prompts/")
                
                if os.path.exists(self.temp_download_path):
                    shutil.rmtree(self.temp_download_path)
                os.makedirs(self.temp_download_path)

                for zip_path in zip_ref.namelist():
                    if zip_path.startswith(prompts_path):
                        relative_path = zip_path[len(root_folder) + len("Prompts/"):]
                        if relative_path: 
                            target_path = os.path.join(self.temp_download_path, relative_path)
                            if zip_path.endswith('/'): 
                                os.makedirs(target_path, exist_ok=True)
                            else: 
                                with zip_ref.open(zip_path) as source, open(target_path, 'wb') as target:
                                    shutil.copyfileobj(source, target)

            if os.path.exists(self.base_path):
                shutil.rmtree(self.base_path)
            shutil.move(self.temp_download_path, self.base_path)
            
            logger.info("Successfully downloaded and replaced prompts!")
            return True
            
        except Exception as e:
            logger.error(f"Error in download_and_replace_prompts: {e}")
            if os.path.exists(self.temp_download_path):
                shutil.rmtree(self.temp_download_path)
            return False