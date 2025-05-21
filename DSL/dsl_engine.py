# File: logic/dsl_engine.py
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import sys
import traceback
from typing import List, Any, TYPE_CHECKING
from contextlib import contextmanager

LOG_DIR = "Logs"
LOG_FILE = os.path.join(LOG_DIR, "dsl_execution.log")
# Import the resolver components
from DSL.path_resolver import AbstractPathResolver, PathResolverError


RED = "\033[91m"
YEL = "\033[93m"
RST = "\033[0m"

LOG_FILE = os.path.join(LOG_DIR, "dsl_execution.log")
MAX_RECURSION = 10
MULTILINE_DELIM = '"""'
MAX_LOG_BYTES = 2_000_000
BACKUP_COUNT = 3

INSERT_PATTERN    = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
MANDATORY_INSERTS: set[str] = {"SYS_INFO"}

dsl_execution_logger = logging.getLogger("dsl_execution")
dsl_script_logger = logging.getLogger("dsl_script")

# if TYPE_CHECKING:
#     from app.models.character import Character # For type hinting

if not any(getattr(h, "name", "") == "dsl_script_simple"
           for h in dsl_script_logger.handlers):
    sh = logging.StreamHandler(sys.stdout)
    sh.name = "dsl_script_simple"
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("%(message)s"))
    dsl_script_logger.addHandler(sh)

dsl_script_logger.propagate = False

if not dsl_execution_logger.handlers:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE, mode="a", encoding="utf-8",
            maxBytes=MAX_LOG_BYTES, backupCount=BACKUP_COUNT
        )
        
        fmt = '%(asctime)s |%(character_id)s| %(name)s - %(levelname)s [%(filename)s:%(lineno)d] - %(message)s'
        formatter = logging.Formatter(fmt)
        file_handler.setFormatter(formatter)
        
        if not any(getattr(h, "name", "") == "dsl_script_simple" for h in dsl_script_logger.handlers):
            simple_handler = logging.StreamHandler(sys.stdout)
            simple_handler.name = "dsl_script_simple"
            simple_handler.setLevel(logging.INFO)
            simple_handler.setFormatter(logging.Formatter("%(message)s"))
            dsl_script_logger.addHandler(simple_handler)
        
        dsl_execution_logger.addHandler(file_handler)
        dsl_execution_logger.setLevel(logging.DEBUG)
        dsl_execution_logger.propagate = False

        dsl_script_logger.addHandler(file_handler)
        dsl_script_logger.setLevel(logging.DEBUG)
        dsl_script_logger.propagate = False
        
    except Exception as e:
        print(f"{RED}CRITICAL: cannot init DSL loggers: {e}{RST}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

class CharacterContextFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self._char_id = "NO_CHAR"

    def set_character_id(self, char_id: str | None):
        self._char_id = char_id or "NO_CHAR"

    def filter(self, record):
        record.character_id = self._char_id
        return True

char_ctx_filter = CharacterContextFilter()
dsl_execution_logger.addFilter(char_ctx_filter)
dsl_script_logger.addFilter(char_ctx_filter)

class DslError(Exception):
    def __init__(
        self,
        message: str,
        script_path: str | None = None, # This can be a relative path, or a resolved ID
        line_num: int | None = None,
        line_content: str | None = None,
        original_exception: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.script_path = script_path
        self.line_num = line_num
        self.line_content = line_content
        self.original_exception = original_exception

        if isinstance(original_exception, TypeError):
            msg = str(original_exception).lower()
            if ("can only concatenate str" in msg) or \
               (("unsupported operand type(s) for +" in msg) and ("str" in msg)):
                self.message += (
                    "  Hint: используйте str(var) при конкатенации строк и чисел. "
                    'Пример: "Score: " + str(score)'
                )
        elif isinstance(original_exception, PathResolverError):
            self.message += f" (Details: {original_exception.message})"
            if original_exception.path and original_exception.path != self.script_path:
                 self.message += f" (Resource: {original_exception.path})"


    def __str__(self):
        loc = ""
        if self.script_path:
            # Use os.path.basename for local paths; for URLs it might not be ideal but works
            loc_display_path = os.path.basename(self.script_path) if isinstance(self.script_path, str) else self.script_path
            loc += f'File "{loc_display_path}"'
            if self.line_num:
                loc += f", line {self.line_num}"
        if self.line_content:
            loc += f'\n  Line: "{self.line_content.strip()}"'
        
        caused_by_msg = ""
        if self.original_exception:
            original_exc_type_name = type(self.original_exception).__name__
            original_exc_msg = str(self.original_exception)
            # Avoid redundant PathResolverError details if already in main message
            if isinstance(self.original_exception, PathResolverError):
                 caused_by_msg = f"\n  Caused by: {original_exc_type_name}" # Message is already incorporated
            else:
                 caused_by_msg = f"\n  Caused by: {original_exc_type_name}: {original_exc_msg}"
        
        return f"DSLError: {self.message}{caused_by_msg}\n  Location: {loc}"

def _split_into_logical_lines(script_text: str) -> list[str]:
    logical_lines: list[str] = []
    buff: list[str] = []
    inside_triple = False
    i = 0
    text = script_text
    n = len(text)
    triple = '"""'

    while i < n:
        if text.startswith(triple, i):
            buff.append(triple)
            inside_triple = not inside_triple
            i += 3
            continue

        ch = text[i]

        if ch == '\n' and not inside_triple:
            logical_lines.append(''.join(buff))
            buff.clear()
            i += 1
            continue

        buff.append(ch)
        i += 1

    if buff:
        logical_lines.append(''.join(buff))

    if inside_triple:
        raise DslError('Unterminated multiline block (""" not closed)')

    return logical_lines

class DslInterpreter:
    placeholder_pattern = re.compile(r"\[<([^\]]+\.(?:script|txt))>]")

    def __init__(self, character: "Character", resolver: AbstractPathResolver):
        self.character = character
        self.resolver = resolver # Store the provided resolver instance
        char_ctx_filter.set_character_id(getattr(character, "char_id", "NO_CHAR_INIT"))
        self._insert_values: dict[str, str] = {}

    @contextmanager
    def _use_base(self, base_dir_resolved_id: str):
        self.resolver.push_base_context(base_dir_resolved_id)
        try:
            yield
        finally:
            self.resolver.pop_base_context()

    def _eval_expr(
        self,
        expr: str,
        script_path_for_error: str,
        line_num: int,
        line_content: str,
    ):
        safe_globals = {
            "__builtins__": {
                "str": str,
                "int": int,
                "float": float,
                "len": len,
                "round": round,
                "abs": abs,
                "max": max,
                "min": min,
                "True": True,
                "False": False,
                "None": None,
            }
        }
        local_vars = self.character.variables.copy()

        def _raise_dsl_error(e: Exception, custom_msg: str = ""):
            err_msg = custom_msg or f"Error evaluating '{expr}': {type(e).__name__} - {e}"
            dsl_script_logger.error(
                f"{err_msg} in script '{os.path.basename(script_path_for_error)}' line {line_num}: \"{line_content.strip()}\"",
                exc_info=True,
            )
            raise DslError(
                err_msg,
                script_path=script_path_for_error,
                line_num=line_num,
                line_content=line_content,
                original_exception=e,
            ) from e

        max_missing_fills = 10
        fills = 0

        while True:
            try:
                if expr.lstrip().startswith(("f'", 'f"', 'f"""')):
                    return eval(expr, safe_globals, local_vars)
                return eval(expr, safe_globals, local_vars)
            except NameError as ne:
                m = re.search(r"name '([^']+)' is not defined", str(ne))
                if not m or fills >= max_missing_fills:
                    _raise_dsl_error(ne)
                var_name = m.group(1)
                dsl_execution_logger.debug(
                    "Auto-initializing unknown variable '%s' with None", var_name
                )
                local_vars[var_name] = None
                fills += 1
                continue
            except TypeError as e:
                msg_lower = str(e).lower()
                is_concat_problem = "can only concatenate str" in msg_lower or (
                    "unsupported operand type(s) for +" in msg_lower and "str" in msg_lower
                )
                if not is_concat_problem:
                    _raise_dsl_error(e)
                dsl_script_logger.debug(
                    "Attempting auto-str cast for TypeError in expression '%s' (%s:%d)",
                    expr,
                    os.path.basename(script_path_for_error),
                    line_num,
                )
                fixed_locals = {
                    k: (str(v) if isinstance(v, (int, float, bool, type(None))) else v)
                    for k, v in local_vars.items()
                }
                try:
                    if expr.lstrip().startswith(("f'", 'f"', 'f"""')):
                        return eval(expr, safe_globals, fixed_locals)
                    return eval(expr, safe_globals, fixed_locals)
                except Exception:
                    _raise_dsl_error(
                        e,
                        f"Error evaluating '{expr}' (even after auto-str cast attempt for TypeError): {type(e).__name__} - {e}",
                    )
            except Exception as e:
                _raise_dsl_error(e)


    def _eval_condition(self, cond: str, script_path_for_error: str, line_num: int, line_content: str):
        py_cond = cond.replace(" AND ", " and ").replace(" OR ", " or ")
        try:
            res = self._eval_expr(py_cond, script_path_for_error, line_num, line_content)
            return bool(res)
        except DslError:
            raise
        except Exception as e:
            dsl_script_logger.error(
                f"Cannot convert condition '{cond}' result to bool in script '{os.path.basename(script_path_for_error)}' line {line_num}: \"{line_content.strip()}\"",
                exc_info=True
            )
            raise DslError(
                f"Cannot convert condition '{cond}' result to bool",
                script_path=script_path_for_error, line_num=line_num, line_content=line_content, original_exception=e
            )

    _INLINE_LOAD_RE = re.compile(
        r"""\bLOAD                      # ключевое слово
             (?:\s+([A-Z0-9_]+))?       # ①  TAG   (опц.)
             \s+FROM\s+                 #   FROM
             (['"])(.+?)\2              # ② "path/to/file"
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    def _expand_inline_loads(
        self,
        expr: str,
        *,
        script_path_for_error: str, # Original script path for context
        line_num: int,
        line_content: str,
    ) -> str:
        def _handle_single(match: re.Match) -> str:
            tag_name = match.group(1)
            rel_path_to_load = match.group(3)
            
            try:
                resolved_path_id = self.resolver.resolve_path(rel_path_to_load)
                
                if tag_name is None:
                    raw = self.resolver.load_text(resolved_path_id, f"inline LOAD in {script_path_for_error}:{line_num}")
                    raw = self._remove_tag_markers(raw)
                else:
                    raw = self._extract_tag_section(resolved_path_id, tag_name, script_path_for_error)

                processed = self.process_template_content(
                    raw,
                    f"inline LOAD ({tag_name or 'FULL'}) FROM {rel_path_to_load} in {os.path.basename(script_path_for_error)}:{line_num}",
                )
                return repr(processed)
            except PathResolverError as pre:
                raise DslError(
                    f"Cannot process inline LOAD for '{rel_path_to_load}': {pre.message}",
                    script_path=script_path_for_error, # Path of the script containing the LOAD
                    line_num=line_num,
                    line_content=line_content,
                    original_exception=pre
                ) from pre
            except DslError: # If _extract_tag_section or process_template_content raises DslError
                raise
            except Exception as e: # Other unexpected errors
                 raise DslError(
                    f"Unexpected error processing inline LOAD for '{rel_path_to_load}': {e}",
                    script_path=script_path_for_error,
                    line_num=line_num,
                    line_content=line_content,
                    original_exception=e
                ) from e


        try:
            return self._INLINE_LOAD_RE.sub(_handle_single, expr)
        except DslError:
            raise
        except Exception as e: # Should be caught by _handle_single, but as a fallback
            raise DslError(
                f"Cannot expand inline LOADs inside expression '{expr}': {e}",
                script_path=script_path_for_error,
                line_num=line_num,
                line_content=line_content,
                original_exception=e,
            ) from e

    def execute_dsl_script(self, rel_script_path: str) -> str:
        resolved_script_id: str = ""
        returned_value_for_log: bool | None = None
        try:
            try:
                resolved_script_id = self.resolver.resolve_path(rel_script_path)
            except PathResolverError as pre:
                raise DslError(
                    message=f"Cannot resolve script path '{rel_script_path}': {pre.message}",
                    script_path=rel_script_path,
                    original_exception=pre
                ) from pre

            script_dirname_id = self.resolver.get_dirname(resolved_script_id)
            with self._use_base(script_dirname_id):
                dsl_execution_logger.info(
                    f"Executing DSL script: {rel_script_path} (resolved: {resolved_script_id})"
                )
                try:
                    content = self.resolver.load_text(resolved_script_id, f"script {rel_script_path}")
                except PathResolverError as pre:
                    raise DslError(
                        message=f"Cannot load script content for '{rel_script_path}': {pre.message}",
                        script_path=resolved_script_id, # Use resolved ID here as it's what failed
                        original_exception=pre
                    ) from pre
                
                logical_lines = _split_into_logical_lines(content)
                if_stack: list[dict[str, Any]] = []
                returned: str | None = None

                for num, raw in enumerate(logical_lines, 1):
                    stripped = raw.strip()
                    if not stripped or stripped.startswith("//"): 
                        continue

                    skipping = any(level["skip"] for level in if_stack)
                    command_part_for_log = stripped.split("//", 1)[0].strip()
                    cmd_for_log = command_part_for_log.split(maxsplit=1)[0].upper()


                    if cmd_for_log == "IF":
                        raw_condition_text = stripped[len("IF"):].strip()
                        
                        comment_start_index = raw_condition_text.find("//")
                        if comment_start_index != -1:
                            condition_without_comment = raw_condition_text[:comment_start_index].strip()
                        else:
                            condition_without_comment = raw_condition_text.strip()

                        if condition_without_comment.upper().endswith(" THEN"):
                            cond_str = condition_without_comment[:-len(" THEN")].strip()
                        else:
                            cond_str = condition_without_comment
                        
                        parent_skip  = skipping
                        cond_met = False
                        if not parent_skip:
                            cond_met = self._eval_condition(cond_str, resolved_script_id, num, raw)
                        dsl_execution_logger.debug(
                            f"IF '{cond_str}' → {cond_met}  ({os.path.basename(rel_script_path)}:{num}), skip={parent_skip}"
                        )
                        if_stack.append({"branch_taken": cond_met, "skip": parent_skip or not cond_met})
                        continue
                    
                    if cmd_for_log == "ELSEIF":
                        if not if_stack: raise DslError("ELSEIF without IF", resolved_script_id, num, raw)
                        lvl = if_stack[-1]
                        parent_skip = any(l["skip"] for l in if_stack[:-1])
                        cond_met_els = False
                        if not parent_skip and not lvl["branch_taken"]:
                            raw_condition_text = stripped[len("ELSEIF"):].strip()

                            comment_start_index = raw_condition_text.find("//")
                            if comment_start_index != -1:
                                condition_without_comment = raw_condition_text[:comment_start_index].strip()
                            else:
                                condition_without_comment = raw_condition_text.strip()

                            if condition_without_comment.upper().endswith(" THEN"):
                                cond_str = condition_without_comment[:-len(" THEN")].strip()
                            else:
                                cond_str = condition_without_comment
                                
                            cond_met_els = self._eval_condition(cond_str, resolved_script_id, num, raw)
                            lvl["branch_taken"] = cond_met_els
                            lvl["skip"] = not cond_met_els
                        else:
                            lvl["skip"] = True
                        dsl_execution_logger.debug(
                            f"ELSEIF, branch_taken={lvl['branch_taken']} skip={lvl['skip']} ({os.path.basename(rel_script_path)}:{num})"
                        )
                        continue

                    if cmd_for_log == "ELSE": 
                        if not if_stack: raise DslError("ELSE without IF", resolved_script_id, num, raw)
                        
                        if command_part_for_log.upper() != "ELSE":
                             raise DslError("ELSE statement should not have conditions or other text on the same line before a comment.", resolved_script_id, num, raw)

                        lvl = if_stack[-1]
                        parent_skip = any(l["skip"] for l in if_stack[:-1])
                        lvl["skip"] = parent_skip or lvl["branch_taken"]
                        if not lvl["skip"]: lvl["branch_taken"] = True 
                        dsl_execution_logger.debug(
                            f"ELSE skip={lvl['skip']} ({os.path.basename(rel_script_path)}:{num})"
                        )
                        continue

                    if cmd_for_log == "ENDIF": 
                        if not if_stack: raise DslError("ENDIF without IF", resolved_script_id, num, raw)
                        if command_part_for_log.upper() != "ENDIF":
                             raise DslError("ENDIF statement should not have other text on the same line before a comment.", resolved_script_id, num, raw)
                        if_stack.pop()
                        dsl_execution_logger.debug(f"ENDIF ({os.path.basename(rel_script_path)}:{num})")
                        continue
                    
                    if skipping: continue 

                    parts = command_part_for_log.split(maxsplit=1)
                    command = parts[0].upper() 
                    args = parts[1] if len(parts) > 1 else ""


                    if command == "SET":
                        if "=" not in args: raise DslError("SET requires '='", resolved_script_id, num, raw)
                        var, expr = [s.strip() for s in args.split("=", 1)]
                        expr = self._expand_inline_loads(expr, script_path_for_error=resolved_script_id, line_num=num, line_content=raw)
                        value = self._eval_expr(expr, resolved_script_id, num, raw)
                        self.character.variables[var] = value
                        dsl_execution_logger.debug(f"SET {var} = {value} ({os.path.basename(rel_script_path)}:{num})")
                        continue

                    if command == "LOG":
                        val = self._eval_expr(args, resolved_script_id, num, raw)
                        prefix = f"{os.path.basename(rel_script_path)}:{num}"
                        message = f"{prefix.ljust(40)}| {val}"
                        dsl_script_logger.info(message)
                        continue
                    
                    if command == "RETURN":
                        raw_arg = args.strip() 
                        raw_arg_expanded = self._expand_inline_loads(raw_arg, script_path_for_error=resolved_script_id, line_num=num, line_content=raw)
                        txt = ""

                        if raw_arg.upper().startswith(("LOAD_REL ", "LOADREL ")):
                            rel_path_to_load = raw_arg.split(None, 1)[1].strip().strip('"').strip("'")
                            try:
                                loaded_path_id = self.resolver.resolve_path(rel_path_to_load)
                                txt = self.resolver.load_text(loaded_path_id, f"LOAD_REL in {rel_script_path}:{num}")
                            except PathResolverError as pre:
                                raise DslError(f"Error in RETURN LOAD_REL '{rel_path_to_load}': {pre.message}", resolved_script_id, num, raw, pre) from pre
                            txt = self._remove_tag_markers(txt)
                        elif raw_arg.upper().startswith("LOAD "):
                            after_load = raw_arg[5:].strip()
                            m = re.match(r"([A-Z0-9_]+)\s+FROM\s+(.+)", after_load, re.IGNORECASE)
                            if m:
                                tag_name = m.group(1).upper()
                                path_str = m.group(2).strip().strip('"').strip("'")
                                try:
                                    loaded_path_id = self.resolver.resolve_path(path_str)
                                    raw_tag = self._extract_tag_section(loaded_path_id, tag_name, resolved_script_id) # Pass current script for context
                                except PathResolverError as pre:
                                    raise DslError(f"Error resolving/loading for RETURN LOAD TAG '{path_str}': {pre.message}", resolved_script_id, num, raw, pre) from pre
                                txt = self.process_template_content(raw_tag, f"LOAD {tag_name} FROM {path_str} in {rel_script_path}:{num}")
                            else:
                                rel_file_to_load = after_load.strip().strip('"').strip("'")
                                try:
                                    loaded_path_id = self.resolver.resolve_path(rel_file_to_load)
                                    txt = self.resolver.load_text(loaded_path_id, f"LOAD in {rel_script_path}:{num}")
                                except PathResolverError as pre:
                                    raise DslError(f"Error in RETURN LOAD '{rel_file_to_load}': {pre.message}", resolved_script_id, num, raw, pre) from pre
                                txt = self._remove_tag_markers(txt)
                        else:
                            txt = str(self._eval_expr(raw_arg_expanded, resolved_script_id, num, raw))
                        
                        returned = self.process_template_content(txt, f"RETURN in {rel_script_path}:{num}")
                        returned_value_for_log = returned is not None
                        dsl_execution_logger.debug(f"RETURN (value exists={returned_value_for_log}) ({os.path.basename(rel_script_path)}:{num})")
                        return returned

                    dsl_execution_logger.error(f"Unknown DSL command '{command}' in {os.path.basename(rel_script_path)}:{num} Line: \"{raw.strip()}\"")
                    raise DslError(f"Unknown DSL command '{command}'", resolved_script_id, num, raw)

                if if_stack:
                    dsl_execution_logger.warning(f"Script {rel_script_path} ended with unterminated IF block(s).")
                
                returned_value_for_log = returned is not None
                return returned or ""

        except DslError as e:
            dsl_execution_logger.error(
                f"DslError during execution of {rel_script_path} (resolved: {e.script_path or resolved_script_id}): {e.message} at line {e.line_num}",
                exc_info=False, 
            )
            print(f"{RED}{str(e)}{RST}", file=sys.stderr)
            return f"[DSL ERROR IN {os.path.basename(e.script_path or resolved_script_id or rel_script_path)}]"
        except Exception as e:
            dsl_execution_logger.error(
                f"Unexpected Python error during execution of {rel_script_path} (resolved: {resolved_script_id}): {e}",
                exc_info=True,
            )
            print(f"{RED}Unexpected Python error in {rel_script_path}: {e}{RST}\n{traceback.format_exc()}", file=sys.stderr)
            return f"[PY ERROR IN {os.path.basename(resolved_script_id or rel_script_path)}]"
        finally:
            dsl_execution_logger.info(
                f"Finished DSL script: {rel_script_path}. Returned value: {returned_value_for_log if returned_value_for_log is not None else False}"
            )

    def process_template_content(self, text: str, ctx="template") -> str:
        if not isinstance(text, str): text = str(text)
        depth = 0
        original_text_for_recursion_check = text

        while self.placeholder_pattern.search(text) and depth < MAX_RECURSION:
            depth += 1
            def repl(match):
                rel_path_placeholder = match.group(1)
                dsl_execution_logger.debug(f"Processing placeholder: {rel_path_placeholder} in context '{ctx}', depth {depth}")
                try:
                    resolved_placeholder_id = self.resolver.resolve_path(rel_path_placeholder)
                    placeholder_dirname_id = self.resolver.get_dirname(resolved_placeholder_id)
                    with self._use_base(placeholder_dirname_id):
                        if rel_path_placeholder.endswith(".script"):
                            return self.execute_dsl_script(rel_path_placeholder) # execute_dsl_script expects relative path
                        if rel_path_placeholder.endswith(".txt"):
                            raw_txt = self.resolver.load_text(resolved_placeholder_id, f"placeholder {rel_path_placeholder} in {ctx}")
                            return self.process_template_content(raw_txt, f"{rel_path_placeholder} (recursive from {ctx})")
                        
                        dsl_execution_logger.error(f"Unknown placeholder type: {rel_path_placeholder} in {ctx}")
                        raise DslError("Unknown placeholder type", script_path=rel_path_placeholder) # Pass rel_path here
                except PathResolverError as pre:
                    dsl_execution_logger.error(f"PathResolverError for placeholder '{rel_path_placeholder}' in {ctx}: {pre.message}")
                    print(f"{RED}Error processing placeholder {rel_path_placeholder}: {pre}{RST}", file=sys.stderr)
                    return f"[PATH ERROR {rel_path_placeholder}]"
                except DslError as de:
                    dsl_execution_logger.error(f"DSL ERROR while processing placeholder {rel_path_placeholder} in {ctx}: {de}")
                    print(f"{RED}Error processing placeholder {rel_path_placeholder}: {de}{RST}", file=sys.stderr)
                    return f"[DSL ERROR {rel_path_placeholder}]" # de.script_path should be rel_path_placeholder
                except Exception as exc:
                    dsl_execution_logger.error(f"Unexpected Python error processing placeholder {rel_path_placeholder} in {ctx}: {exc}", exc_info=True)
                    print(f"{RED}Unexpected Python error in placeholder {rel_path_placeholder}: {exc}{RST}\n{traceback.format_exc()}", file=sys.stderr)
                    return f"[PY ERROR {rel_path_placeholder}]"

            processed_text = self.placeholder_pattern.sub(repl, text)
            if processed_text == text and self.placeholder_pattern.search(text):
                dsl_execution_logger.error(
                    f"Template processing stalled at depth {depth} in context '{ctx}'. Unresolved: {self.placeholder_pattern.search(text).group(0)}"
                )
                text = self.placeholder_pattern.sub(f"[STALLED DSL ERROR {self.placeholder_pattern.search(text).group(1)}]", text, count=1)
            else:
                text = processed_text
            
            if depth == MAX_RECURSION -1 and self.placeholder_pattern.search(text):
                 dsl_execution_logger.warning(
                    f"Nearing max recursion depth ({depth+1}/{MAX_RECURSION}) in '{ctx}'. Next: {self.placeholder_pattern.search(text).group(0)}"
                )

        if depth >= MAX_RECURSION:
            dsl_execution_logger.error(f"Max recursion depth ({MAX_RECURSION}) reached in '{ctx}'. Original: '{original_text_for_recursion_check[:100]}...'")
            text += f"\n[DSL ERROR: MAX RECURSION {MAX_RECURSION} REACHED IN '{ctx}']"
        return text

    def set_insert(self, name: str, content: Any | None):
        if content is None: return
        if isinstance(content, (list, tuple)): content = "\n".join(map(str, content))
        self._insert_values[name.upper()] = str(content)

    def _apply_inserts(self, text: str, *, ctx: str = "") -> str:
        def _replace(match: re.Match):
            placeholder = match.group(1).upper()
            return self._insert_values.get(placeholder, match.group(0))
        processed = INSERT_PATTERN.sub(_replace, text)
        for mandatory in MANDATORY_INSERTS:
            token = f"{{{{{mandatory}}}}}"
            if token not in text: # Check original text, not processed one for this warning
                dsl_execution_logger.warning(f"Mandatory insert {token} not found while processing {ctx or 'template'}")
        return processed

    _SECTION_MARKER_RE = re.compile(r"^[ \t]*\[(?:#|/)\s*[A-Z0-9_]+\s*][ \t]*\r?\n?", re.IGNORECASE | re.MULTILINE)

    def _remove_tag_markers(self, text: str) -> str:
        return self._SECTION_MARKER_RE.sub("", text)

    def _extract_tag_section(self, resolved_path_id: str, tag_name: str, script_path_for_error_context: str) -> str:
        try:
            raw = self.resolver.load_text(resolved_path_id, f"extract tag {tag_name} for {script_path_for_error_context}")
        except PathResolverError as pre:
            raise DslError(
                f"Cannot load file to extract tag section [#{tag_name}] from '{resolved_path_id}': {pre.message}",
                script_path=script_path_for_error_context, # Path of the script that tried to load the tag
                original_exception=pre
            ) from pre

        tag_up  = tag_name.upper()
        pattern = re.compile(rf"\[#\s*{tag_up}\s*](.*?)\[/\s*{tag_up}\s*]", re.IGNORECASE | re.DOTALL)
        m = pattern.search(raw)
        if not m:
            raise DslError(
                f"Tag section [#{tag_name}] not found in '{resolved_path_id}' (loaded for {script_path_for_error_context})",
                script_path=resolved_path_id, # Path of the file where tag was expected
            )
        content = m.group(1)
        if content.startswith("\n"): content = content[1:]
        return content

    def process_main_template_file(self, rel_path_main_template: str) -> str:
        resolved_main_template_id: str = ""
        try:
            char_ctx_filter.set_character_id(getattr(self.character, "char_id", "NO_CHAR_CTX"))
            dsl_execution_logger.info(f"Processing main template file: {rel_path_main_template} for character {self.character.char_id}")
            
            try:
                resolved_main_template_id = self.resolver.resolve_path(rel_path_main_template)
            except PathResolverError as pre:
                raise DslError(
                    message=f"Cannot resolve main template path '{rel_path_main_template}': {pre.message}",
                    script_path=rel_path_main_template,
                    original_exception=pre
                ) from pre
            
            try:
                raw_template_content = self.resolver.load_text(resolved_main_template_id, f"main template {rel_path_main_template}")
            except PathResolverError as pre:
                 raise DslError(
                    message=f"Cannot load main template content for '{rel_path_main_template}': {pre.message}",
                    script_path=resolved_main_template_id,
                    original_exception=pre
                ) from pre

            final_prompt = self.process_template_content(raw_template_content, f"main template {rel_path_main_template}")
            final_prompt = self._apply_inserts(final_prompt, ctx=f"main template {rel_path_main_template}")
            dsl_execution_logger.info(f"Successfully processed main template: {rel_path_main_template}")
            return final_prompt
        except DslError as e:
            dsl_execution_logger.error(f"DslError while processing main template '{rel_path_main_template}' (resolved: {e.script_path or resolved_main_template_id}): {e.message}", exc_info=False)
            print(f"{RED}{str(e)}{RST}", file=sys.stderr)
            return f"[DSL ERROR IN MAIN TEMPLATE {os.path.basename(e.script_path or resolved_main_template_id or rel_path_main_template)} - CHECK LOGS]"
        except Exception as e:
            dsl_execution_logger.error(f"Unexpected Python error processing main template '{rel_path_main_template}' (resolved: {resolved_main_template_id}): {e}", exc_info=True)
            print(f"{RED}Unexpected Python error in main template {rel_path_main_template}: {e}{RST}\n{traceback.format_exc()}", file=sys.stderr)
            return f"[PY ERROR IN MAIN TEMPLATE {os.path.basename(resolved_main_template_id or rel_path_main_template)} - CHECK LOGS]"