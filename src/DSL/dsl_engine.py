# File: src/DSL/dsl_engine.py
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import sys
import traceback
from typing import List, Any, Dict, Optional, Tuple
from contextlib import contextmanager

LOG_DIR = "Logs"
RED = "\033[91m"
YEL = "\033[93m"
AQUA = "\033[96m"
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
        script_path: str | None = None,
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

    def __str__(self):
        loc = ""
        if self.script_path:
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
    placeholder_pattern = re.compile(r"\[<([^>]+\.(?:script|txt|system))>\]")
    _TXT_VAR_RE = re.compile(r"\[\{([A-Za-z_][A-Za-z0-9_]*)\}\]")

    def __init__(self, character: "Character", resolver):
        self.character = character
        self.resolver = resolver
        self._insert_values: dict[str, str] = {}
        self._local_vars: dict[str, Any] = {}
        self._declared_local_vars: set[str] = set()

    @contextmanager
    def _use_base(self, base_dir_resolved_id: str):
        push = getattr(self.resolver, "push_base_context", None)
        pop = getattr(self.resolver, "pop_base_context", None)
        if callable(push):
            self.resolver.push_base_context(base_dir_resolved_id)
        try:
            yield
        finally:
            if callable(pop):
                self.resolver.pop_base_context()

    def _eval_expr(
        self,
        expr: str,
        script_path_for_error: str,
        line_num: int,
        line_content: str,
        sys_msgs: Optional[List[str]] = None,
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
        combined_vars = {**self.character.variables, **getattr(self.character, "app_vars", {}), **self._local_vars}

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
                expr_to_eval = self._expand_inline_loads(expr, script_path_for_error=script_path_for_error, line_num=line_num, line_content=line_content, sys_msgs=sys_msgs)
                if expr_to_eval.lstrip().startswith(("f'", 'f"', 'f"""')):
                    return eval(expr_to_eval, safe_globals, combined_vars)
                return eval(expr_to_eval, safe_globals, combined_vars)
            except NameError as ne:
                m = re.search(r"name '([^']+)' is not defined", str(ne))
                if not m or fills >= max_missing_fills:
                    _raise_dsl_error(ne)
                var_name = m.group(1)
                dsl_execution_logger.debug("Auto-initializing unknown variable '%s' with None in local scope", var_name)
                self._local_vars[var_name] = None
                combined_vars[var_name] = None
                fills += 1
                continue
            except TypeError as e:
                msg_lower = str(e).lower()
                is_concat_problem = "can only concatenate str" in msg_lower or ("unsupported operand type(s) for +" in msg_lower and "str" in msg_lower)
                if not is_concat_problem:
                    _raise_dsl_error(e)
                dsl_script_logger.debug(
                    "Attempting auto-str cast for TypeError in expression '%s' (%s:%d)",
                    expr,
                    os.path.basename(script_path_for_error),
                    line_num,
                )
                fixed_locals = {k: (str(v) if isinstance(v, (int, float, bool, type(None))) else v) for k, v in combined_vars.items()}
                try:
                    if expr_to_eval.lstrip().startswith(("f'", 'f"', 'f"""')):
                        return eval(expr_to_eval, safe_globals, fixed_locals)
                    return eval(expr_to_eval, safe_globals, fixed_locals)
                except Exception:
                    _raise_dsl_error(e, f"Error evaluating '{expr_to_eval}' (even after auto-str cast attempt for TypeError): {type(e).__name__} - {e}")
            except Exception as e:
                _raise_dsl_error(e)

    def _eval_condition(self, cond: str, script_path_for_error: str, line_num: int, line_content: str, sys_msgs: Optional[List[str]] = None):
        py_cond = cond.replace(" AND ", " and ").replace(" OR ", " or ")
        try:
            res = self._eval_expr(py_cond, script_path_for_error, line_num, line_content, sys_msgs=sys_msgs)
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
        r"""\bLOAD
             (?:\s+([A-Z0-9_]+))?
             \s+FROM\s+
             (['"])(.+?)\2
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    def _expand_inline_loads(
        self,
        expr: str,
        *,
        script_path_for_error: str,
        line_num: int,
        line_content: str,
        sys_msgs: Optional[List[str]] = None,
    ) -> str:
        def _handle_single(match: re.Match) -> str:
            tag_name = match.group(1)
            rel_path_to_load = match.group(3)

            try:
                resolved_path_id = self.resolver.resolve_path(rel_path_to_load)

                if tag_name is None:
                    raw = self.resolver.load_text(resolved_path_id, f"inline LOAD in {script_path_for_error}:{line_num}")
                    raw = self._remove_tag_markers(raw)
                    processed = self.process_template_content(raw, f"inline LOAD FULL FROM {rel_path_to_load} in {os.path.basename(script_path_for_error)}:{line_num}", sys_msgs=sys_msgs)
                else:
                    raw = self._extract_tag_section(resolved_path_id, tag_name, script_path_for_error)
                    processed = self.process_template_content(raw, f"inline LOAD {tag_name} FROM {rel_path_to_load} in {os.path.basename(script_path_for_error)}:{line_num}", sys_msgs=sys_msgs)

                return repr(processed)
            except DslError:
                raise
            except Exception as e:
                raise DslError(
                    f"Cannot process inline LOAD for '{rel_path_to_load}': {e}",
                    script_path_for_error, line_num, line_content, e
                ) from e

        try:
            return self._INLINE_LOAD_RE.sub(_handle_single, expr)
        except DslError:
            raise
        except Exception as e:
            raise DslError(
                f"Cannot expand inline LOADs inside expression '{expr}': {e}",
                script_path_for_error,
                line_num,
                line_content,
                e,
            ) from e

    def process_script(self, rel_script_path: str, sys_msgs: Optional[List[str]] = None) -> Tuple[str, List[str]]:
        if sys_msgs is None:
            sys_msgs = []

        self._local_vars.clear()
        self._declared_local_vars.clear()

        resolved_script_id: str = ""
        returned_value_for_log: bool | None = None
        try:
            try:
                resolved_script_id = self.resolver.resolve_path(rel_script_path)
            except Exception as pre:
                raise DslError(
                    message=f"Cannot resolve script path '{rel_script_path}': {pre}",
                    script_path=rel_script_path,
                    original_exception=pre
                ) from pre

            script_dirname_id = self.resolver.get_dirname(resolved_script_id)
            with self._use_base(script_dirname_id):
                dsl_execution_logger.info(f"Executing DSL script: {rel_script_path} (resolved: {resolved_script_id})")
                try:
                    content = self.resolver.load_text(resolved_script_id, f"script {rel_script_path}")
                except Exception as pre:
                    raise DslError(
                        message=f"Cannot load script content for '{rel_script_path}': {pre}",
                        script_path=resolved_script_id,
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
                            cond_met = self._eval_condition(cond_str, resolved_script_id, num, raw, sys_msgs=sys_msgs)
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

                            cond_met_els = self._eval_condition(cond_str, resolved_script_id, num, raw, sys_msgs=sys_msgs)
                            lvl["branch_taken"] = cond_met_els
                            lvl["skip"] = not cond_met_els
                        else:
                            lvl["skip"] = True
                        continue

                    if cmd_for_log == "ELSE":
                        if not if_stack: raise DslError("ELSE without IF", resolved_script_id, num, raw)
                        if command_part_for_log.upper() != "ELSE":
                            raise DslError("ELSE statement should not have conditions or other text on the same line before a comment.", resolved_script_id, num, raw)
                        lvl = if_stack[-1]
                        parent_skip = any(l["skip"] for l in if_stack[:-1])
                        lvl["skip"] = parent_skip or lvl["branch_taken"]
                        if not lvl["skip"]: lvl["branch_taken"] = True
                        continue

                    if cmd_for_log == "ENDIF":
                        if not if_stack: raise DslError("ENDIF without IF", resolved_script_id, num, raw)
                        if command_part_for_log.upper() != "ENDIF":
                            raise DslError("ENDIF statement should not have other text on the same line before a comment.", resolved_script_id, num, raw)
                        if_stack.pop()
                        continue

                    if skipping: 
                        continue

                    parts = command_part_for_log.split(maxsplit=1)
                    command = parts[0].upper()
                    args = parts[1] if len(parts) > 1 else ""

                    if command == "SET":
                        if "=" not in args: raise DslError("SET requires '='", resolved_script_id, num, raw)

                        is_local = False
                        var = ""
                        expr = ""

                        parts_after_set = args.split(maxsplit=1)
                        if len(parts_after_set) > 1 and parts_after_set[0].upper() == "LOCAL":
                            is_local = True
                            remaining_args = parts_after_set[1]
                            if "=" in remaining_args:
                                var, expr = [s.strip() for s in remaining_args.split("=", 1)]
                            else:
                                raise DslError("Malformed SET LOCAL command. Missing '='.", resolved_script_id, num, raw)

                            if var in self._local_vars:
                                continue
                        else:
                            if "=" in args:
                                var, expr = [s.strip() for s in args.split("=", 1)]
                            else:
                                raise DslError("Malformed SET command. Missing '='.", resolved_script_id, num, raw)

                        value = self._eval_expr(expr, resolved_script_id, num, raw, sys_msgs=sys_msgs)

                        if is_local:
                            self._declared_local_vars.add(var)
                            self._local_vars[var] = value
                        else:
                            if var in self._declared_local_vars:
                                self._local_vars[var] = value
                            else:
                                self.character.variables[var] = value
                        continue

                    if command == "ADD_SYSTEM_INFO":
                        if not args:
                            raise DslError("ADD_SYSTEM_INFO requires an argument (expression or LOAD command).", resolved_script_id, num, raw)

                        content_to_add = ""
                        raw_arg = args.strip()

                        if raw_arg.upper().startswith(("LOAD_REL ", "LOADREL ")):
                            rel_path_to_load = raw_arg.split(None, 1)[1].strip().strip('"').strip("'")
                            try:
                                content_to_add, _ = self.process_file(rel_path_to_load, sys_msgs=sys_msgs)
                            except DslError as de:
                                raise DslError(f"Error in ADD_SYSTEM_INFO LOAD_REL '{rel_path_to_load}': {de.message}", resolved_script_id, num, raw, de) from de
                            except Exception as e:
                                raise DslError(f"Unexpected error in ADD_SYSTEM_INFO LOAD_REL '{rel_path_to_load}': {e}", resolved_script_id, num, raw, e) from e
                        elif raw_arg.upper().startswith("LOAD "):
                            after_load = raw_arg[5:].strip()
                            m = re.match(r"([A-Z0-9_]+)\s+FROM\s+(.+)", after_load, re.IGNORECASE)
                            if m:
                                tag_name = m.group(1).upper()
                                path_str = m.group(2).strip().strip('"').strip("'")
                                try:
                                    loaded_path_id = self.resolver.resolve_path(path_str)
                                    raw_tag = self._extract_tag_section(loaded_path_id, tag_name, resolved_script_id)
                                    content_to_add = self.process_template_content(raw_tag, f"ADD_SYSTEM_INFO LOAD {tag_name} FROM {path_str} in {rel_script_path}:{num}", sys_msgs=sys_msgs)
                                except DslError as de:
                                    raise DslError(f"Error resolving/loading for ADD_SYSTEM_INFO LOAD TAG '{path_str}': {de.message}", resolved_script_id, num, raw, de) from de
                                except Exception as e:
                                    raise DslError(f"Unexpected error in ADD_SYSTEM_INFO LOAD TAG '{path_str}': {e}", resolved_script_id, num, raw, e) from e
                            else:
                                rel_file_to_load = after_load.strip().strip('"').strip("'")
                                try:
                                    content_to_add, _ = self.process_file(rel_file_to_load, sys_msgs=sys_msgs)
                                except DslError as de:
                                    raise DslError(f"Error in ADD_SYSTEM_INFO LOAD '{rel_file_to_load}': {de.message}", resolved_script_id, num, raw, de) from de
                                except Exception as e:
                                    raise DslError(f"Unexpected error in ADD_SYSTEM_INFO LOAD '{rel_file_to_load}': {e}", resolved_script_id, num, raw, e) from e
                        else:
                            content_to_add = str(self._eval_expr(raw_arg, resolved_script_id, num, raw, sys_msgs=sys_msgs))

                        if content_to_add and content_to_add.strip():
                            sys_msgs.append(content_to_add)
                        continue

                    if command == "LOG":
                        try:
                            val = self._eval_expr(args, resolved_script_id, num, raw, sys_msgs=sys_msgs)
                            prefix = f"{os.path.basename(rel_script_path)}:{num}"
                            message = f"{prefix.ljust(40)}| {val}"
                            dsl_script_logger.info(f"{AQUA}{message}{RST}")
                        except Exception:
                            pass
                        continue

                    if command == "RETURN":
                        raw_arg = args.strip()
                        txt = ""

                        if raw_arg.upper().startswith(("LOAD_REL ", "LOADREL ")):
                            rel_path_to_load = raw_arg.split(None, 1)[1].strip().strip('"').strip("'")
                            try:
                                loaded_path_id = self.resolver.resolve_path(rel_path_to_load)
                                txt = self.resolver.load_text(loaded_path_id, f"LOAD_REL in {rel_script_path}:{num}")
                            except Exception as pre:
                                raise DslError(f"Error in RETURN LOAD_REL '{rel_path_to_load}': {pre}", resolved_script_id, num, raw, pre) from pre
                            txt = self._remove_tag_markers(txt)
                        elif raw_arg.upper().startswith("LOAD "):
                            after_load = raw_arg[5:].strip()
                            m = re.match(r"([A-Z0-9_]+)\s+FROM\s+(.+)", after_load, re.IGNORECASE)
                            if m:
                                tag_name = m.group(1).upper()
                                path_str = m.group(2).strip().strip('"').strip("'")
                                try:
                                    loaded_path_id = self.resolver.resolve_path(path_str)
                                    raw_tag = self._extract_tag_section(loaded_path_id, tag_name, resolved_script_id)
                                except Exception as pre:
                                    raise DslError(f"Error resolving/loading for RETURN LOAD TAG '{path_str}': {pre}", resolved_script_id, num, raw, pre) from pre
                                txt = self.process_template_content(raw_tag, f"LOAD {tag_name} FROM {path_str} in {rel_script_path}:{num}", sys_msgs=sys_msgs)
                            else:
                                rel_file_to_load = after_load.strip().strip('"').strip("'")
                                try:
                                    loaded_path_id = self.resolver.resolve_path(rel_file_to_load)
                                    txt = self.resolver.load_text(loaded_path_id, f"LOAD in {rel_script_path}:{num}")
                                except Exception as pre:
                                    raise DslError(f"Error in RETURN LOAD '{rel_file_to_load}': {pre}", resolved_script_id, num, raw, pre) from pre
                                txt = self._remove_tag_markers(txt)
                        else:
                            txt = str(self._eval_expr(raw_arg, resolved_script_id, num, raw, sys_msgs=sys_msgs))

                        returned = self.process_template_content(txt, f"RETURN in {rel_script_path}:{num}", sys_msgs=sys_msgs)
                        returned_value_for_log = returned is not None
                        return (returned or "", sys_msgs)

                    if command == "SEED_MEMORY":
                        if not args or "|" not in args:
                            raise DslError("SEED_MEMORY requires format: SEED_MEMORY priority | content [ENTITIES e1, e2]", resolved_script_id, num, raw)
                        entities = []
                        raw_args = args
                        upper_args = args.upper()
                        if " ENTITIES " in upper_args:
                            ent_idx = upper_args.index(" ENTITIES ")
                            entities_str = args[ent_idx + len(" ENTITIES "):]
                            raw_args = args[:ent_idx]
                            entities = [e.strip() for e in entities_str.split(",") if e.strip()]
                        if "|" not in raw_args:
                            raise DslError("SEED_MEMORY requires format: SEED_MEMORY priority | content [ENTITIES e1, e2]", resolved_script_id, num, raw)
                        parts = raw_args.split("|", 1)
                        priority = parts[0].strip()
                        content = self._eval_expr(f'f"""{parts[1].strip()}"""', resolved_script_id, num, raw, sys_msgs=sys_msgs) if '{' in parts[1] else parts[1].strip()
                        if content and hasattr(self.character, "memory_system") and self.character.memory_system:
                            self.character.memory_system.add_memory(
                                str(content), priority=priority, skip_if_exists=True,
                                entities=entities if entities else None
                            )
                        continue

                    if command == "LINK_ENTITIES":
                        parts = [p.strip() for p in args.split("->")]
                        if len(parts) != 3:
                            raise DslError("LINK_ENTITIES requires format: entity1 -> relation -> entity2", resolved_script_id, num, raw)
                        entity1, relation, entity2 = parts
                        mem_sys = getattr(self.character, "memory_system", None)
                        rag = getattr(mem_sys, "rag", None) if mem_sys else None
                        if rag and entity1 and entity2 and relation:
                            try:
                                from managers.rag.graph.graph_store import GraphStore
                                gs = GraphStore(rag.db, rag.character_id)
                                sid = gs.upsert_entity(entity1)
                                oid = gs.upsert_entity(entity2)
                                gs.upsert_relation(sid, relation, oid)
                            except Exception as _link_err:
                                import logging as _logging
                                _logging.warning(f"LINK_ENTITIES failed (ignored): {_link_err}")
                        continue

                    raise DslError(f"Unknown DSL command '{command}'", resolved_script_id, num, raw)

                if if_stack:
                    dsl_execution_logger.warning(f"Script {rel_script_path} ended with unterminated IF block(s).")

                returned_value_for_log = (returned is not None)
                return (returned or "", sys_msgs)

        except DslError as e:
            dsl_execution_logger.error(
                f"DslError during execution of {rel_script_path} (resolved: {e.script_path or resolved_script_id}): {e.message} at line {e.line_num}",
                exc_info=False,
            )
            print(f"{RED}{str(e)}{RST}", file=sys.stderr)
            return (f"[DSL ERROR IN {os.path.basename(e.script_path or resolved_script_id or rel_script_path)}]", sys_msgs)
        except Exception as e:
            dsl_execution_logger.error(
                f"Unexpected Python error during execution of {rel_script_path} (resolved: {resolved_script_id}): {e}",
                exc_info=True,
            )
            print(f"{RED}Unexpected Python error in {rel_script_path}: {e}{RST}\n{traceback.format_exc()}", file=sys.stderr)
            return (f"[PY ERROR IN {os.path.basename(resolved_script_id or rel_script_path)}]", sys_msgs)
        finally:
            dsl_execution_logger.info(
                f"Finished DSL script: {rel_script_path}. Returned value: {returned_value_for_log if returned_value_for_log is not None else False}"
            )

    def process_template_content(self, text: str, ctx: str = "template", sys_msgs: Optional[List[str]] = None) -> str:
        if sys_msgs is None:
            sys_msgs = []
        if not isinstance(text, str):
            text = str(text)
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
                        if rel_path_placeholder.endswith(".script") or rel_path_placeholder.endswith(".system"):
                            content, _ = self.process_script(rel_path_placeholder, sys_msgs=sys_msgs)
                            return content
                        if rel_path_placeholder.endswith(".txt"):
                            content, _ = self.process_file(rel_path_placeholder, sys_msgs=sys_msgs)
                            return content
                        raise DslError("Unknown placeholder type", script_path=rel_path_placeholder)
                except DslError as de:
                    dsl_execution_logger.error(f"DSL ERROR while processing placeholder {rel_path_placeholder} in {ctx}: {de}")
                    print(f"{RED}Error processing placeholder {rel_path_placeholder}: {de}{RST}", file=sys.stderr)
                    return f"[DSL ERROR {rel_path_placeholder}]"
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

            if depth == MAX_RECURSION - 1 and self.placeholder_pattern.search(text):
                 dsl_execution_logger.warning(
                    f"Nearing max recursion depth ({depth+1}/{MAX_RECURSION}) in '{ctx}'. Next: {self.placeholder_pattern.search(text).group(0)}"
                )

        if depth >= MAX_RECURSION:
            dsl_execution_logger.error(f"Max recursion depth ({MAX_RECURSION}) reached in '{ctx}'. Original: '{original_text_for_recursion_check[:100]}...'")
            text += f"\n[DSL ERROR: MAX RECURSION {MAX_RECURSION} REACHED IN '{ctx}']"

        return text

    def set_insert(self, name: str, content: Any | None):
        if content is None: 
            return
        if isinstance(content, (list, tuple)): 
            content = "\n".join(map(str, content))
        self._insert_values[name.upper()] = str(content)

    def _apply_inserts(self, text: str, *, ctx: str = "") -> str:
        def _replace(match: re.Match):
            placeholder = match.group(1).upper()
            return self._insert_values.get(placeholder, match.group(0))
        processed = INSERT_PATTERN.sub(_replace, text)
        for mandatory in MANDATORY_INSERTS:
            token = f"{{{{{mandatory}}}}}"
            if token not in text:
                dsl_execution_logger.warning(f"Mandatory insert {token} not found while processing {ctx or 'template'}")
        return processed

    _SECTION_MARKER_RE = re.compile(
        r"^[ \t]*\[(?:#|/)\s*[A-Z0-9_]+\s*\][ \t]*\r?\n?",
        re.IGNORECASE | re.MULTILINE
    )

    def _remove_tag_markers(self, text: str) -> str:
        return self._SECTION_MARKER_RE.sub("", text)

    def _extract_tag_section(self, resolved_path_id: str, tag_name: str, script_path_for_error_context: str) -> str:
        try:
            raw = self.resolver.load_text(resolved_path_id, f"extract tag {tag_name} for {script_path_for_error_context}")
        except Exception as pre:
            raise DslError(
                f"Cannot load file to extract tag section [#{tag_name}] from '{resolved_path_id}': {pre}",
                script_path=script_path_for_error_context,
                original_exception=pre
            ) from pre

        tag_up  = tag_name.upper()
        pattern = re.compile(
            rf"\[#\s*{tag_up}\s*\](.*?)\s*\[/\s*{tag_up}\s*\]",
            re.IGNORECASE | re.DOTALL
        )
        m = pattern.search(raw)
        if not m:
            raise DslError(
                f"Tag section [#{tag_name}] not found in '{resolved_path_id}' (loaded for {script_path_for_error_context})",
                script_path=resolved_path_id,
            )
        content = m.group(1)
        if content.startswith("\n"): 
            content = content[1:]
        return content

    def process_main_template(self, rel_path_main_template: str) -> tuple[List[str], List[str]]:
        blocks: List[str] = []
        sys_msgs: List[str] = []
        resolved_main_template_id: str = ""

        try:
            char_ctx_filter.set_character_id(getattr(self.character, "char_id", "NO_CHAR_CTX"))
            dsl_execution_logger.info(f"Processing main template file: {rel_path_main_template} for character {getattr(self.character, 'char_id', 'NO_CHAR')}")

            try:
                resolved_main_template_id = self.resolver.resolve_path(rel_path_main_template)
            except Exception as pre:
                raise DslError(
                    message=f"Cannot resolve main template path '{rel_path_main_template}': {pre}",
                    script_path=rel_path_main_template,
                    original_exception=pre
                ) from pre

            try:
                raw_template_content = self.resolver.load_text(resolved_main_template_id, f"main template {rel_path_main_template}")
            except Exception as pre:
                 raise DslError(
                    message=f"Cannot load main template content for '{rel_path_main_template}': {pre}",
                    script_path=resolved_main_template_id,
                    original_exception=pre
                ) from pre

            file_paths_in_template = self.placeholder_pattern.findall(raw_template_content)

            for rel_file_path in file_paths_in_template:
                try:
                    content, _ = self.process_file(rel_file_path, sys_msgs=sys_msgs)
                    if content and content.strip():
                        blocks.append(content)
                except DslError as de:
                    dsl_execution_logger.error(f"DslError while processing included file '{rel_file_path}' in main template: {de.message}", exc_info=False)
                    blocks.append(f"[DSL ERROR IN {os.path.basename(de.script_path or rel_file_path)}]")
                except Exception as e:
                    dsl_execution_logger.error(f"Unexpected Python error processing included file '{rel_file_path}' in main template: {e}", exc_info=True)
                    blocks.append(f"[PY ERROR IN {os.path.basename(rel_file_path)}]")

            dsl_execution_logger.info(f"Successfully processed main template: {rel_path_main_template}")
            return (blocks, sys_msgs)
        except DslError as e:
            dsl_execution_logger.error(f"DslError while processing main template '{rel_path_main_template}' (resolved: {e.script_path or resolved_main_template_id}): {e.message}", exc_info=False)
            print(f"{RED}{str(e)}{RST}", file=sys.stderr)
            return ([f"[DSL ERROR IN MAIN TEMPLATE {os.path.basename(e.script_path or resolved_main_template_id or rel_path_main_template)}]"], sys_msgs)
        except Exception as e:
            dsl_execution_logger.error(f"Unexpected Python error processing main template '{rel_path_main_template}' (resolved: {resolved_main_template_id}): {e}", exc_info=True)
            print(f"{RED}Unexpected Python error in main template {rel_path_main_template}: {e}{RST}\n{traceback.format_exc()}", file=sys.stderr)
            return ([f"[PY ERROR IN MAIN TEMPLATE {os.path.basename(resolved_main_template_id or rel_path_main_template)}]"], sys_msgs)

    def process_file(self, rel_file_path: str, sys_msgs: Optional[List[str]] = None) -> tuple[str, List[str]]:
        if sys_msgs is None:
            sys_msgs = []
        resolved_file_id: str = ""

        try:
            char_ctx_filter.set_character_id(getattr(self.character, "char_id", "NO_CHAR_CTX"))
            dsl_execution_logger.info(f"Processing individual file: {rel_file_path} for character {getattr(self.character, 'char_id', 'NO_CHAR')}")

            try:
                resolved_file_id = self.resolver.resolve_path(rel_file_path)
            except Exception as pre:
                raise DslError(
                    message=f"Cannot resolve file path '{rel_file_path}': {pre}",
                    script_path=rel_file_path,
                    original_exception=pre
                ) from pre

            if rel_file_path.endswith(".script") or rel_file_path.endswith(".system"):
                content, _ = self.process_script(rel_file_path, sys_msgs=sys_msgs)
            elif rel_file_path.endswith(".txt"):
                try:
                    _ = self.resolver.load_text(resolved_file_id, f"individual file {rel_file_path}")  # проверка наличия
                except Exception as pre:
                    raise DslError(
                        message=f"Cannot load file content for '{rel_file_path}': {pre}",
                        script_path=resolved_file_id,
                        original_exception=pre
                    ) from pre
                content, _ = self.process_txt(rel_file_path, sys_msgs=sys_msgs)
            else:
                raise DslError(f"Unsupported file type for individual processing: {rel_file_path}", script_path=rel_file_path)

            dsl_execution_logger.info(f"Successfully processed individual file: {rel_file_path}")
            return (content, sys_msgs)
        except DslError as e:
            dsl_execution_logger.error(f"DslError while processing individual file '{rel_file_path}' (resolved: {e.script_path or resolved_file_id}): {e.message}", exc_info=False)
            print(f"{RED}{str(e)}{RST}", file=sys.stderr)
            return (f"[DSL ERROR IN FILE {os.path.basename(e.script_path or resolved_file_id or rel_file_path)}]", sys_msgs)
        except Exception as e:
            dsl_execution_logger.error(f"Unexpected Python error processing individual file '{rel_file_path}' (resolved: {resolved_file_id}): {e}", exc_info=True)
            print(f"{RED}Unexpected Python error in file {rel_file_path}: {e}{RST}\n{traceback.format_exc()}", file=sys.stderr)
            return (f"[PY ERROR IN FILE {os.path.basename(resolved_file_id or rel_file_path)}]", sys_msgs)

    def process_txt(self, rel_txt_path: str, sys_msgs: Optional[List[str]] = None) -> tuple[str, List[str]]:
        if sys_msgs is None:
            sys_msgs = []
        try:
            resolved_id = self.resolver.resolve_path(rel_txt_path)
        except Exception:
            return (f"[DSL ERROR IN FILE {os.path.basename(rel_txt_path)}]", sys_msgs)

        base_id = self.resolver.get_dirname(resolved_id)
        with self._use_base(base_id):
            try:
                raw = self.resolver.load_text(resolved_id, "txt")
            except Exception:
                return (f"[DSL ERROR IN FILE {os.path.basename(rel_txt_path)}]", sys_msgs)

            with_includes = self.process_template_content(raw, f"txt {rel_txt_path}", sys_msgs=sys_msgs)

            def repl(m: re.Match) -> str:
                name = m.group(1)
                if name in self.character.variables:
                    return "" if self.character.variables.get(name) is None else str(self.character.variables.get(name))
                app_vars = getattr(self.character, "app_vars", {}) or {}
                if name in app_vars:
                    return "" if app_vars.get(name) is None else str(app_vars.get(name))
                return ""

            final_text = self._TXT_VAR_RE.sub(repl, with_includes)
            return (final_text, sys_msgs)