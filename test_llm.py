"""Warstwa modelu: zapytanie do endpointu OpenAI, licznik tokenow, okno ustawien."""
import asyncio, json, io, urllib.request
from nicegui.testing import User
from PIL import Image

async def test_llm(user: User):
    import llm, d2_web as W
    # 1) licznik tokenow
    buf = io.BytesIO(); Image.new("RGB", (560, 280), "black").save(buf, "PNG")
    assert llm.est_image_tokens(buf.getvalue()) == 20 * 10
    assert llm.est_text_tokens("x" * 400) == 100
    # 2) tryb chmurowy: poprawne zapytanie OpenAI i zapis zuzycia
    sent = {}
    class R:
        def __init__(s, b): s.b = b
        def __enter__(s): return s
        def __exit__(s, *a): pass
        def read(s): return s.b
    def fake(req, timeout=300):
        sent['url'] = req.full_url; sent['auth'] = req.headers.get('Authorization'); sent['body'] = json.loads(req.data)
        return R(json.dumps({"choices": [{"message": {"content": "LINE A\nLINE B"}}],
                             "usage": {"prompt_tokens": 260, "completion_tokens": 9}}).encode())
    urllib.request.urlopen = fake
    import paths
    paths.SECRETS.mkdir(parents=True, exist_ok=True)
    paths.secret('api_OVH.txt').write_text('abc123\n', encoding='utf-8')
    import i18n
    i18n.save_setting('llm_provider', 'openai'); i18n.save_setting('llm_model', 'Qwen3.5-9B')
    i18n.save_setting('llm_url', 'https://oai.endpoints.kepler.ai.cloud.ovh.net/v1')
    text, diag = llm.ask(buf.getvalue(), "read this", kind="read")
    print('url:', sent['url']); print('auth:', sent['auth'])
    print('tresc:', [c['type'] for c in sent['body']['messages'][0]['content']], '| model:', sent['body']['model'])
    print('tokeny:', diag['tokens'])
    assert sent['url'].endswith('/chat/completions') and sent['auth'] == 'Bearer abc123'
    assert diag['tokens']['ich_in'] == 260 and diag['tokens']['nasze_in'] == 202
    s = llm.usage_summary(30); print('podsumowanie:', s)
    assert list(s)[0] == 'openai / Qwen3.5-9B'
    print('reasoning_effort w zapytaniu:', sent['body'].get('reasoning_effort'))
    assert sent['body']['reasoning_effort'] == 'none'
    # usage ze szczegolami + cennik z /v1/models
    def fake2(req, timeout=300):
        if req.full_url.endswith('/models'):
            return R(json.dumps({"data": [{"id": "Qwen3.5-9B", "context_length": 262144,
                                           "pricing": {"prompt": "0.0000002", "completion": "0.0000006",
                                                       "currency_unit": "EUR"}}]}).encode())
        return R(json.dumps({"choices": [{"message": {"content": "ok"}}],
                             "usage": {"prompt_tokens": 300, "completion_tokens": 10,
                                       "prompt_tokens_details": {"cached_tokens": 120},
                                       "completion_tokens_details": {"reasoning_tokens": 0}}}).encode())
    urllib.request.urlopen = fake2
    llm.ask(None, "x", kind="read")
    print('modele:', [m['id'] for m in llm.models()], '| info:', llm.model_info().get('context_length'))
    s2 = llm.usage_summary(30)['openai / Qwen3.5-9B']
    print('cache:', s2['cache'], '| rozumowanie:', s2['rozumowanie'], '| koszt:', round(s2['koszt'], 6), s2['waluta'])
    assert s2['cache'] == 120 and s2['koszt'] > 0
    ok, msg = llm.test_connection(); print('test polaczenia:', ok, msg)
    # 3) okno ustawien pokazuje sekcje modelu
    await user.open('/'); await asyncio.sleep(1.5)
    W.settings_dialog(); await asyncio.sleep(0.5)
    await user.should_see('Model (odczyt screenow)')
    await user.should_see('Adres endpointu:')
    W.usage_dialog(); await asyncio.sleep(0.4)
    await user.should_see('Zuzycie tokenow (ostatnie 30 dni)')
    i18n.save_setting('llm_provider', 'ollama')


async def test_klucz_api_trafia_do_pliku_nie_do_ustawien(user: User):
    """Klucz wklejony w oknie zapisuje sie w pliku obok programu - settings.json zostaje bez sekretow."""
    import json as _json
    from pathlib import Path
    import i18n, llm, paths, app_config, d2_web as W
    await user.open("/")

    app_config.save({"seller_id": "123", "token": "", "llm_key": "sk-tajne-123", "llm_key_file": "api_OVH.txt"})
    zapisany = paths.secret("api_OVH.txt").read_text(encoding="utf-8").strip()
    ustawienia = _json.loads(i18n.SETTINGS.read_text(encoding="utf-8"))
    print("w pliku:", zapisany, "| klucze w settings.json:", sorted(ustawienia)[:6])
    assert zapisany == "sk-tajne-123"
    assert "sk-tajne-123" not in i18n.SETTINGS.read_text(encoding="utf-8")
    assert llm.api_key() == "sk-tajne-123"
    assert app_config.current()["llm_key"] == "sk-tajne-123"      # okno pokazuje go z pliku

    # pusty klucz nie kasuje zapisanego (zapis ustawien bez ruszania pola klucza)
    app_config.save({"seller_id": "123", "token": "", "llm_key": "", "llm_key_file": "api_OVH.txt"})
    assert llm.api_key() == "sk-tajne-123"

    # klucz z okna da sie przetestowac przed zapisaniem
    llm.override_key("sk-nowy")
    assert llm.api_key() == "sk-nowy"
    llm.override_key(None)
    assert llm.api_key() == "sk-tajne-123"
