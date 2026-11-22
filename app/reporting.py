"""Per-export masking. Never mutate the live result or remember full-value consent."""
from copy import deepcopy
from ipaddress import ip_address
import json
import re

EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[\w-]+', re.UNICODE)
PHONE = re.compile(r'(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)')
IPV4 = re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')
IPV6 = re.compile(r'(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.]*(?:%[\w]+)?(?!\w)')
PERSON_FIELDS = {'person', 'owner', 'username', 'user_name', 'full_name', 'first_name', 'last_name',
                 'sender', 'recipient', 'contact', 'display_name', 'handle'}
PERSON_LISTS = {'thread', 'participants', 'members', 'recipients'}
PATH_FIELDS = {'sourceFile', 'source_file', 'file', 'path', 'original_name', 'recordRef'}
# Raw free text can contain names absent from any structured identity field. Omit it in masked records.
RAW_FIELDS = {'text', 'body', 'message', 'caption', 'subject', 'title', 'snippet', 'feedback', 'description'}


def export_result(result, *, include_full_values=False):
    if type(include_full_values) is not bool:
        raise ValueError('include_full_values must be an explicit boolean')
    if include_full_values:
        return deepcopy(result)
    names = set()

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in PERSON_FIELDS or key == 'name' and not any(k in value for k in ('lat', 'lon', 'association', 'status', 'kind')):
                    if isinstance(item, str) and item.strip():
                        names.add(item.strip())
                if key in PERSON_LISTS and isinstance(item, list):
                    names.update(v.strip() for v in item if isinstance(v, str) and v.strip())
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(result)
    name_pattern = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(n) for n in sorted(names, key=lambda n: (-len(n), n))) + r')(?!\w)', re.I) if names else None

    def mask(text):
        text = EMAIL.sub('[email]', text)
        def ip(match):
            try:
                ip_address(match[0].split('%')[0])
                return '[IP]'
            except ValueError:
                return match[0]
        text = IPV4.sub(ip, text)
        text = IPV6.sub(ip, text)
        text = PHONE.sub(lambda m: '[phone]' if len(re.sub(r'\D', '', m[0])) >= 10 else m[0], text)
        return name_pattern.sub('[name]', text) if name_pattern else text

    def walk(value, *, record=False, meta=False):
        if isinstance(value, dict):
            output = {}
            for key, item in value.items():
                clean_key = mask(key)
                if key == 'records' and isinstance(item, list):
                    output[clean_key] = walk(item, record=True)
                elif key == 'inputSources' and isinstance(item, list):
                    output[clean_key] = ['[local reference]' for _ in item]
                elif key in PATH_FIELDS and isinstance(item, str):
                    output[clean_key] = '[local reference]'
                elif (record and key == 'item' or meta and key in RAW_FIELDS) and isinstance(item, str):
                    output[clean_key] = '[record text omitted]'
                elif key in PERSON_FIELDS and isinstance(item, str):
                    output[clean_key] = '[name]'
                elif key in PERSON_LISTS and isinstance(item, list):
                    output[clean_key] = ['[name]' if isinstance(v, str) else walk(v) for v in item]
                else:
                    output[clean_key] = walk(item, record=record, meta=meta or record and key == 'meta')
            return output
        if isinstance(value, list):
            return [walk(item, record=record, meta=meta) for item in value]
        return mask(value) if isinstance(value, str) else value

    return walk(result)


def json_report_bytes(result, *, include_full_values=False):
    data = export_result(result, include_full_values=include_full_values)
    return (json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
