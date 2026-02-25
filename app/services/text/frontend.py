import json
import re
from pathlib import Path

import pymorphy2
from ruaccent import RUAccent


class RussianTextFrontend:
    def __init__(self, overrides_path: str):
        self.morph = pymorphy2.MorphAnalyzer()
        self.accenter = RUAccent()
        self.accenter.load(omograph_model_size='turbo3', use_dictionary=True)
        self.overrides_path = overrides_path
        self.overrides = self._load_overrides()

    def _load_overrides(self) -> dict[str, str]:
        path = Path(self.overrides_path)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def _normalize_numbers(text: str) -> str:
        repl = {
            '2024': 'две тысячи двадцать четыре',
            '2025': 'две тысячи двадцать пять',
            '24.04.3': 'двадцать четыре ноль четыре три',
        }
        for k, v in repl.items():
            text = text.replace(k, v)
        return text

    def _normalize_abbr(self, text: str) -> str:
        text = text.replace('т.д.', 'так далее').replace('т.п.', 'тому подобное')
        text = re.sub(r'\bг\.\b', 'город', text)
        return text

    @staticmethod
    def split_story(text: str) -> list[str]:
        return [x.strip() for x in re.split(r'(?<=[.!?])\s+', text) if x.strip()]

    @staticmethod
    def split_poem(text: str) -> list[str]:
        lines = text.splitlines()
        return [line if line.strip() else '__STANZA_BREAK__' for line in lines]

    def apply_accents(self, text: str, use_user_overrides: bool = True) -> str:
        # already manually accent-marked words are preserved by token replacement
        tokens = re.findall(r'[А-Яа-яЁё-]+|[^А-Яа-яЁё-]+', text)
        out = []
        for token in tokens:
            if not re.match(r'[А-Яа-яЁё-]+$', token):
                out.append(token)
                continue
            if '́' in token:
                out.append(token)
                continue
            low = token.lower()
            if use_user_overrides and low in self.overrides:
                out.append(self.overrides[low])
                continue
            out.append(token)
        joined = ''.join(out)
        return self.accenter.process_all(joined)

    def preprocess(self, text: str, use_accenting: bool, use_user_overrides: bool) -> str:
        text = self._normalize_numbers(text)
        text = self._normalize_abbr(text)
        text = re.sub(r'\s+', ' ', text).strip()
        if use_accenting:
            text = self.apply_accents(text, use_user_overrides=use_user_overrides)
        return text
