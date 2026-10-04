"""Przelaczanie dostawcy modelu (Ollama <-> chmura) i zapamietywanie modelu per dostawca."""
import asyncio, json, urllib.request
from nicegui.testing import User

async def test_switch(user: User):
    import llm, i18n, d2_web as W
    i18n.save_setting('llm_provider', 'ollama')
    print('lokalnie:', llm.model())
    assert llm.model() == 'qwen3-vl:4b-instruct'
    i18n.save_setting('llm_provider', 'openai')
    print('chmura (domyslnie):', llm.model())
    assert llm.model() == 'Qwen3.5-9B'
    i18n.save_setting('llm_model_cloud', 'Qwen3-VL-32B')
    print('chmura (zmieniony):', llm.model())
    i18n.save_setting('llm_provider', 'ollama')
    print('powrot na lokalny:', llm.model())
    assert llm.model() == 'qwen3-vl:4b-instruct'
    # okno: przelaczenie dostawcy zmienia pole modelu
    await user.open('/'); await asyncio.sleep(1.5)
    W.settings_dialog(); await asyncio.sleep(0.5)
    from nicegui import ui
    sels = {e.props.get('label'): e for e in user.find(ui.select).elements}
    prov, mdl = sels['Gdzie liczy model:'], sels['Model:']
    print('pole modelu na starcie:', mdl.value)
    assert mdl.value == 'qwen3-vl:4b-instruct'
    prov.value = 'openai'; prov._handle_value_change('openai'); await asyncio.sleep(0.4)
    print('pole modelu po przelaczeniu na chmure:', mdl.value, '| opcje:', mdl.options)
    assert mdl.value == 'Qwen3-VL-32B'
    prov._handle_value_change('ollama'); await asyncio.sleep(0.3)
    print('po powrocie na lokalny:', mdl.value)
    assert mdl.value == 'qwen3-vl:4b-instruct' 
    i18n.save_setting('llm_provider', 'ollama'); i18n.save_setting('llm_model_cloud', 'Qwen3.5-9B')
