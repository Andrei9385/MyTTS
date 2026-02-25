import json
import re
from pathlib import Path



class RussianTextFrontend:
    def __init__(self, overrides_path: str):
        self.morph = None
        self._accent_callable = self._build_accenter()
        self.overrides_path = overrides_path
        self.overrides = self._load_overrides()

    def reload_overrides(self) -> None:
        """Reload overrides from disk so API updates apply without worker restart."""
        try:
            self.overrides = self._load_overrides()
        except Exception:
            # Keep previously loaded overrides if file is temporarily invalid.
            pass

    @staticmethod
    def _build_accenter():
        # ruaccent package changed API across versions; keep workers bootable on both
        try:
            from ruaccent import RUAccent  # old API

            accenter = RUAccent()
            accenter.load(omograph_model_size='turbo3', use_dictionary=True)
            return accenter.process_all
        except Exception:
            pass

        try:
            import ruaccent  # newer APIs may expose module-level helpers

            if hasattr(ruaccent, 'accentize'):
                return getattr(ruaccent, 'accentize')
            if hasattr(ruaccent, 'process_all'):
                return getattr(ruaccent, 'process_all')
        except Exception:
            pass

        return None

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

    def apply_accents(self, text: str, use_user_overrides: bool = True, enable_auto: bool = True) -> str:
        # Keep user/manual accents with highest priority and only accentize the rest.
        word_re = r'[А-Яа-яЁё\u0301-]+'
        tokens = re.findall(r'[А-Яа-яЁё\u0301-]+|[^А-Яа-яЁё\u0301-]+', text)
        protected: dict[str, str] = {}
        out = []

        for token in tokens:
            if not re.fullmatch(word_re, token):
                out.append(token)
                continue

            low = token.replace('́', '').lower()
            replacement = None

            # 1) Manual accents in input text always win.
            if '́' in token:
                replacement = token
            # 2) User overrides have priority over auto accenting.
            elif use_user_overrides and low in self.overrides:
                replacement = self.overrides[low]

            if replacement is None:
                out.append(token)
                continue

            key = f'__ACCENT_{len(protected)}__'
            protected[key] = replacement
            out.append(key)

        joined = ''.join(out)
        if not enable_auto or self._accent_callable is None:
            result = joined
        else:
            try:
                result = self._accent_callable(joined)
            except Exception:
                result = joined

        for key, value in protected.items():
            result = result.replace(key, value)
        return result

    def preprocess(
        self,
        text: str,
        use_accenting: bool,
        use_user_overrides: bool,
        accent_mode: str = 'auto_plus_overrides',
    ) -> str:
        self.reload_overrides()
        text = self._normalize_numbers(text)
        text = self._normalize_abbr(text)
        text = re.sub(r'\s+', ' ', text).strip()
        if accent_mode == 'none':
            return text
        if accent_mode == 'overrides_only':
            return self.apply_accents(text, use_user_overrides=True, enable_auto=False)
        if use_accenting:
            text = self.apply_accents(text, use_user_overrides=use_user_overrides)
        return text

    @staticmethod
    def to_tts_stress_format(text: str, mode: str = 'none') -> str:
        """Convert stress marks to optional XTTS hints without corrupting words."""
        if mode == 'none':
            return text
        if mode == 'plus':
            return re.sub(r'([А-Яа-яЁё])\u0301', lambda m: f'+{m.group(1)}', text).replace('́', '')
        if mode == 'plus_and_acute':
            return re.sub(r'([А-Яа-яЁё])\u0301', lambda m: f'+{m.group(1)}́', text)
        return text
