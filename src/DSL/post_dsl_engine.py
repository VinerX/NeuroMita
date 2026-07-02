# OpenMita/DSL/post_dsl_engine.py
import re
from typing import List, Dict, Any, Tuple, Callable, TYPE_CHECKING
from core.safe_eval import SafeEvalError, safe_eval_expression
from main_logger import logger  # Use OpenMita's logger

if TYPE_CHECKING:
    from character import Character  # OpenMita's Character
    from .path_resolver import AbstractPathResolver


# (Consider moving DslError from Editor's dsl_engine to a common error module if not already)
# For now, define a local one or adapt from existing.
class PostDslError(Exception):
    pass  # Basic error class


class PostDslRule:
    def __init__(self, name: str, match_type: str, pattern_str: str, capture_names: List[str], action_lines: List[str]):
        self.name = name
        self.match_type = match_type  # "TEXT" or "REGEX"
        self.pattern_str = pattern_str
        self.compiled_pattern = re.compile(pattern_str) if match_type == "REGEX" else None
        self.capture_names = capture_names
        self.action_lines = action_lines
        self.remove_match_flag = False
        self.replace_with_expr: str | None = None

        # Pre-parse action lines for REMOVE_MATCH or REPLACE_MATCH
        final_action_lines = []
        for line in action_lines:
            if line.strip().upper() == "REMOVE_MATCH":
                self.remove_match_flag = True
            elif line.strip().upper().startswith("REPLACE_MATCH WITH "):
                self.replace_with_expr = line.strip()[len("REPLACE_MATCH WITH "):].strip()
            else:
                final_action_lines.append(line)
        self.action_lines = final_action_lines


class PostDslInterpreter:
    def __init__(self, character: "Character", resolver: "AbstractPathResolver"):
        self.character = character
        self.resolver = resolver
        self.rules: List[PostDslRule] = []
        self.debug_display_config: Dict[str, str] = {}  # { "LabelInUI": "variable_name" }
        self._local_vars: Dict[str, Any] = {} # New: for local variables within post-rules execution
        self._declared_local_vars: set[str] = set()
        self._load_rules_and_configs()  # Переименуем или вызовем новый метод

    def _parse_dsl_script_text_to_rules_and_config(self, script_text: str) -> Tuple[List[PostDslRule], Dict[str, str]]:
        """
        Parses the content of a .postscript file into a list of PostDslRule objects.
        This is a simplified parser. A more robust solution might use a dedicated parsing library
        or more complex regex for structure.
        """
        rules = []
        debug_config = {}
        current_rule_name = None
        current_match_type = None
        current_pattern_str = None
        current_capture_names = []
        current_action_lines = []
        in_actions_block = False
        in_debug_display_block = False

        for line_num, line_content in enumerate(script_text.splitlines(), 1):
            line = line_content.strip()
            if not line or line.startswith("//"):
                continue

            # 1. Удаляем комментарии в конце строки
            line = line.split("//", 1)[0].strip()

            # 2. Пропускаем пустые строки или строки, которые были только комментариями
            if not line:
                continue

            if line.upper().startswith("RULE "):
                if current_rule_name:  # Starting a new rule, finalize previous one
                    rules.append(
                        PostDslRule(current_rule_name, current_match_type, current_pattern_str, current_capture_names,
                                    current_action_lines))
                current_rule_name = line.split(maxsplit=1)[1]
                current_match_type = None
                current_pattern_str = None
                current_capture_names = []
                current_action_lines = []
                in_actions_block = False
            elif current_rule_name and line.upper().startswith("MATCH "):
                match_parts = line.split(maxsplit=2)  # MATCH TYPE "PATTERN"
                current_match_type = match_parts[1].upper()
                pattern_part = match_parts[2]

                capture_match = re.search(r"CAPTURE\s*\((.*?)\)", pattern_part, re.IGNORECASE)
                if capture_match:
                    current_capture_names = [name.strip() for name in capture_match.group(1).split(',')]
                    pattern_part = pattern_part[:capture_match.start()].strip()  # Remove CAPTURE part

                if current_match_type == "TEXT":
                    current_pattern_str = pattern_part.strip('"')
                elif current_match_type == "REGEX":
                    current_pattern_str = pattern_part.strip('"')
                elif current_match_type == "FIELD":
                    current_pattern_str = pattern_part.strip('"')
            elif current_rule_name and line.upper() == "ACTIONS":
                in_actions_block = True
            elif current_rule_name and line.upper() == "END_ACTIONS":
                in_actions_block = False
            elif current_rule_name and line.upper() == "END_RULE":
                if current_rule_name and current_match_type and current_pattern_str:
                    rules.append(
                        PostDslRule(current_rule_name, current_match_type, current_pattern_str, current_capture_names,
                                    current_action_lines))
                current_rule_name = None  # Reset for next rule
                in_actions_block = False
            elif in_actions_block:
                current_action_lines.append(line)
            elif current_rule_name and not in_actions_block and line:  # For REMOVE_MATCH or REPLACE_MATCH outside ACTIONS block
                # This logic is now handled inside PostDslRule constructor from action_lines
                pass

            if line.upper() == "DEBUG_DISPLAY":
                in_debug_display_block = True
                # Если предыдущий блок был RULE, его нужно завершить
                if current_rule_name and current_match_type and current_pattern_str:
                    rules.append(
                        PostDslRule(current_rule_name, current_match_type, current_pattern_str, current_capture_names,
                                    current_action_lines))
                    current_rule_name = None  # Сброс, чтобы не мешать DEBUG_DISPLAY
                continue  # Переходим к следующей строке

            if line.upper() == "END_DEBUG_DISPLAY":
                in_debug_display_block = False
                continue

            if in_debug_display_block:
                if ":" in line:
                    label_part, var_name_part = line.split(":", 1)
                    label = label_part.strip().strip('"')  # Убираем кавычки, если есть
                    var_name = var_name_part.strip()
                    debug_config[label] = var_name
                else:
                    logger.warning(
                        f"[{self.character.char_id}] Post-DSL: Malformed line in DEBUG_DISPLAY: '{line_content}'")

            # Не забыть добавить последнее правило, если оно не было закрыто END_RULE перед DEBUG_DISPLAY
        if current_rule_name and current_match_type and current_pattern_str:
            rules.append(PostDslRule(current_rule_name, current_match_type, current_pattern_str, current_capture_names,
                                     current_action_lines))

        logger.info(
            f"[{self.character.char_id}] Parsed {len(rules)} post-rules and {len(debug_config)} debug display entries.")
        return rules, debug_config

    def _load_rules_and_configs(self):  # Новое имя метода
        self.rules = []
        self.debug_display_config = {}
        main_rules_file = "PostScripts/main_rules.postscript"
        try:
            char_base_path = self.character.base_data_path
            # Используем resolve_path из LocalPathResolver (или другого AbstractPathResolver)
            full_path_to_rules = self.resolver.resolve_path(main_rules_file)

            content = self.resolver.load_text(full_path_to_rules, f"post_dsl script for {self.character.char_id}")
            self.rules, self.debug_display_config = self._parse_dsl_script_text_to_rules_and_config(
                content)  # Обновлено
            logger.info(
                f"[{self.character.char_id}] Loaded post-processing rules and debug config from {main_rules_file}")
        except Exception as e:
            logger.info(
                f"[{self.character.char_id}] No/Empty post-processing rules/config file found at {main_rules_file} or error loading: {e}. Post-DSL will be inactive/default debug.")
            self.rules = []
            self.debug_display_config = {}  # Сброс

    def _eval_dsl_expression(self, expr: str, context_vars: Dict[str, Any]) -> Any:
        """
        Evaluates a DSL expression.
        It needs access to character variables, local variables, and context_vars (from regex captures).
        Priority: context_vars > _local_vars > character.variables
        """
        def _default(var_name, def_val):
            return context_vars.get(
                var_name,
                self._local_vars.get(var_name, self.character.variables.get(var_name, def_val))
            )

        eval_scope = {**self.character.variables, **self._local_vars, **context_vars, **self.character.app_vars}
        allowed_calls = {
            "str": str,
            "int": int,
            "float": float,
            "len": len,
            "round": round,
            "abs": abs,
            "max": max,
            "min": min,
            "default": _default,
        }

        try:
            return safe_eval_expression(expr, names=eval_scope, allowed_calls=allowed_calls)
        except SafeEvalError as e:
            logger.error(f"[{self.character.char_id}] Post-DSL: Error evaluating expression '{expr}': {e}",
                         exc_info=True)
            raise PostDslError(f"Error evaluating expression: {expr}") from e

    def _execute_actions(self, rule: PostDslRule, match_object: re.Match | None, current_response_segment: str,
                         extra_context: Dict[str, Any] | None = None) -> Tuple[str, bool]:
        """
        Executes actions for a rule.
        Returns the modified segment and a boolean indicating if a match was processed.
        extra_context: additional variables to inject (e.g. field values for MATCH FIELD rules).
        """
        context_vars = {}
        if extra_context:
            context_vars.update(extra_context)
        if rule.match_type == "REGEX" and match_object:
            captured_values = match_object.groups()
            if len(captured_values) == len(rule.capture_names):
                for i, name in enumerate(rule.capture_names):
                    context_vars[name] = captured_values[i]
            else:  # Fallback if capture group names don't match count
                for i, val in enumerate(captured_values):
                    context_vars[f"capture_{i + 1}"] = val

        # Execute SET, LOG commands
        for line in rule.action_lines:
            parts = line.split(maxsplit=1)
            command = parts[0].upper()
            args = parts[1] if len(parts) > 1 else ""

            if command == "SET":
                is_local = False
                var_name = "" # Initialize var_name
                parts_after_set = args.split(maxsplit=1)
                if len(parts_after_set) > 1 and parts_after_set[0].upper() == "LOCAL":
                    is_local = True
                    # The var_name is part of the 'args' after 'LOCAL'
                    # So, we need to parse it from the remaining 'args'
                    remaining_args = parts_after_set[1]
                    if "=" in remaining_args:
                        var_name = remaining_args.split("=", 1)[0].strip()
                    else:
                        # Handle cases where 'SET LOCAL var_name' might be malformed without '='
                        logger.error(f"[{self.character.char_id}] Post-DSL Rule '{rule.name}': Malformed SET LOCAL command: '{line}'. Missing '='.")
                        continue # Skip this action

                    if var_name in self._local_vars:
                        continue # If already declared as local, skip re-declaration
                    args = remaining_args # Remaining part after "LOCAL"

                # This line should now always have var_name defined, either from 'LOCAL' or direct 'SET'
                # If not 'LOCAL', var_name will be parsed here
                if not is_local: # Only parse if not already parsed by 'LOCAL'
                    if "=" in args:
                        var_name = args.split("=", 1)[0].strip()
                    else:
                        logger.error(f"[{self.character.char_id}] Post-DSL Rule '{rule.name}': Malformed SET command: '{line}'. Missing '='.")
                        continue # Skip this action

                try:
                    # Ensure expr is correctly extracted after var_name
                    expr = args.split("=", 1)[1].strip()
                    value = self._eval_dsl_expression(expr, context_vars)
                    if is_local:
                        self._declared_local_vars.add(var_name)
                        self._local_vars[var_name] = value
                        # Update context_vars as well for subsequent actions in the same rule
                        context_vars[var_name] = value # Ensure it's available for current rule's context
                    else:
                        if var_name in self._declared_local_vars:
                            self._local_vars[var_name] = value
                            # Update context_vars as well for subsequent actions in the same rule
                            context_vars[var_name] = value # Ensure it's available for current rule's context
                        else:
                            self.character.set_variable(var_name, value)
                            # Update context_vars as well for subsequent actions in the same rule
                            context_vars[var_name] = value # Ensure it's available for current rule's context
                except Exception as e:
                    logger.error(
                        f"[{self.character.char_id}] Post-DSL Rule '{rule.name}': Failed to SET '{var_name}': {e}")
            elif command == "LOG":
                try:
                    log_message = self._eval_dsl_expression(args, context_vars)
                    logger.info(f"[{self.character.char_id}] Post-DSL Rule '{rule.name}' LOG: {log_message}")
                except Exception as e:
                    logger.error(f"[{self.character.char_id}] Post-DSL Rule '{rule.name}': Failed to LOG: {e}")

        # Handle REMOVE_MATCH or REPLACE_MATCH
        processed_segment = current_response_segment
        if rule.remove_match_flag:
            processed_segment = ""  # The matched part will be removed
        elif rule.replace_with_expr:
            try:
                replacement_text = str(self._eval_dsl_expression(rule.replace_with_expr, context_vars))
                processed_segment = replacement_text
            except Exception as e:
                logger.error(
                    f"[{self.character.char_id}] Post-DSL Rule '{rule.name}': Failed to evaluate REPLACE_MATCH expression: {e}. Match not replaced.")
                return current_response_segment, False  # Return original segment, indicate no successful processing for this specific action

        return processed_segment, True

    def process_structured_fields(self, fields: Dict[str, Any]) -> None:
        """Applies MATCH FIELD rules to a custom_fields dict from a StructuredResponse."""
        self._local_vars.clear()
        self._declared_local_vars.clear()

        for rule in self.rules:
            if rule.match_type != "FIELD":
                continue
            field_name = rule.pattern_str
            if field_name not in fields:
                continue
            extra_context = {field_name: fields[field_name]}
            self._execute_actions(rule, None, "", extra_context=extra_context)

    def process(self, response_text: str) -> str:
        # Clear local variables at the start of each processing cycle
        self._local_vars.clear()
        self._declared_local_vars.clear()

        modified_response = response_text

        for rule in self.rules:
            if rule.match_type == "FIELD":
                continue  # FIELD rules are handled by process_structured_fields()

            new_response_parts = []
            last_end = 0
            processed_something_for_this_rule = False

            if rule.match_type == "REGEX":
                for match in rule.compiled_pattern.finditer(modified_response):
                    start, end = match.span()
                    new_response_parts.append(modified_response[last_end:start])  # Text before match

                    original_match_text = match.group(0)
                    replacement_text, processed_ok = self._execute_actions(rule, match, original_match_text)
                    if processed_ok:
                        new_response_parts.append(replacement_text)
                        processed_something_for_this_rule = True
                    else:  # Action failed, keep original match
                        new_response_parts.append(original_match_text)
                    last_end = end
                new_response_parts.append(modified_response[last_end:])

            elif rule.match_type == "TEXT":
                current_pos = 0
                while current_pos < len(modified_response):
                    found_idx = modified_response.find(rule.pattern_str, current_pos)
                    if found_idx == -1:
                        new_response_parts.append(modified_response[current_pos:])
                        break

                    new_response_parts.append(modified_response[current_pos:found_idx])  # Text before match
                    original_match_text = rule.pattern_str
                    replacement_text, processed_ok = self._execute_actions(rule, None, original_match_text)

                    if processed_ok:
                        new_response_parts.append(replacement_text)
                        processed_something_for_this_rule = True
                    else:  # Action failed, keep original match
                        new_response_parts.append(original_match_text)

                    current_pos = found_idx + len(rule.pattern_str)
                    last_end = current_pos  # Update last_end for text matches too

            if processed_something_for_this_rule:
                modified_response = "".join(new_response_parts)

        return modified_response
