"""
llm.py - jeden interfejs do modelu: lokalna Ollama albo zdalny endpoint zgodny z OpenAI
(np. OVH AI Endpoints). Wybor w Ustawieniach; rozliczanie tokenow liczone takze po naszej stronie.

Ustawienia (settings.json):
  llm_provider : "ollama" | "openai"
  llm_model        : model lokalny (Ollama), np. "qwen3-vl:4b-instruct"
  llm_model_cloud  : model w chmurze, np. "Qwen3.5-9B"
  llm_url      : adres endpointu dla "openai" (np. https://oai.endpoints.kepler.ai.cloud.ovh.net/v1)
  llm_key_file : nazwa pliku z kluczem API w katalogu secrets/ (domyslnie api_OVH.txt)
"""
import io
import csv
import json
import time
import base64
import urllib.error
import urllib.request

import i18n
import paths

USAGE_FILE = paths.DATA / "token_usage.csv"
DEFAULTS = {"llm_provider": "ollama", "llm_model": "qwen3-vl:4b-instruct", "llm_model_cloud": "Qwen3.5-9B",
            "llm_url": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", "llm_key_file": "api_OVH.txt"}
TIMEOUT = 300
_ollama = None


def cfg(key: str):
    return i18n.settings().get(key) or DEFAULTS[key]


def provider() -> str:
    return cfg("llm_provider")


def is_local() -> bool:
    return provider() == "ollama"


def model() -> str:
    """Model wybranego dostawcy (lokalny i chmurowy sa zapamietywane osobno)."""
    return cfg("llm_model") if is_local() else cfg("llm_model_cloud")


_key_override = None     # klucz wpisany w oknie ustawien, jeszcze niezapisany - tylko na czas testu


def override_key(key):
    """Na czas testu polaczenia podstawia klucz z okna, zanim trafi do pliku."""
    global _key_override
    _key_override = (key or "").strip() or None


def api_key() -> str:
    if _key_override:
        return _key_override
    f = paths.secret(cfg("llm_key_file"))
    if not f.exists():
        return ""
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line.split()[-1]          # tez format "Authorization: Bearer xxx"
    return ""


def save_api_key(key: str, file: str = ""):
    """Klucz API idzie do pliku w secrets/, nigdy do settings.json."""
    key = (key or "").strip()
    if not key:
        return
    f = paths.secret(file or cfg("llm_key_file"))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(key + "\n", encoding="utf-8")


def ollama_client():
    global _ollama
    if _ollama is None:
        import ollama
        _ollama = ollama.Client(timeout=TIMEOUT)
    return _ollama


# ---------- licznik tokenow (nasza kontrola rozliczen) ----------
def est_text_tokens(text: str) -> int:
    """Szacunek tokenow tekstu: ~4 znaki na token (typowe dla angielskiego)."""
    return max(1, round(len(text or "") / 4))


def est_image_tokens(png: bytes) -> int:
    """Szacunek tokenow obrazu dla modeli Qwen-VL: 1 token na blok 28x28 pikseli."""
    try:
        from PIL import Image
        w, h = Image.open(io.BytesIO(png)).size
    except Exception:
        return 0
    return max(1, round(w / 28) * round(h / 28))


COLUMNS = ["czas", "dostawca", "model", "zapytanie", "nasze_wejscie", "nasze_wyjscie",
           "ich_wejscie", "ich_wyjscie", "z_cache", "rozumowanie", "sekundy"]


def log_usage(kind: str, est_in: int, est_out: int, usage: dict, seconds: float):
    """Dopisuje wiersz do token_usage.csv: nasz szacunek obok tego, co zglosil dostawca."""
    u = usage or {}
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")      # tokeny z cache sa tansze
    reason = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    row = [time.strftime("%Y-%m-%d %H:%M:%S"), provider(), model(), kind, est_in, est_out,
           u.get("prompt_tokens") if u.get("prompt_tokens") is not None else "",
           u.get("completion_tokens") if u.get("completion_tokens") is not None else "",
           cached if cached is not None else "", reason if reason is not None else "", round(seconds, 2)]
    new = not USAGE_FILE.exists()
    with open(USAGE_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(COLUMNS)
        w.writerow(row)


def usage_summary(days: int = 30) -> dict:
    """Podsumowanie z token_usage.csv: ile tokenow my naliczylismy, ile dostawca, i roznica."""
    if not USAGE_FILE.exists():
        return {}
    cut = time.time() - days * 86400
    out = {}
    with open(USAGE_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                if time.mktime(time.strptime(r["czas"], "%Y-%m-%d %H:%M:%S")) < cut:
                    continue
            except Exception:
                continue
            k = f'{r["dostawca"]} / {r["model"]}'
            d = out.setdefault(k, {"zapytan": 0, "nasze_in": 0, "nasze_out": 0, "ich_in": 0, "ich_out": 0,
                                   "cache": 0, "rozumowanie": 0, "sekundy": 0.0})
            d["zapytan"] += 1
            for a, b in (("nasze_in", "nasze_wejscie"), ("nasze_out", "nasze_wyjscie"),
                         ("ich_in", "ich_wejscie"), ("ich_out", "ich_wyjscie"),
                         ("cache", "z_cache"), ("rozumowanie", "rozumowanie")):
                d[a] += int(r.get(b) or 0)
            d["sekundy"] += float(r["sekundy"] or 0)
    price = {}
    try:
        price = {m["id"]: m.get("pricing") or {} for m in models()}
    except Exception:
        pass
    for k, d in out.items():
        ours, theirs = d["nasze_in"] + d["nasze_out"], d["ich_in"] + d["ich_out"]
        d["roznica_%"] = round(100 * (theirs - ours) / ours, 1) if ours and theirs else None
        p = price.get(k.split(" / ")[-1]) or {}
        try:    # cennik z /v1/models: cena za 1 token (prompt / completion)
            d["koszt"] = d["ich_in"] * float(p["prompt"]) + d["ich_out"] * float(p["completion"])
            d["waluta"] = p.get("currency_unit", "")
        except Exception:
            d["koszt"] = d["waluta"] = None
    return out


def models() -> list:
    """Lista modeli z endpointu (/v1/models) wraz z cennikiem i dlugoscia kontekstu."""
    if is_local():
        return [{"id": m.get("model") or m.get("name")} for m in ollama_client().list().get("models", [])]
    url = cfg("llm_url").rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key()}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")).get("data") or []


def model_info() -> dict:
    """Informacje o wybranym modelu: kontekst, cennik."""
    try:
        return next((m for m in models() if m.get("id") == model()), {})
    except Exception:
        return {}


# ---------- zapytania ----------
def _openai_chat(png: bytes, prompt: str, schema=None, max_tokens: int = 1024):
    url = cfg("llm_url").rstrip("/") + "/chat/completions"
    key = api_key()
    if not key:
        raise RuntimeError(f"brak klucza API w pliku {cfg('llm_key_file')}")
    content = [{"type": "text", "text": prompt}]
    if png:
        content.insert(0, {"type": "image_url",
                           "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}})
    body = {"model": model(), "messages": [{"role": "user", "content": content}],
            "temperature": 0, "max_tokens": max_tokens,
            "reasoning_effort": "none"}        # OCR nie potrzebuje rozumowania - oszczedza tokeny i czas
    if schema:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "result", "schema": schema, "strict": True}}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"{e.code} {e.reason}: {detail}") from None
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return text, data.get("usage") or {}


def ask(png: bytes, prompt: str, schema=None, max_tokens: int = 1024, think: bool = False,
        keep_alive=None, num_ctx: int = 8192, kind: str = "read") -> tuple:
    """Jedno zapytanie do modelu. Zwraca (tekst, diagnostyka)."""
    t0 = time.time()
    est_in = est_text_tokens(prompt) + (est_image_tokens(png) if png else 0)
    if is_local():
        kwargs = {"format": schema} if schema else {}
        msg = {"role": "user", "content": prompt}
        if png:
            msg["images"] = [png]
        resp = ollama_client().chat(model=model(), messages=[msg], think=think, keep_alive=keep_alive,
                                    options={"temperature": 0, "num_ctx": num_ctx, "num_predict": max_tokens,
                                             "repeat_penalty": 1.1}, **kwargs)
        m = resp["message"]
        text = m.get("content") or ""
        usage = {"prompt_tokens": resp.get("prompt_eval_count"), "completion_tokens": resp.get("eval_count")}
        diag = {"schema": bool(schema), "done_reason": resp.get("done_reason"), "eval_count": resp.get("eval_count"),
                "thinking": (m.get("thinking") or "")[:500],
                "prefill_s": round((resp.get("prompt_eval_duration") or 0) / 1e9, 1),
                "gen_s": round((resp.get("eval_duration") or 0) / 1e9, 1),
                "load_s": round((resp.get("load_duration") or 0) / 1e9, 1)}
    else:
        text, usage = _openai_chat(png, prompt, schema, max_tokens)
        diag = {"schema": bool(schema), "done_reason": "stop", "eval_count": usage.get("completion_tokens"),
                "thinking": "", "prefill_s": 0.0, "gen_s": round(time.time() - t0, 1), "load_s": 0.0}
    est_out = est_text_tokens(text)
    diag["tokens"] = {"nasze_in": est_in, "nasze_out": est_out,
                      "ich_in": usage.get("prompt_tokens"), "ich_out": usage.get("completion_tokens")}
    log_usage(kind, est_in, est_out, usage, time.time() - t0)
    return text, diag


def test_connection() -> tuple:
    """(ok, komunikat) - krotkie zapytanie sprawdzajace konfiguracje."""
    try:
        t0 = time.time()
        text, diag = ask(None, "Reply with the single word: ok", max_tokens=8, kind="test")
    except Exception as e:
        return False, str(e)
    tok = diag["tokens"]
    extra = ""
    if tok["ich_in"] is not None:
        extra = f" | tokeny: nasze {tok['nasze_in']}+{tok['nasze_out']}, ich {tok['ich_in']}+{tok['ich_out']}"
    return True, f"polaczenie dziala ({model()}, {time.time() - t0:.1f} s){extra}"
