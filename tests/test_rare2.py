"""Magic/rare: panel ze statami na tle maksimum dla slotu."""
import asyncio
from nicegui.testing import User
async def test_rare_panel(user: User):
    import d2_web as W
    await user.open('/'); await asyncio.sleep(2.0)
    iid = 'item_20261001_174310_483.listing.json'
    await user.should_see("Jared's Stone")
    W.select(iid); await asyncio.sleep(1.2)
    await user.should_see('Staty na tle maksimum dla tego slotu')
    await user.should_see('Faster Cast Rate')
    it = W.S.items[iid]
    print('status:', it['status'], '| staty w karcie:', W.d2jsp_post.short_stats(it['lst'], W.S.defs.get("Jared's Stone"))[0])
    print('podpowiedz:', (it['hint'] or {}).get('text','').splitlines()[:2])
