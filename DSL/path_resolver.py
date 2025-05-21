# backend/app/logic/path_resolver.py
from abc import ABC, abstractmethod
from typing import List, TYPE_CHECKING
import os

if TYPE_CHECKING:
    # This is for type hinting only and avoids circular import if DslError remains in dsl_engine
    # If DslError were in a common errors module, this would be a direct import.
    pass

class PathResolverError(Exception):
    """Custom exception for path resolver issues."""
    def __init__(self, message: str, path: str | None = None, original_exception: Exception | None = None):
        super().__init__(message)
        self.message = message
        self.path = path
        self.original_exception = original_exception

    def __str__(self):
        s = f"PathResolverError: {self.message}"
        if self.path:
            s += f" (Path: {self.path})"
        if self.original_exception:
            s += f" Caused by: {type(self.original_exception).__name__}: {self.original_exception}"
        return s

class AbstractPathResolver(ABC):
    @abstractmethod
    def __init__(self, global_prompts_root: str, character_base_data_path: str):
        self.global_prompts_root = os.path.abspath(global_prompts_root)
        self.character_base_data_path = os.path.abspath(character_base_data_path)
        self._context_dir_stack: List[str] = []

    @abstractmethod
    def resolve_path(self, rel_path: str) -> str:
        """
        Resolves a relative path string into a unique, absolute-like identifier.
        Resolution is based on the current context, character_base_data_path, or global_prompts_root.
        Must handle security to prevent path traversal outside allowed roots.
        """
        pass

    @abstractmethod
    def load_text(self, resolved_path_id: str, context_for_error_msg: str) -> str:
        """Loads text content from the resource identified by resolved_path_id."""
        pass

    @abstractmethod
    def get_dirname(self, resolved_path_id: str) -> str:
        """Returns the "directory" part of a resolved_path_id."""
        pass

    def push_base_context(self, resolved_dir_path_id: str):
        self._context_dir_stack.append(resolved_dir_path_id)

    def pop_base_context(self):
        if not self._context_dir_stack:
            raise PathResolverError("Attempted to pop from an empty context directory stack.")
        self._context_dir_stack.pop()

    def _get_current_context_dir(self) -> str:
        if self._context_dir_stack:
            return self._context_dir_stack[-1]
        return self.character_base_data_path

class LocalPathResolver(AbstractPathResolver):
    def __init__(self, global_prompts_root: str, character_base_data_path: str):
        super().__init__(global_prompts_root, character_base_data_path)
        if not os.path.isabs(self.global_prompts_root):
            raise ValueError("LocalPathResolver: global_prompts_root must be an absolute path.")
        if not os.path.isabs(self.character_base_data_path):
            raise ValueError("LocalPathResolver: character_base_data_path must be an absolute path.")
        
        norm_global_root = os.path.normpath(self.global_prompts_root)
        norm_char_base = os.path.normpath(self.character_base_data_path)

        if not (norm_char_base.startswith(norm_global_root + os.sep) or norm_char_base == norm_global_root):
            try:
                if os.path.commonpath([norm_global_root, norm_char_base]) != norm_global_root:
                    raise PathResolverError(
                        f"Security Error: Character base path '{norm_char_base}' "
                        f"is outside the global prompts root '{norm_global_root}'.",
                        path=norm_char_base
                    )
            except ValueError:
                 raise PathResolverError(
                    f"Security Error: Character base path '{norm_char_base}' cannot be reconciled with "
                    f"global prompts root '{norm_global_root}' (e.g. different drives).",
                    path=norm_char_base
                )

    def _secure_join(self, base: str, *paths: str) -> str:
        combined_path = os.path.normpath(os.path.join(base, *paths))
        norm_global_root = os.path.normpath(self.global_prompts_root)
        norm_combined_path = os.path.normpath(os.path.abspath(combined_path))

        if not (norm_combined_path.startswith(norm_global_root + os.sep) or norm_combined_path == norm_global_root):
            try:
                if os.path.commonpath([norm_global_root, norm_combined_path]) != norm_global_root:
                    raise PathResolverError(
                        f"Security Error: Path '{norm_combined_path}' is outside the allowed global prompts root '{norm_global_root}'.",
                        path=norm_combined_path
                    )
            except ValueError:
                 raise PathResolverError(
                    f"Security Error: Path '{norm_combined_path}' cannot be safely combined with Prompts root '{norm_global_root}'.",
                    path=norm_combined_path
                )
        return norm_combined_path

    def resolve_path(self, rel_path: str) -> str:
        if rel_path.startswith(("_CommonPrompts/", "_CommonScripts/")):
            return self._secure_join(self.global_prompts_root, rel_path)

        current_processing_dir = self._get_current_context_dir()

        if rel_path.startswith("./"):
            return self._secure_join(current_processing_dir, rel_path[2:])
        
        if rel_path.startswith("../"):
            return self._secure_join(current_processing_dir, rel_path)
            
        return self._secure_join(self.character_base_data_path, rel_path)

    def load_text(self, resolved_path_id: str, context_for_error_msg: str) -> str:
        try:
            if not os.path.isfile(resolved_path_id):
                raise FileNotFoundError(f"Path is not a file: {resolved_path_id}")
            with open(resolved_path_id, 'r', encoding='utf-8') as f:
                return f.read().rstrip()
        except FileNotFoundError as e:
            raise PathResolverError(f"File not found '{os.path.basename(resolved_path_id)}' (context: {context_for_error_msg})", path=resolved_path_id, original_exception=e) from e
        except Exception as e:
            raise PathResolverError(f"Error reading file '{os.path.basename(resolved_path_id)}' (context: {context_for_error_msg})", path=resolved_path_id, original_exception=e) from e

    def get_dirname(self, resolved_path_id: str) -> str:
        dir_name = os.path.dirname(resolved_path_id)
        norm_global_root = os.path.normpath(self.global_prompts_root)
        norm_dir_name = os.path.normpath(dir_name)
        if not (norm_dir_name.startswith(norm_global_root + os.sep) or norm_dir_name == norm_global_root):
            try:
                if os.path.commonpath([norm_global_root, norm_dir_name]) != norm_global_root:
                    raise PathResolverError(
                        f"Security Error: Derived directory name '{norm_dir_name}' is outside the global prompts root '{norm_global_root}'.",
                        path=norm_dir_name
                    )
            except ValueError:
                raise PathResolverError(
                    f"Security Error: Derived directory name '{norm_dir_name}' cannot be reconciled with global prompts root '{norm_global_root}'.",
                    path=norm_dir_name
                )
        return norm_dir_name

class RemotePathResolver(AbstractPathResolver):
    def __init__(self, global_prompts_root_url: str, character_base_data_path_segment: str, api_token: str | None = None):
        # For remote, global_prompts_root_url is the base URL.
        # character_base_data_path_segment is appended to the base URL for character-specific resources.
        # A proper URL join should be used here, os.path.join is for file paths.
        # from urllib.parse import urljoin # Example
        # char_base_url = urljoin(global_prompts_root_url + '/', character_base_data_path_segment + '/')
        # super().__init__(global_prompts_root_url, char_base_url)
        
        # Simplified for placeholder:
        self.global_prompts_root_url = global_prompts_root_url.rstrip('/')
        self.character_base_url = f"{self.global_prompts_root_url}/{character_base_data_path_segment.strip('/')}"
        super().__init__(self.global_prompts_root_url, self.character_base_url)
        
        self.api_token = api_token
        # An actual HTTP client (e.g., httpx, requests) would be initialized here.
        # For now, it's a placeholder.

    def _construct_url(self, base: str, path_segment: str) -> str:
        # Placeholder for proper URL construction, e.g., using urllib.parse.urljoin
        # This naive version is for demonstration only.
        return f"{base.rstrip('/')}/{path_segment.lstrip('/')}"

    def resolve_path(self, rel_path: str) -> str:
        # This would construct a full URL based on context and rel_path
        # Security: Ensure target_url is within allowed base URLs.
        
        # Placeholder logic:
        if rel_path.startswith(("_CommonPrompts/", "_CommonScripts/")):
            return self._construct_url(self.global_prompts_root, rel_path)
        
        current_base_url_context = self._get_current_context_dir() # This is a URL

        if rel_path.startswith("./"):
            return self._construct_url(current_base_url_context, rel_path[2:])
        
        if rel_path.startswith("../"):
            base_parts = current_base_url_context.split('/')
            num_dots = rel_path.count("../")
            effective_base = "/".join(base_parts[:-num_dots]) if len(base_parts) > num_dots else self.global_prompts_root
            return self._construct_url(effective_base, rel_path.replace("../", ""))

        # Default to character base path
        return self._construct_url(self.character_base_data_path, rel_path)

    def load_text(self, resolved_path_id: str, context_for_error_msg: str) -> str:
        # This would make an HTTP GET request to resolved_path_id (which is a URL)
        # Example with a hypothetical http client:
        # headers = {}
        # if self.api_token:
        #     headers['Authorization'] = f"Bearer {self.api_token}"
        # try:
        #     response = http_client.get(resolved_path_id, headers=headers)
        #     response.raise_for_status() # Check for HTTP errors
        #     return response.text.rstrip()
        # except HttpClientError as e: # Replace with actual client exception
        #     raise PathResolverError(f"Error loading remote resource '{resolved_path_id}' (context: {context_for_error_msg})", path=resolved_path_id, original_exception=e) from e
        
        # Placeholder:
        if "error" in resolved_path_id.lower():
            raise PathResolverError(f"Simulated error loading remote resource '{resolved_path_id}'", path=resolved_path_id)
        if "notfound" in resolved_path_id.lower():
            raise PathResolverError(f"Simulated 404 for remote resource '{resolved_path_id}'", path=resolved_path_id, original_exception=FileNotFoundError("Mock HTTP 404"))

        return f"Content from remote URL: {resolved_path_id}\n(Original context: {context_for_error_msg})"

    def get_dirname(self, resolved_path_id: str) -> str:
        # For URLs, this would mean getting the parent "directory" part of the URL.
        # Example with urllib.parse:
        # from urllib.parse import urlparse, urljoin
        # if not resolved_path_id.endswith('/'): # Ensure it's treated as a file to get its container
        #     resolved_path_id_as_file = resolved_path_id
        # else: # If it's already a dir, get its parent
        #     resolved_path_id_as_file = resolved_path_id.rstrip('/')
        # return urljoin(resolved_path_id_as_file, '.') # Gets current directory URL
        
        # Simplified placeholder:
        if '/' not in resolved_path_id:
            return self.global_prompts_root # Or some base
        
        parts = resolved_path_id.split('/')
        if resolved_path_id.endswith('/'): # If it's like a/b/c/
            return "/".join(parts[:-2]) + '/' if len(parts) > 2 else self.global_prompts_root
        return "/".join(parts[:-1]) + '/' # If it's like a/b/c/file.txt -> a/b/c/